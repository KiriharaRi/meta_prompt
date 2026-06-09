"""Run the one-off Friends 14-ROI s01/s02 Vertex Gemini encoding expansion.

This script is intentionally scoped to one research run. It creates a new
self-contained output root by copying validated s01 artifacts from the previous
14-ROI pilot, generating summaries for the new s02 episodes, scoring only the
new s02 ROI/episode pairs, and fitting the expanded encoding model.
"""

from __future__ import annotations

import os
import shutil
import sys
from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from brain_region_pipeline.core.io_utils import (  # noqa: E402
    file_sha256,
    read_json,
    write_json,
)
from brain_region_pipeline.pilot.runner import (  # noqa: E402
    PilotConfig,
    PilotEpisode,
    _domain_pool_auto_confirmed_path,
    _domain_pool_draft_path,
    _encoding_dir,
    _manifest_path,
    _region_schema_path,
    _roi_schema_mapping_path,
    _run_encoding,
    _scoring_dir,
    _summary_path,
    _validate_episode_inputs,
    _write_manifest,
    load_pilot_config,
)
from brain_region_pipeline.scoring.description_io import load_description_segments  # noqa: E402
from brain_region_pipeline.scoring.summary_generator import (  # noqa: E402
    summarize_descriptions_from_file,
)
from run_friends_7roi_vertex_pilot import (  # noqa: E402
    _retry_failed_batches,
    _run_parallel,
    _run_scoring_job,
    _validate_full_outputs,
    _validate_vertex_env,
)

DEFAULT_CONFIG = (
    REPO_ROOT / "configs" / "friends_14roi_s01s02_vertex_gemini35_pilot_20260607.json"
)
DEFAULT_SOURCE_OUTPUT_ROOT = (
    REPO_ROOT / "friends" / "demo" / "multi_roi_pilot_vertex_gemini35_7roi_20260605"
)
DEFAULT_SUMMARY_WORKERS = 1
DEFAULT_SCORING_WORKERS = 4
S02_EPISODES = {"s02e01a", "s02e02a", "s02e03a", "s02e04a", "s02e05a"}


@dataclass(frozen=True)
class RunOptions:
    """Runtime options for the s01/s02 expansion run."""

    config_path: Path
    source_output_root: Path
    summary_workers: int
    scoring_workers: int
    dry_run: bool
    retry_failed_batches: bool
    skip_existing: bool


@dataclass(frozen=True)
class RetryOptions:
    """Minimal adapter for the shared failed-batch retry helper."""

    scoring_workers: int


def _log(message: str) -> None:
    print(f"[friends_s01s02_vertex_pilot] {message}", flush=True)


def _resolve_workspace_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def parse_args(argv: Sequence[str] | None = None) -> RunOptions:
    """Parse one-off run options."""

    parser = ArgumentParser(description="Run the Friends 14-ROI s01/s02 Vertex pilot.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Expanded pilot config JSON.")
    parser.add_argument(
        "--source-output-root",
        default=str(DEFAULT_SOURCE_OUTPUT_ROOT),
        help="Previous validated output root to reuse for s01 artifacts.",
    )
    parser.add_argument("--summary-workers", type=int, default=DEFAULT_SUMMARY_WORKERS)
    parser.add_argument("--scoring-workers", type=int, default=DEFAULT_SCORING_WORKERS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--retry-failed-batches",
        action="store_true",
        help="Retry only batch_generation_failed_zero_filled scoring batches.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip already complete generated summaries instead of refusing to continue.",
    )
    args = parser.parse_args(argv)
    for flag in ("summary_workers", "scoring_workers"):
        if getattr(args, flag) < 1:
            raise ValueError(f"--{flag.replace('_', '-')} must be at least 1.")
    return RunOptions(
        config_path=_resolve_workspace_path(args.config),
        source_output_root=_resolve_workspace_path(args.source_output_root),
        summary_workers=args.summary_workers,
        scoring_workers=args.scoring_workers,
        dry_run=args.dry_run,
        retry_failed_batches=args.retry_failed_batches,
        skip_existing=args.skip_existing,
    )


