"""Run a config-driven concurrent Friends multi-ROI pilot.

This runner is the general 14-ROI path for current Friends experiments. The
episode set is read entirely from the pilot config; this script does not assume
specific seasons, copy artifacts across output roots, or replace the staged
serial ``run-multi-roi-pilot`` CLI.
"""

from __future__ import annotations

import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for path in (REPO_ROOT, SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from brain_region_pipeline.atlas.roi_config import (  # noqa: E402
    RoiDefinition,
    load_roi_definitions,
    select_roi_definitions,
    validate_roi_definitions_against_atlas,
)
from brain_region_pipeline.core.config import SummaryDescriptionsConfig  # noqa: E402
from brain_region_pipeline.core.dependencies import (  # noqa: E402
    PipelineDependencies,
    default_dependencies,
)
from brain_region_pipeline.pilot.runner import (  # noqa: E402
    PilotConfig,
    PilotEpisode,
    _dry_run,
    _run_encoding,
    _summary_path,
    _validate_episode_inputs,
    _write_manifest,
    load_pilot_config,
)
from brain_region_pipeline.scoring.summary_generator import (  # noqa: E402
    summarize_descriptions_from_file,
)
from run_friends_7roi_vertex_pilot import (  # noqa: E402
    _retry_failed_batches,
    _run_domain_pool_jobs,
    _run_parallel,
    _run_schema_jobs,
    _run_scoring_jobs,
    _validate_full_outputs,
)

DEFAULT_CONFIG = REPO_ROOT / "configs" / "friends_multi_roi_pilot.json"
DEFAULT_SUMMARY_WORKERS = 1
DEFAULT_WORKERS = 4


@dataclass(frozen=True)
class RunOptions:
    """Runtime options for the config-driven concurrent pilot."""

    config_path: Path
    summary_workers: int
    domain_workers: int
    schema_workers: int
    scoring_workers: int
    dry_run: bool
    retry_failed_batches: bool
    skip_existing_summaries: bool
    overwrite_scoring: bool


def _log(message: str) -> None:
    print(f"[friends_14roi_concurrent_pilot] {message}", flush=True)


def _resolve_workspace_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def parse_args(argv: Sequence[str] | None = None) -> RunOptions:
    """Parse script options without mutating global environment."""

    parser = ArgumentParser(description="Run the config-driven Friends 14-ROI concurrent pilot.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Pilot config JSON.")
    parser.add_argument("--summary-workers", type=int, default=DEFAULT_SUMMARY_WORKERS)
    parser.add_argument("--domain-workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--schema-workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--scoring-workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--retry-failed-batches",
        action="store_true",
        help="Retry only batch_generation_failed_zero_filled scoring batches, then refresh encoding.",
    )
    parser.add_argument(
        "--skip-existing-summaries",
        action="store_true",
        help="Skip already complete summary outputs in this config's output_root.",
    )
    parser.add_argument(
        "--overwrite-scoring",
        action="store_true",
        help="Clear generated scoring outputs before scoring. Default is resume-only.",
    )
    args = parser.parse_args(argv)
    for flag in ("summary_workers", "domain_workers", "schema_workers", "scoring_workers"):
        if getattr(args, flag) < 1:
            raise ValueError(f"--{flag.replace('_', '-')} must be at least 1.")
    return RunOptions(
        config_path=_resolve_workspace_path(args.config),
        summary_workers=args.summary_workers,
        domain_workers=args.domain_workers,
        schema_workers=args.schema_workers,
        scoring_workers=args.scoring_workers,
        dry_run=args.dry_run,
        retry_failed_batches=args.retry_failed_batches,
        skip_existing_summaries=args.skip_existing_summaries,
        overwrite_scoring=args.overwrite_scoring,
    )


def _load_run_inputs(config_path: Path) -> tuple[PilotConfig, list[RoiDefinition], dict[str, int]]:
    """Load config and validate static ROI, atlas, description, and H5 inputs."""

    config = load_pilot_config(config_path)
    roi_definitions = load_roi_definitions(config.roi_definitions)
    rois = list(select_roi_definitions(roi_definitions, config.rois))
    counts = validate_roi_definitions_against_atlas(rois, config.atlas_labels)
    _validate_episode_inputs(config)
    return config, rois, counts


def _summary_exists(config: PilotConfig, episode: PilotEpisode) -> bool:
    summary = _summary_path(config, episode)
    return summary.exists() and summary.with_name("summary_metadata.json").exists()


def _run_summary_job(
    *,
    config: PilotConfig,
    episode: PilotEpisode,
    skip_existing: bool,
) -> None:
    """Generate one episode rolling summary unless an existing complete one is reused."""

    summary = _summary_path(config, episode)
    metadata = summary.with_name("summary_metadata.json")
    if summary.exists() or metadata.exists():
        if skip_existing and summary.exists() and metadata.exists():
            _log(f"Summary already complete: {episode.episode_id}")
            return
        raise ValueError(
            f"Summary output already exists for {episode.episode_id}; "
            "pass --skip-existing-summaries to reuse complete summary outputs.",
        )
    summarize_descriptions_from_file(
        Namespace(
            descriptions=str(episode.descriptions),
            output_file=str(summary),
        ),
        SummaryDescriptionsConfig(
            generation_provider=config.generation_provider,
            generation_model=config.generation_model,
        ),
    )


def _run_summary_jobs(
    *,
    config: PilotConfig,
    workers: int,
    skip_existing: bool,
) -> None:
    """Generate shared summaries for all configured episodes."""

    jobs: list[tuple[str, Callable[[], None]]] = []
    for episode in config.episodes:
        if skip_existing and _summary_exists(config, episode):
            _log(f"Summary already complete: {episode.episode_id}")
            continue
        jobs.append(
            (
                episode.episode_id,
                lambda episode=episode: _run_summary_job(
                    config=config,
                    episode=episode,
                    skip_existing=skip_existing,
                ),
            ),
        )
    _run_parallel(stage_name="summaries", workers=workers, jobs=jobs)


def _print_dry_run(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    counts: dict[str, int],
    options: RunOptions,
) -> None:
    """Validate static inputs and print the planned concurrent full run."""

    _dry_run(config, rois, "all")
    _log(
        "Workers: "
        f"summary={options.summary_workers}, domain={options.domain_workers}, "
        f"schema={options.schema_workers}, scoring={options.scoring_workers}",
    )
    _log("Parcel counts: " + ", ".join(f"{roi_id}={count}" for roi_id, count in counts.items()))


def _run_full(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    options: RunOptions,
    deps: PipelineDependencies,
) -> None:
    """Run the complete config-driven concurrent workflow."""

    config.output_root.mkdir(parents=True, exist_ok=True)
    _log("Step 1/6: Generate summaries")
    _run_summary_jobs(
        config=config,
        workers=options.summary_workers,
        skip_existing=options.skip_existing_summaries,
    )

    _log("Step 2/6: Generate domain pools")
    _run_domain_pool_jobs(config, rois, deps=deps, workers=options.domain_workers)

    _log("Step 3/6: Generate schemas")
    _run_schema_jobs(config, rois, deps=deps, workers=options.schema_workers)

    _log("Step 4/6: Score ROI/episode pairs")
    _run_scoring_jobs(
        config,
        rois,
        config.episodes,
        deps=deps,
        workers=options.scoring_workers,
        overwrite_scoring=options.overwrite_scoring,
    )

    _log("Step 5/6: Write manifest and fit encoding")
    _write_manifest(config, rois)
    _run_encoding(config)

    _log("Step 6/6: Validate outputs")
    _validate_full_outputs(config, rois)
    _log("Concurrent pilot run complete.")


def main(argv: Sequence[str] | None = None) -> None:
    """Run dry-run, full, or failed-batch retry modes."""

    options = parse_args(argv)
    config, rois, counts = _load_run_inputs(options.config_path)
    if options.dry_run:
        _print_dry_run(config=config, rois=rois, counts=counts, options=options)
        return
    deps = default_dependencies()
    if options.retry_failed_batches:
        _retry_failed_batches(config=config, rois=rois, options=options, deps=deps)
        return
    _run_full(config=config, rois=rois, options=options, deps=deps)


if __name__ == "__main__":
    main()
