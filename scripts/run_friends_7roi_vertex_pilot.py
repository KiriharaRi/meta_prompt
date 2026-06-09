"""Run the one-off Friends 7-ROI Vertex Gemini multi-ROI pilot.

The maintained CLI stays serial and general-purpose. This script is scoped to a
single research run: copy known-good summaries, run a smoke path, then run the
LLM-heavy ROI stages concurrently while reusing the maintained stage runners.
"""

from __future__ import annotations

import os
import shutil
import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brain_region_pipeline.atlas.roi_config import (
    RoiDefinition,
    load_roi_definitions,
    select_roi_definitions,
    validate_roi_definitions_against_atlas,
)
from brain_region_pipeline.core.config import (
    GEMINI_GENERATION_PROVIDER,
    DomainPoolConfig,
    RegionSchemaConfig,
    ScoreDescriptionsConfig,
)
from brain_region_pipeline.core.dependencies import (
    PipelineDependencies,
    default_dependencies,
)
from brain_region_pipeline.core.genai import resolve_gemini_api_key
from brain_region_pipeline.core.io_utils import file_sha256, read_jsonl, write_jsonl
from brain_region_pipeline.pilot.runner import (
    PilotConfig,
    PilotEpisode,
    _confirm_domain_pool_for_pilot,
    _domain_pool_auto_confirmed_path,
    _domain_pool_draft_path,
    _domain_pool_for_schema,
    _dry_run,
    _encoding_dir,
    _manifest_path,
    _region_schema_path,
    _roi_schema_mapping_path,
    _scoring_dir,
    _summary_path,
    _run_encoding,
    _validate_episode_inputs,
    _write_manifest,
    load_pilot_config,
)
from brain_region_pipeline.schema_design.domain_pool import load_domain_pool
from brain_region_pipeline.schema_design.region_schema import load_region_schema
from brain_region_pipeline.schema_design.runner import (
    make_domain_pool,
    make_region_schema,
)
from brain_region_pipeline.scoring.checkpoint import scoring_output_paths
from brain_region_pipeline.scoring.description_io import load_description_segments
from brain_region_pipeline.scoring.runner import score_descriptions_from_file
from brain_region_pipeline.scoring.runner import _normalize_batch_score_metadata

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
        help="Retry only batch_generation_failed_zero_filled scoring batches, then refresh encoding.",
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


def _load_run_inputs(options: RunOptions) -> tuple[PilotConfig, list[RoiDefinition], dict[str, int]]:
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
    """Run independent jobs concurrently and report every failed job."""

    if not jobs:
        return
    max_workers = min(workers, len(jobs))
    _log(f"{stage_name}: {len(jobs)} job(s), workers={max_workers}")
    failures: list[tuple[str, BaseException]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(job): label for label, job in jobs}
        for future in as_completed(futures):
            label = futures[future]
            try:
                future.result()
                _log(f"{stage_name} complete: {label}")
            except BaseException as exc:  # noqa: BLE001 - aggregate and rethrow below.
                failures.append((label, exc))
                _log(f"{stage_name} failed: {label}: {exc}")
    if failures:
        lines = "\n".join(f"- {label}: {exc}" for label, exc in failures)
        raise RuntimeError(f"{stage_name} failed for {len(failures)} job(s):\n{lines}")


def _validate_domain_pool(path: Path, *, roi_id: str, expected_status: str | None = None) -> None:
    pool = load_domain_pool(path)
    if pool.target_region != roi_id:
        raise ValueError(f"{path} target_region {pool.target_region!r} != {roi_id!r}.")
    if expected_status and pool.curation_status != expected_status:
        raise ValueError(f"{path} curation_status {pool.curation_status!r} != {expected_status!r}.")


def _run_domain_pool_job(
    *,
    config: PilotConfig,
    roi: RoiDefinition,
    deps: PipelineDependencies,
) -> None:
    draft_path = _domain_pool_draft_path(config, roi.roi_id)
    confirmed_path = _domain_pool_auto_confirmed_path(config, roi.roi_id)
    if confirmed_path.exists() and not draft_path.exists():
        raise ValueError(f"Cannot resume {roi.roi_id}: missing draft domain pool {draft_path}.")
    if draft_path.exists() and confirmed_path.exists():
        _validate_domain_pool(draft_path, roi_id=roi.roi_id)
        _validate_domain_pool(confirmed_path, roi_id=roi.roi_id, expected_status="confirmed")
        _log(f"Domain pool already complete: {roi.roi_id}")
        return
    if not draft_path.exists():
        make_domain_pool(
            Namespace(
                atlas_labels=str(config.atlas_labels),
                target_region=roi.roi_id,
                output_file=str(draft_path),
                model=config.generation_model,
                provider=config.generation_provider,
                proposal_runs=config.proposal_runs,
            ),
            DomainPoolConfig(
                generation_provider=config.generation_provider,
                generation_model=config.generation_model,
                target_region=roi.roi_id,
                proposal_runs=config.proposal_runs,
            ),
            deps=deps,
        )
    _confirm_domain_pool_for_pilot(draft_path, confirmed_path)
    _validate_domain_pool(confirmed_path, roi_id=roi.roi_id, expected_status="confirmed")