def _load_run_inputs(config_path: Path) -> tuple[PilotConfig, list[RoiDefinition], dict[str, int]]:
    """Load config and validate static ROI, atlas, description, and H5 inputs."""

    config = load_pilot_config(config_path)
    roi_definitions = load_roi_definitions(config.roi_definitions)
    rois = list(select_roi_definitions(roi_definitions, config.rois))
    counts = validate_roi_definitions_against_atlas(rois, config.atlas_labels)
    _validate_episode_inputs(config)
    return config, rois, counts


def _s01_episodes(config: PilotConfig) -> list[PilotEpisode]:
    return [episode for episode in config.episodes if episode.episode_id.startswith("s01")]


def _s02_episodes(config: PilotConfig) -> list[PilotEpisode]:
    return [episode for episode in config.episodes if episode.episode_id in S02_EPISODES]


def _relative_output_path(config: PilotConfig, path: Path) -> str:
    return os.path.relpath(path, config.output_root)


def _copied_record(
    *,
    config: PilotConfig,
    kind: str,
    source: Path,
    destination: Path,
    status: str,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "source": str(source),
        "destination": _relative_output_path(config, destination),
        "status": status,
        "sha256": file_sha256(destination),
    }


def _copy_file_checked(
    *,
    config: PilotConfig,
    source: Path,
    destination: Path,
    kind: str,
    copied: list[dict[str, Any]],
) -> None:
    """Copy one artifact, refusing to overwrite a different existing file."""

    if not source.exists():
        raise FileNotFoundError(f"Missing reusable source artifact: {source}")
    if destination.exists():
        if file_sha256(source) != file_sha256(destination):
            raise ValueError(
                "Refusing to overwrite a different artifact in the new output root: "
                f"{destination}",
            )
        copied.append(
            _copied_record(
                config=config,
                kind=kind,
                source=source,
                destination=destination,
                status="already_present",
            ),
        )
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    copied.append(
        _copied_record(
            config=config,
            kind=kind,
            source=source,
            destination=destination,
            status="copied",
        ),
    )


def _copy_tree_checked(
    *,
    config: PilotConfig,
    source_dir: Path,
    destination_dir: Path,
    kind: str,
    copied: list[dict[str, Any]],
) -> None:
    """Copy a reusable artifact directory file-by-file with hash checks."""

    if not source_dir.exists():
        raise FileNotFoundError(f"Missing reusable source directory: {source_dir}")
    source_files = sorted(path for path in source_dir.rglob("*") if path.is_file())
    if not source_files:
        raise ValueError(f"Reusable source directory has no files: {source_dir}")
    for source in source_files:
        destination = destination_dir / source.relative_to(source_dir)
        _copy_file_checked(
            config=config,
            source=source,
            destination=destination,
            kind=kind,
            copied=copied,
        )


def _reuse_source_config(config: PilotConfig, source_output_root: Path) -> PilotConfig:
    """Return a config view rooted at the previous validated output directory."""

    if source_output_root.resolve() == config.output_root.resolve():
        raise ValueError("source_output_root and output_root must be different for this expansion run.")
    return replace(config, output_root=source_output_root)


def _required_reuse_files(
    *,
    source_config: PilotConfig,
    rois: Sequence[RoiDefinition],
    episodes: Sequence[PilotEpisode],
) -> list[Path]:
    """List required source artifacts before copying from the previous run."""

    paths: list[Path] = []
    for episode in episodes:
        summary = _summary_path(source_config, episode)
        paths.extend([summary, summary.with_name("summary_metadata.json")])
    for roi in rois:
        paths.extend(
            [
                _domain_pool_draft_path(source_config, roi.roi_id),
                _domain_pool_auto_confirmed_path(source_config, roi.roi_id),
                _region_schema_path(source_config, roi.roi_id),
            ],
        )
        for episode in episodes:
            score_dir = _scoring_dir(source_config, roi.roi_id, episode)
            paths.extend(
                [
                    score_dir / "segment_region_scores.jsonl",
                    score_dir / "tr_features.jsonl",
                    score_dir / "tr_descriptions_readable.jsonl",
                    score_dir / "scoring_metadata.json",
                    score_dir / "scoring_progress.json",
                ],
            )
    return paths


def _validate_reuse_sources(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    source_output_root: Path,
) -> None:
    source_config = _reuse_source_config(config, source_output_root)
    missing = [
        path
        for path in _required_reuse_files(
            source_config=source_config,
            rois=rois,
            episodes=_s01_episodes(config),
        )
        if not path.exists()
    ]
    if missing:
        details = "\n".join(str(path) for path in missing)
        raise ValueError(f"Previous output root is missing reusable artifact(s):\n{details}")


