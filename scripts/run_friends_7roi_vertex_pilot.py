"""Run the one-off Friends 7-ROI Vertex Gemini multi-ROI pilot.

The maintained CLI stays serial and general-purpose. This script is scoped to a
single research run: copy known-good summaries, run a smoke path, then run the
LLM-heavy ROI stages concurrently while reusing the maintained stage runners.
"""

from __future__ import annotations

import os
import shutil
import sys
from argparse import ArgumentParser
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brain_region_pipeline.atlas.roi_config import (
    RoiDefinition,
    load_roi_definitions,
    select_roi_definitions,
    validate_roi_definitions_against_atlas,
)
from brain_region_pipeline.core.config import GEMINI_GENERATION_PROVIDER
from brain_region_pipeline.core.dependencies import (
    PipelineDependencies,
    default_dependencies,
)
from brain_region_pipeline.core.genai import resolve_gemini_api_key
from brain_region_pipeline.core.io_utils import file_sha256
from brain_region_pipeline.pilot.concurrent import (
    ConcurrentPilotStages,
    require_paths,
    run_parallel,
    validate_full_outputs,
    validate_scoring_outputs,
)
from brain_region_pipeline.pilot.runner import (
    PilotConfig,
    PilotEpisode,
    _domain_pool_auto_confirmed_path,
    _domain_pool_draft_path,
    _dry_run,
    _region_schema_path,
    _summary_path,
    _validate_episode_inputs,
    load_pilot_config,
)

DEFAULT_CONFIG = REPO_ROOT / "configs" / "friends_7roi_vertex_gemini35_pilot_20260605.json"
DEFAULT_SOURCE_SUMMARIES = REPO_ROOT / "friends" / "demo" / "multi_roi_pilot" / "summaries"
DEFAULT_WORKERS = 4
DEFAULT_SMOKE_ROI = "VMPFC"
DEFAULT_SMOKE_EPISODE = "s01e03a"


@dataclass(frozen=True)
class RunOptions:
    """Runtime options for the one-off Vertex pilot run."""

    config_path: Path
    source_summaries: Path
    domain_workers: int
    schema_workers: int
    scoring_workers: int
    smoke_roi: str
    smoke_episode: str
    dry_run: bool
    skip_smoke: bool
    smoke_only: bool
    retry_failed_batches: bool
    overwrite_scoring: bool