def _run_domain_pool_jobs(
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    *,
    deps: PipelineDependencies,
    workers: int,
) -> None:
    _run_parallel(
        stage_name="domain-pools",
        workers=workers,
        jobs=[
            (
                roi.roi_id,
                lambda roi=roi: _run_domain_pool_job(config=config, roi=roi, deps=deps),
            )
            for roi in rois
        ],
    )


def _run_schema_job(
    *,
    config: PilotConfig,
    roi: RoiDefinition,
    deps: PipelineDependencies,
) -> None:
    schema_path = _region_schema_path(config, roi.roi_id)
    if schema_path.exists():
        schema = load_region_schema(schema_path)
        if schema.target_region != roi.roi_id:
            raise ValueError(f"{schema_path} target_region {schema.target_region!r} != {roi.roi_id!r}.")
        _log(f"Schema already complete: {roi.roi_id}")
        return
    make_region_schema(
        Namespace(
            atlas_labels=str(config.atlas_labels),
            target_region=roi.roi_id,
            output_file=str(schema_path),
            model=config.generation_model,
            provider=config.generation_provider,
            domain_pool=str(_domain_pool_for_schema(config, roi.roi_id)),
            roi_definitions=str(config.roi_definitions),
            roi_id=roi.roi_id,
        ),
        RegionSchemaConfig(
            generation_provider=config.generation_provider,
            generation_model=config.generation_model,
            target_region=roi.roi_id,
        ),
        deps=deps,
    )


def _run_schema_jobs(
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    *,
    deps: PipelineDependencies,
    workers: int,
) -> None:
    _run_parallel(
        stage_name="schemas",
        workers=workers,
        jobs=[
            (
                roi.roi_id,
                lambda roi=roi: _run_schema_job(config=config, roi=roi, deps=deps),
            )
            for roi in rois
        ],
    )