def copy_reused_artifacts(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    source_output_root: Path,
) -> list[dict[str, Any]]:
    """Copy all validated s01 artifacts needed for a self-contained new run."""

    source_config = _reuse_source_config(config, source_output_root)
    _validate_reuse_sources(config=config, rois=rois, source_output_root=source_output_root)
    copied: list[dict[str, Any]] = []
    for episode in _s01_episodes(config):
        source_summary = _summary_path(source_config, episode)
        destination_summary = _summary_path(config, episode)
        _copy_file_checked(
            config=config,
            source=source_summary,
            destination=destination_summary,
            kind="s01_summary",
            copied=copied,
        )
        _copy_file_checked(
            config=config,
            source=source_summary.with_name("summary_metadata.json"),
            destination=destination_summary.with_name("summary_metadata.json"),
            kind="s01_summary_metadata",
            copied=copied,
        )
    for roi in rois:
        for source, destination, kind in (
            (
                _domain_pool_draft_path(source_config, roi.roi_id),
                _domain_pool_draft_path(config, roi.roi_id),
                "roi_domain_pool_draft",
            ),
            (
                _domain_pool_auto_confirmed_path(source_config, roi.roi_id),
                _domain_pool_auto_confirmed_path(config, roi.roi_id),
                "roi_domain_pool_auto_confirmed",
            ),
            (
                _region_schema_path(source_config, roi.roi_id),
                _region_schema_path(config, roi.roi_id),
                "roi_region_schema",
            ),
        ):
            _copy_file_checked(
                config=config,
                source=source,
                destination=destination,
                kind=kind,
                copied=copied,
            )
        for episode in _s01_episodes(config):
            _copy_tree_checked(
                config=config,
                source_dir=_scoring_dir(source_config, roi.roi_id, episode),
                destination_dir=_scoring_dir(config, roi.roi_id, episode),
                kind="s01_scoring_output",
                copied=copied,
            )
    return copied


def _summary_exists(config: PilotConfig, episode: PilotEpisode) -> bool:
    summary = _summary_path(config, episode)
    return summary.exists() and summary.with_name("summary_metadata.json").exists()


def _run_summary_job(
    *,
    config: PilotConfig,
    episode: PilotEpisode,
    skip_existing: bool,
) -> None:
    """Generate one s02 rolling summary unless an existing complete one is allowed."""

    summary = _summary_path(config, episode)
    metadata = summary.with_name("summary_metadata.json")
    if summary.exists() or metadata.exists():
        if skip_existing and summary.exists() and metadata.exists():
            _log(f"Summary already complete: {episode.episode_id}")
            return
        raise ValueError(
            f"Summary output already exists for {episode.episode_id}; "
            "pass --skip-existing to reuse complete summary outputs.",
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
    episodes: Sequence[PilotEpisode],
    workers: int,
    skip_existing: bool,
) -> None:
    _run_parallel(
        stage_name="summaries-s02",
        workers=workers,
        jobs=[
            (
                episode.episode_id,
                lambda episode=episode: _run_summary_job(
                    config=config,
                    episode=episode,
                    skip_existing=skip_existing,
                ),
            )
            for episode in episodes
            if not (skip_existing and _summary_exists(config, episode))
        ],
    )


def _run_s02_scoring_jobs(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    episodes: Sequence[PilotEpisode],
    deps: PipelineDependencies,
    workers: int,
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
                        overwrite_scoring=False,
                    ),
                ),
            )
    _run_parallel(stage_name="scoring-s02", workers=workers, jobs=jobs)


def _artifact_output_record(config: PilotConfig, path: Path) -> dict[str, Any]:
    return {
        "path": _relative_output_path(config, path),
        "sha256": file_sha256(path),
    }


def _collect_generated_summaries(
    config: PilotConfig,
    episodes: Sequence[PilotEpisode],
) -> list[dict[str, Any]]:
    records = []
    for episode in episodes:
        summary = _summary_path(config, episode)
        rows = read_json(summary)
        records.append(
            {
                "episode_id": episode.episode_id,
                "summary": _artifact_output_record(config, summary),
                "metadata": _artifact_output_record(config, summary.with_name("summary_metadata.json")),
                "n_batches": len(rows),
            },
        )
    return records