def _log(message: str) -> None:
    print(f"[friends_vertex_pilot] {message}", flush=True)


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_workspace_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def parse_args(argv: Sequence[str] | None = None) -> RunOptions:
    """Parse script options without mutating global environment."""

    parser = ArgumentParser(description="Run the Friends 7-ROI Vertex Gemini pilot.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="7-ROI pilot config JSON.")
    parser.add_argument(
        "--source-summaries",
        default=str(DEFAULT_SOURCE_SUMMARIES),
        help="Existing multi-pilot summaries to copy into the new output root.",
    )
    parser.add_argument("--domain-workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--schema-workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--scoring-workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--smoke-roi", default=DEFAULT_SMOKE_ROI)
    parser.add_argument("--smoke-episode", default=DEFAULT_SMOKE_EPISODE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--smoke-only", action="store_true")
    parser.add_argument(
        "--retry-failed-batches",
        action="store_true",
        help=(
            "Retry only batch_generation_failed_zero_filled scoring batches, "
            "then refresh encoding."
        ),
    )
    parser.add_argument(
        "--overwrite-scoring",
        action="store_true",
        help="Clear generated scoring outputs before scoring. Default is resume-only.",
    )
    args = parser.parse_args(argv)
    if args.skip_smoke and args.smoke_only:
        raise ValueError("--skip-smoke and --smoke-only cannot be used together.")
    for flag in ("domain_workers", "schema_workers", "scoring_workers"):
        if getattr(args, flag) < 1:
            raise ValueError(f"--{flag.replace('_', '-')} must be at least 1.")
    return RunOptions(
        config_path=_resolve_workspace_path(args.config),
        source_summaries=_resolve_workspace_path(args.source_summaries),
        domain_workers=args.domain_workers,
        schema_workers=args.schema_workers,
        scoring_workers=args.scoring_workers,
        smoke_roi=args.smoke_roi,
        smoke_episode=args.smoke_episode,
        dry_run=args.dry_run,
        skip_smoke=args.skip_smoke,
        smoke_only=args.smoke_only,
        retry_failed_batches=args.retry_failed_batches,
        overwrite_scoring=args.overwrite_scoring,
    )


def _load_run_inputs(
    options: RunOptions,
) -> tuple[PilotConfig, list[RoiDefinition], dict[str, int]]:
    """Load config, validate fMRI/description inputs, and select fixed ROIs."""

    config = load_pilot_config(options.config_path)
    roi_definitions = load_roi_definitions(config.roi_definitions)
    rois = select_roi_definitions(roi_definitions, config.rois)
    counts = validate_roi_definitions_against_atlas(rois, config.atlas_labels)
    _validate_episode_inputs(config)
    return config, list(rois), counts


def _validate_vertex_env(config: PilotConfig) -> None:
    """Fail fast if this run would not use Vertex Gemini API-key mode."""

    if config.generation_provider != GEMINI_GENERATION_PROVIDER:
        raise ValueError(
            "This one-off runner is only for generation_provider='gemini'; "
            f"got {config.generation_provider!r}.",
        )
    # resolve_gemini_api_key loads the project .env through the maintained
    # genai helper, keeping this script aligned with the actual call path.
    resolve_gemini_api_key()
    if not (_env_flag("GEMINI_USE_VERTEXAI") or _env_flag("GOOGLE_GENAI_USE_VERTEXAI")):
        raise RuntimeError(
            "Set GEMINI_USE_VERTEXAI=true or GOOGLE_GENAI_USE_VERTEXAI=true "
            "before running the Vertex Gemini pilot.",
        )
    if os.environ.get("GEMINI_BASE_URL"):
        _log("GEMINI_BASE_URL is set but ignored because Vertex AI mode is enabled.")


def _copy_summary_file(source: Path, destination: Path) -> None:
    """Copy one summary artifact, refusing to change an existing different file."""

    if not source.exists():
        raise FileNotFoundError(f"Missing source summary artifact: {source}")
    if destination.exists():
        if file_sha256(source) != file_sha256(destination):
            raise ValueError(
                "Refusing to overwrite a different copied summary artifact: "
                f"{destination}",
            )
        _log(f"Summary already copied: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    _log(f"Copied summary artifact: {destination}")


def copy_summaries(
    config: PilotConfig,
    *,
    source_root: Path,
    episodes: Sequence[PilotEpisode] | None = None,
) -> None:
    """Copy source summaries into the new output root for self-contained outputs."""

    selected_episodes = episodes or config.episodes
    for episode in selected_episodes:
        source_dir = source_root / episode.episode_id
        destination_dir = _summary_path(config, episode).parent
        _copy_summary_file(source_dir / "summary.json", destination_dir / "summary.json")
        _copy_summary_file(
            source_dir / "summary_metadata.json",
            destination_dir / "summary_metadata.json",
        )


def _one_roi(rois: Sequence[RoiDefinition], roi_id: str) -> RoiDefinition:
    for roi in rois:
        if roi.roi_id == roi_id:
            return roi
    raise ValueError(f"Smoke ROI {roi_id!r} is not in the configured ROI set.")


def _one_episode(config: PilotConfig, episode_id: str) -> PilotEpisode:
    for episode in config.episodes:
        if episode.episode_id == episode_id:
            return episode
    raise ValueError(f"Smoke episode {episode_id!r} is not in the configured episode set.")


def _run_parallel(
    *,
    stage_name: str,
    workers: int,
    jobs: Sequence[tuple[str, Callable[[], None]]],
) -> None:
    run_parallel(stage_name=stage_name, workers=workers, jobs=jobs, log=_log)


def _run_domain_pool_jobs(
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    *,
    deps: PipelineDependencies,
    workers: int,
) -> None:
    ConcurrentPilotStages(config=config, deps=deps, log=_log).run_domain_pool_jobs(
        rois,
        workers=workers,
    )


def _run_schema_jobs(
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    *,
    deps: PipelineDependencies,
    workers: int,
) -> None:
    ConcurrentPilotStages(config=config, deps=deps, log=_log).run_schema_jobs(
        rois,
        workers=workers,
    )


def _run_scoring_jobs(
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    episodes: Sequence[PilotEpisode],
    *,
    deps: PipelineDependencies,
    workers: int,
    overwrite_scoring: bool,
) -> None:
    ConcurrentPilotStages(config=config, deps=deps, log=_log).run_scoring_jobs(
        rois,
        episodes,
        workers=workers,
        overwrite_scoring=overwrite_scoring,
    )


def _retry_failed_batches(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    options: RunOptions,
    deps: PipelineDependencies,
) -> None:
    ConcurrentPilotStages(config=config, deps=deps, log=_log).retry_failed_batches(
        rois,
        workers=options.scoring_workers,
    )


def _require_paths(paths: Sequence[Path], *, context: str) -> None:
    require_paths(paths, context=context)


def _validate_scoring_outputs(
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    episodes: Sequence[PilotEpisode],
) -> None:
    validate_scoring_outputs(config, rois, episodes)


def _run_smoke(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    options: RunOptions,
    deps: PipelineDependencies,
) -> None:
    smoke_roi = _one_roi(rois, options.smoke_roi)
    smoke_episode = _one_episode(config, options.smoke_episode)
    _log(f"Smoke path: ROI={smoke_roi.roi_id}, episode={smoke_episode.episode_id}")
    _run_domain_pool_jobs(
        config,
        [smoke_roi],
        deps=deps,
        workers=options.domain_workers,
    )
    _run_schema_jobs(
        config,
        [smoke_roi],
        deps=deps,
        workers=options.schema_workers,
    )
    _run_scoring_jobs(
        config,
        [smoke_roi],
        [smoke_episode],
        deps=deps,
        workers=options.scoring_workers,
        overwrite_scoring=options.overwrite_scoring,
    )
    _require_paths(
        [
            _domain_pool_draft_path(config, smoke_roi.roi_id),
            _domain_pool_auto_confirmed_path(config, smoke_roi.roi_id),
            _region_schema_path(config, smoke_roi.roi_id),
        ],
        context="Smoke validation",
    )
    _validate_scoring_outputs(config, [smoke_roi], [smoke_episode])
    _log("Smoke path complete.")


def _run_full(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    options: RunOptions,
    deps: PipelineDependencies,
) -> None:
    stages = ConcurrentPilotStages(config=config, deps=deps, log=_log)
    _log("Full run: domain pools")
    stages.run_domain_pool_jobs(rois, workers=options.domain_workers)
    _log("Full run: schemas")
    stages.run_schema_jobs(rois, workers=options.schema_workers)
    _log("Full run: scoring")
    stages.run_scoring_jobs(
        rois,
        config.episodes,
        workers=options.scoring_workers,
        overwrite_scoring=options.overwrite_scoring,
    )
    _log("Full run: manifest")
    stages.write_manifest(rois)
    _log("Full run: encoding")
    stages.run_encoding()
    stages.validate_full_outputs(rois)


def _validate_full_outputs(config: PilotConfig, rois: Sequence[RoiDefinition]) -> None:
    validate_full_outputs(config, rois)


def _print_dry_run(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    counts: dict[str, int],
    options: RunOptions,
) -> None:
    _dry_run(config, rois, "all")
    _log(f"Source summaries: {options.source_summaries}")
    _log(
        "Concurrent workers: "
        f"domain={options.domain_workers}, schema={options.schema_workers}, "
        f"scoring={options.scoring_workers}",
    )
    _log(f"Smoke path: {options.smoke_roi}/{options.smoke_episode}")
    _log("Parcel counts: " + ", ".join(f"{roi_id}={count}" for roi_id, count in counts.items()))


def main(argv: Sequence[str] | None = None) -> None:
    """Run dry-run, smoke-only, or smoke-then-full Vertex pilot workflow."""

    options = parse_args(argv)
    config, rois, counts = _load_run_inputs(options)
    if options.dry_run:
        _print_dry_run(config=config, rois=rois, counts=counts, options=options)
        return
    _validate_vertex_env(config)
    copy_summaries(config, source_root=options.source_summaries)
    deps = default_dependencies()
    if options.retry_failed_batches:
        _retry_failed_batches(config=config, rois=rois, options=options, deps=deps)
        return
    if not options.skip_smoke:
        _run_smoke(config=config, rois=rois, options=options, deps=deps)
    if options.smoke_only:
        return
    _run_full(config=config, rois=rois, options=options, deps=deps)


if __name__ == "__main__":
    main()