def _run_scoring_job(
    *,
    config: PilotConfig,
    roi: RoiDefinition,
    episode: PilotEpisode,
    deps: PipelineDependencies,
    overwrite_scoring: bool,
) -> None:
    score_descriptions_from_file(
        Namespace(
            descriptions=str(episode.descriptions),
            region_schema=str(_region_schema_path(config, roi.roi_id)),
            output_dir=str(_scoring_dir(config, roi.roi_id, episode)),
            model=config.generation_model,
            tr_s=config.tr_s,
            total_trs=None,
            resume=not overwrite_scoring,
            overwrite=overwrite_scoring,
            summary_file=str(_summary_path(config, episode)),
            provider=config.generation_provider,
            scoring_batch_size=config.scoring_batch_size,
            local_buffer_size=config.local_buffer_size,
            gt_dir=None,
            gt_file_pattern="*.csv",
            gt_time_column="视频时间(s)",
            gt_emotion_column="情绪值",
            alignment="overlap_weighted",
        ),
        ScoreDescriptionsConfig(
            generation_provider=config.generation_provider,
            generation_model=config.generation_model,
            tr_s=config.tr_s,
            scoring_batch_size=config.scoring_batch_size,
            local_buffer_size=config.local_buffer_size,
        ),
        deps=deps,
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
    jobs: list[tuple[str, Callable[[], None]]] = []
    for roi in rois:
        for episode in episodes:
            jobs.append(
                (
                    f"{roi.roi_id}/{episode.episode_id}",
                    lambda roi=roi, episode=episode: _run_scoring_job(
                        config=config,
                        roi=roi,
                        episode=episode,
                        deps=deps,
                        overwrite_scoring=overwrite_scoring,
                    ),
                ),
            )
    _run_parallel(stage_name="scoring", workers=workers, jobs=jobs)


def _scoring_args(config: PilotConfig, roi: RoiDefinition, episode: PilotEpisode) -> Namespace:
    """Build a score-descriptions Namespace for one ROI/episode job."""

    return Namespace(
        descriptions=str(episode.descriptions),
        region_schema=str(_region_schema_path(config, roi.roi_id)),
        output_dir=str(_scoring_dir(config, roi.roi_id, episode)),
        model=config.generation_model,
        tr_s=config.tr_s,
        total_trs=None,
        resume=True,
        overwrite=False,
        summary_file=str(_summary_path(config, episode)),
        provider=config.generation_provider,
        scoring_batch_size=config.scoring_batch_size,
        local_buffer_size=config.local_buffer_size,
        gt_dir=None,
        gt_file_pattern="*.csv",
        gt_time_column="视频时间(s)",
        gt_emotion_column="情绪值",
        alignment="overlap_weighted",
    )


def _score_config(config: PilotConfig) -> ScoreDescriptionsConfig:
    """Build the scoring config shared by normal scoring and batch retries."""

    return ScoreDescriptionsConfig(
        generation_provider=config.generation_provider,
        generation_model=config.generation_model,
        tr_s=config.tr_s,
        scoring_batch_size=config.scoring_batch_size,
        local_buffer_size=config.local_buffer_size,
    )


def _failed_batch_indices(output_dir: Path) -> list[int]:
    """Return sorted failed batch indexes recorded for one scoring output dir."""

    warning_path = scoring_output_paths(output_dir)["warnings"]
    if not warning_path.exists():
        return []
    rows = read_jsonl(warning_path)
    failed = {
        int(row["batch_idx"])
        for row in rows
        if row.get("reason") == "batch_generation_failed_zero_filled"
        and row.get("batch_idx") is not None
    }
    return sorted(failed)


def _replace_score_rows(
    *,
    output_dir: Path,
    replacement_rows: Sequence,
    batch_idx: int,
) -> None:
    """Replace serialized score rows for one batch with retry results."""

    score_path = scoring_output_paths(output_dir)["scores"]
    rows = read_jsonl(score_path)
    replacements = [row.to_dict() for row in replacement_rows]
    replacement_ids = {int(row["segment_id"]) for row in replacements}
    if not replacement_ids:
        raise ValueError(f"Retry for batch {batch_idx} produced no replacement rows.")
    filtered = [
        row
        for row in rows
        if int(row.get("segment_id", -1)) not in replacement_ids
    ]
    combined = sorted(
        [*filtered, *replacements],
        key=lambda row: int(row["segment_id"]),
    )
    if len(combined) != len(rows):
        raise ValueError(
            f"Retry replacement row count mismatch for {output_dir}: "
            f"{len(combined)} != {len(rows)}.",
        )
    write_jsonl(score_path, combined)


def _rewrite_warning_rows(
    *,
    output_dir: Path,
    retried_batch_idx: int,
    new_warnings: Sequence[dict],
) -> None:
    """Drop the old failed-batch warning and keep any new retry warnings."""

    warning_path = scoring_output_paths(output_dir)["warnings"]
    existing = read_jsonl(warning_path) if warning_path.exists() else []
    filtered = [
        row
        for row in existing
        if not (
            row.get("reason") == "batch_generation_failed_zero_filled"
            and int(row.get("batch_idx", -1)) == retried_batch_idx
        )
    ]
    rows = [*filtered, *[dict(row) for row in new_warnings]]
    if rows:
        write_jsonl(warning_path, rows)
    elif warning_path.exists():
        warning_path.unlink()


def _retry_failed_batch_job(
    *,
    config: PilotConfig,
    roi: RoiDefinition,
    episode: PilotEpisode,
    batch_idx: int,
    deps: PipelineDependencies,
    mutation_lock: Lock,
) -> tuple[str, bool]:
    """Retry one failed score batch and refresh that episode's derived outputs."""

    label = f"{roi.roi_id}/{episode.episode_id}/batch{batch_idx}"
    args = _scoring_args(config, roi, episode)
    cfg = _score_config(config)
    output_dir = Path(args.output_dir)
    schema = load_region_schema(args.region_schema)
    segments = load_description_segments(args.descriptions)
    with Path(args.summary_file).open("r", encoding="utf-8") as handle:
        import json

        summaries = json.load(handle)
    batch_start = batch_idx * cfg.scoring_batch_size
    if batch_start >= len(segments):
        raise ValueError(f"{label}: batch_start {batch_start} exceeds segment count.")
    retry_warnings: list[dict] = []
    rows = deps.score_description_segment_batch(
        batch_idx,
        batch_start,
        segments,
        schema,
        cfg,
        summaries,
        retry_warnings,
    )
    rows = _normalize_batch_score_metadata(
        batch_scores=rows,
        batch_start=batch_start,
        batch_idx=batch_idx,
        total_segments=len(segments),
        cfg=cfg,
    )
    with mutation_lock:
        _replace_score_rows(output_dir=output_dir, replacement_rows=rows, batch_idx=batch_idx)
        _rewrite_warning_rows(
            output_dir=output_dir,
            retried_batch_idx=batch_idx,
            new_warnings=retry_warnings,
        )
        # Reuse the maintained runner to regenerate TR features, readable rows,
        # metadata, and progress from the updated complete score rows.
        score_descriptions_from_file(args, cfg, deps=deps)
    still_failed = any(
        row.get("reason") == "batch_generation_failed_zero_filled"
        and int(row.get("batch_idx", -1)) == batch_idx
        for row in retry_warnings
    )
    return label, not still_failed


def _retry_failed_batches(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    options: RunOptions,
    deps: PipelineDependencies,
) -> None:
    """Retry only previously zero-filled failed scoring batches."""

    jobs: list[tuple[str, Callable[[], None]]] = []
    retry_labels: list[str] = []
    mutation_locks: dict[Path, Lock] = {}
    for roi in rois:
        for episode in config.episodes:
            output_dir = _scoring_dir(config, roi.roi_id, episode)
            mutation_locks.setdefault(output_dir, Lock())
            for batch_idx in _failed_batch_indices(output_dir):
                label = f"{roi.roi_id}/{episode.episode_id}/batch{batch_idx}"
                retry_labels.append(label)
                jobs.append(
                    (
                        label,
                        lambda roi=roi, episode=episode, batch_idx=batch_idx: _retry_failed_batch_job(
                            config=config,
                            roi=roi,
                            episode=episode,
                            batch_idx=batch_idx,
                            deps=deps,
                            mutation_lock=mutation_locks[output_dir],
                        ),
                    ),
                )
    if not jobs:
        _log("No failed scoring batches found.")
        return
    _log("Retry failed batches: " + ", ".join(retry_labels))
    _run_parallel(stage_name="retry-failed-batches", workers=options.scoring_workers, jobs=jobs)
    _log("Retry complete: refresh manifest and encoding")
    _write_manifest(config, rois)
    _run_encoding(config)
    _validate_full_outputs(config, rois)


def _require_paths(paths: Sequence[Path], *, context: str) -> None:
    missing = [path for path in paths if not path.exists()]
    if missing:
        details = "\n".join(str(path) for path in missing)
        raise ValueError(f"{context} is missing expected output(s):\n{details}")


def _validate_scoring_outputs(
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    episodes: Sequence[PilotEpisode],
) -> None:
    paths = []
    for roi in rois:
        for episode in episodes:
            score_dir = _scoring_dir(config, roi.roi_id, episode)
            paths.extend(
                [
                    score_dir / "segment_region_scores.jsonl",
                    score_dir / "tr_features.jsonl",
                    score_dir / "scoring_metadata.json",
                    score_dir / "scoring_progress.json",
                ],
            )
    _require_paths(paths, context="Scoring validation")


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
    _log("Full run: domain pools")
    _run_domain_pool_jobs(config, rois, deps=deps, workers=options.domain_workers)
    _log("Full run: schemas")
    _run_schema_jobs(config, rois, deps=deps, workers=options.schema_workers)
    _log("Full run: scoring")
    _run_scoring_jobs(
        config,
        rois,
        config.episodes,
        deps=deps,
        workers=options.scoring_workers,
        overwrite_scoring=options.overwrite_scoring,
    )
    _log("Full run: manifest")
    _write_manifest(config, rois)
    _log("Full run: encoding")
    _run_encoding(config)
    _validate_full_outputs(config, rois)


def _validate_full_outputs(config: PilotConfig, rois: Sequence[RoiDefinition]) -> None:
    paths: list[Path] = []
    for roi in rois:
        paths.extend(
            [
                _domain_pool_draft_path(config, roi.roi_id),
                _domain_pool_auto_confirmed_path(config, roi.roi_id),
                _region_schema_path(config, roi.roi_id),
            ],
        )
    for episode in config.episodes:
        paths.extend(
            [
                _summary_path(config, episode),
                _summary_path(config, episode).with_name("summary_metadata.json"),
            ],
        )
    paths.extend(
        [
            _manifest_path(config),
            _roi_schema_mapping_path(config),
            _encoding_dir(config) / "group_summary.json",
            _encoding_dir(config) / "encoding_metadata.json",
        ],
    )
    _require_paths(paths, context="Full-run validation")
    _validate_scoring_outputs(config, rois, config.episodes)


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