def _collect_generated_scores(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    episodes: Sequence[PilotEpisode],
) -> list[dict[str, Any]]:
    records = []
    for roi in rois:
        for episode in episodes:
            score_dir = _scoring_dir(config, roi.roi_id, episode)
            files = [
                path
                for path in sorted(score_dir.rglob("*"))
                if path.is_file() and path.name != "scoring_warnings.jsonl"
            ]
            records.append(
                {
                    "roi_id": roi.roi_id,
                    "episode_id": episode.episode_id,
                    "output_dir": _relative_output_path(config, score_dir),
                    "files": [_artifact_output_record(config, path) for path in files],
                },
            )
    return records


def _collect_warning_metadata(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
) -> list[dict[str, Any]]:
    warnings = []
    for roi in rois:
        for episode in config.episodes:
            metadata_path = _scoring_dir(config, roi.roi_id, episode) / "scoring_metadata.json"
            if not metadata_path.exists():
                continue
            warning_summary = read_json(metadata_path).get("scoring_warnings", {})
            if (
                warning_summary.get("warning_count", 0)
                or warning_summary.get("zero_filled_segments", 0)
                or warning_summary.get("reason_counts")
            ):
                warnings.append(
                    {
                        "roi_id": roi.roi_id,
                        "episode_id": episode.episode_id,
                        "scoring_warnings": warning_summary,
                    },
                )
    return warnings


def write_reuse_manifest(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    source_output_root: Path,
    copied_artifacts: Sequence[dict[str, Any]],
) -> None:
    """Write provenance for copied s01 artifacts and newly generated s02 artifacts."""

    s02_episodes = _s02_episodes(config)
    write_json(
        config.output_root / "reuse_manifest.json",
        {
            "command": "run_friends_14roi_s01s02_vertex_pilot",
            "generated_at": datetime.now(UTC).isoformat(),
            "config": str(config.config_path),
            "source_output_root": str(source_output_root),
            "output_root": str(config.output_root),
            "generation_provider": config.generation_provider,
            "generation_model": config.generation_model,
            "roi_ids": [roi.roi_id for roi in rois],
            "splits": {
                split: [episode.episode_id for episode in config.episodes if episode.split == split]
                for split in ("train", "val", "test")
            },
            "copied_artifacts": list(copied_artifacts),
            "generated_summaries": _collect_generated_summaries(config, s02_episodes),
            "generated_scores": _collect_generated_scores(
                config=config,
                rois=rois,
                episodes=s02_episodes,
            ),
            "encoding_outputs": {
                "manifest": _relative_output_path(config, _manifest_path(config)),
                "roi_schemas": _relative_output_path(config, _roi_schema_mapping_path(config)),
                "group_summary": _relative_output_path(
                    config,
                    _encoding_dir(config) / "group_summary.json",
                ),
                "metadata": _relative_output_path(
                    config,
                    _encoding_dir(config) / "encoding_metadata.json",
                ),
            },
            "residual_scoring_warnings": _collect_warning_metadata(config=config, rois=rois),
        },
    )


def refresh_reuse_manifest_after_retry(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
) -> None:
    """Refresh retry-sensitive reuse manifest fields after failed-batch recovery."""

    manifest_path = config.output_root / "reuse_manifest.json"
    if not manifest_path.exists():
        _log("Reuse manifest not found; skip retry refresh.")
        return

    manifest = read_json(manifest_path)
    s02_episodes = _s02_episodes(config)
    manifest["last_retry_refresh_at"] = datetime.now(UTC).isoformat()
    # Failed-batch retry mutates score rows, TR features, metadata, and encoding
    # outputs. Refresh only the derived fields while preserving the original
    # copied_artifacts provenance from the full run.
    manifest["generated_scores"] = _collect_generated_scores(
        config=config,
        rois=rois,
        episodes=s02_episodes,
    )
    manifest["encoding_outputs"] = {
        "manifest": _relative_output_path(config, _manifest_path(config)),
        "roi_schemas": _relative_output_path(config, _roi_schema_mapping_path(config)),
        "group_summary": _relative_output_path(
            config,
            _encoding_dir(config) / "group_summary.json",
        ),
        "metadata": _relative_output_path(
            config,
            _encoding_dir(config) / "encoding_metadata.json",
        ),
    }
    manifest["residual_scoring_warnings"] = _collect_warning_metadata(config=config, rois=rois)
    write_json(manifest_path, manifest)


def _print_dry_run(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    counts: dict[str, int],
    options: RunOptions,
) -> None:
    """Validate static inputs and print the planned expanded run."""

    _validate_reuse_sources(
        config=config,
        rois=rois,
        source_output_root=options.source_output_root,
    )
    _log("Dry-run s01/s02 expansion plan")
    _log(f"  Config: {config.config_path}")
    _log(f"  Source output root: {options.source_output_root}")
    _log(f"  New output root: {config.output_root}")
    _log(f"  Generation: {config.generation_provider} / {config.generation_model}")
    _log(f"  ROI count: {len(rois)} -> {', '.join(roi.roi_id for roi in rois)}")
    _log("  Parcel counts: " + ", ".join(f"{roi_id}={count}" for roi_id, count in counts.items()))
    for split in ("train", "val", "test"):
        ids = [episode.episode_id for episode in config.episodes if episode.split == split]
        _log(f"  {split}: {', '.join(ids)}")
    for episode in _s02_episodes(config):
        segments = load_description_segments(episode.descriptions)
        _log(
            f"  s02 summary plan: {episode.episode_id} "
            f"segments={len(segments)} batches={(len(segments) + 39) // 40}",
        )
    _log(f"  s02 scoring jobs: {len(rois) * len(_s02_episodes(config))}")
    _log(
        "  workers: "
        f"summary={options.summary_workers}, scoring={options.scoring_workers}",
    )


def _run_full(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    options: RunOptions,
    deps: PipelineDependencies,
) -> None:
    _log("Step 1/6: Copy validated s01 artifacts")
    copied_artifacts = copy_reused_artifacts(
        config=config,
        rois=rois,
        source_output_root=options.source_output_root,
    )
    _log(f"  Copied or verified {len(copied_artifacts)} reusable artifact file(s)")

    _log("Step 2/6: Generate s02 summaries")
    _run_summary_jobs(
        config=config,
        episodes=_s02_episodes(config),
        workers=options.summary_workers,
        skip_existing=options.skip_existing,
    )

    _log("Step 3/6: Score s02 ROI/episode pairs")
    _run_s02_scoring_jobs(
        config=config,
        rois=rois,
        episodes=_s02_episodes(config),
        deps=deps,
        workers=options.scoring_workers,
    )

    _log("Step 4/6: Write expanded manifest")
    _write_manifest(config, rois)

    _log("Step 5/6: Fit expanded encoding")
    _run_encoding(config)

    _log("Step 6/6: Validate outputs and write reuse manifest")
    _validate_full_outputs(config, rois)
    write_reuse_manifest(
        config=config,
        rois=rois,
        source_output_root=options.source_output_root,
        copied_artifacts=copied_artifacts,
    )
    warnings = _collect_warning_metadata(config=config, rois=rois)
    if warnings:
        _log(f"Expanded run complete with residual scoring warning group(s): {len(warnings)}")
    else:
        _log("Expanded run complete with zero residual scoring warnings.")


def main(argv: Sequence[str] | None = None) -> None:
    """Run dry-run, full, or failed-batch retry modes."""

    options = parse_args(argv)
    config, rois, counts = _load_run_inputs(options.config_path)
    if options.dry_run:
        _print_dry_run(config=config, rois=rois, counts=counts, options=options)
        return
    _validate_vertex_env(config)
    deps = default_dependencies()
    if options.retry_failed_batches:
        _retry_failed_batches(
            config=config,
            rois=rois,
            options=RetryOptions(scoring_workers=options.scoring_workers),
            deps=deps,
        )
        refresh_reuse_manifest_after_retry(config=config, rois=rois)
        warnings = _collect_warning_metadata(config=config, rois=rois)
        if warnings:
            _log(f"Retry complete with residual scoring warning group(s): {len(warnings)}")
        else:
            _log("Retry complete with zero residual scoring warnings.")
        return
    _run_full(config=config, rois=rois, options=options, deps=deps)


if __name__ == "__main__":
    main()
