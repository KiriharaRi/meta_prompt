"""Run a config-driven concurrent Friends multi-ROI pilot.

This runner is the general 14-ROI path for current Friends experiments. The
episode set is read entirely from the pilot config; this script does not assume
specific seasons, copy artifacts across output roots, or replace the staged
serial ``run-multi-roi-pilot`` CLI.
"""

from __future__ import annotations

import sys
from argparse import ArgumentParser
from collections.abc import Sequence
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
from brain_region_pipeline.core.dependencies import default_dependencies  # noqa: E402
from brain_region_pipeline.pilot.concurrent import ConcurrentPilotStages  # noqa: E402
from brain_region_pipeline.pilot.runner import (  # noqa: E402
    PILOT_STAGES,
    PilotConfig,
    _dry_run,
    _validate_episode_inputs,
    load_pilot_config,
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
    stage: str
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
    parser.add_argument(
        "--stage",
        choices=PILOT_STAGES,
        default="all",
        help="Pipeline stage to run. 'all' runs every stage in order.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--retry-failed-batches",
        action="store_true",
        help=(
            "Retry only batch_generation_failed_zero_filled scoring batches, "
            "then refresh encoding."
        ),
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
    if args.retry_failed_batches and args.stage != "all":
        raise ValueError("--retry-failed-batches cannot be combined with non-all --stage.")
    for flag in ("summary_workers", "domain_workers", "schema_workers", "scoring_workers"):
        if getattr(args, flag) < 1:
            raise ValueError(f"--{flag.replace('_', '-')} must be at least 1.")
    return RunOptions(
        config_path=_resolve_workspace_path(args.config),
        summary_workers=args.summary_workers,
        domain_workers=args.domain_workers,
        schema_workers=args.schema_workers,
        scoring_workers=args.scoring_workers,
        stage=args.stage,
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


def _print_dry_run(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    counts: dict[str, int],
    options: RunOptions,
) -> None:
    """Validate static inputs and print the planned concurrent stage run."""

    _dry_run(config, rois, options.stage)
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
    stages: ConcurrentPilotStages,
) -> None:
    """Run the complete config-driven concurrent workflow."""

    config.output_root.mkdir(parents=True, exist_ok=True)
    _log("Step 1/6: Generate summaries")
    stages.run_summary_jobs(
        workers=options.summary_workers,
        skip_existing=options.skip_existing_summaries,
    )

    _log("Step 2/6: Generate domain pools")
    stages.run_domain_pool_jobs(rois, workers=options.domain_workers)

    _log("Step 3/6: Generate schemas")
    stages.run_schema_jobs(rois, workers=options.schema_workers)

    _log("Step 4/6: Score ROI/episode pairs")
    stages.run_scoring_jobs(
        rois,
        config.episodes,
        workers=options.scoring_workers,
        overwrite_scoring=options.overwrite_scoring,
    )

    _log("Step 5/6: Write manifest and fit encoding")
    stages.refresh_encoding(rois)

    _log("Step 6/6: Validate outputs")
    stages.validate_full_outputs(rois)
    _log("Concurrent pilot run complete.")


def _run_stage(
    *,
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    options: RunOptions,
    stages: ConcurrentPilotStages,
) -> None:
    """Run one configured stage while preserving full-run behavior for ``all``."""

    if options.stage == "all":
        _run_full(config=config, rois=rois, options=options, stages=stages)
    elif options.stage == "summaries":
        config.output_root.mkdir(parents=True, exist_ok=True)
        _log("Stage summaries: Generate summaries")
        stages.run_summary_jobs(
            workers=options.summary_workers,
            skip_existing=options.skip_existing_summaries,
        )
    elif options.stage == "domain-pools":
        config.output_root.mkdir(parents=True, exist_ok=True)
        _log("Stage domain-pools: Generate domain pools")
        stages.run_domain_pool_jobs(rois, workers=options.domain_workers)
    elif options.stage == "schemas":
        config.output_root.mkdir(parents=True, exist_ok=True)
        _log("Stage schemas: Generate schemas")
        stages.run_schema_jobs(rois, workers=options.schema_workers)
    elif options.stage == "scoring":
        config.output_root.mkdir(parents=True, exist_ok=True)
        _log("Stage scoring: Score ROI/episode pairs")
        stages.run_scoring_jobs(
            rois,
            config.episodes,
            workers=options.scoring_workers,
            overwrite_scoring=options.overwrite_scoring,
        )
    elif options.stage == "manifest":
        config.output_root.mkdir(parents=True, exist_ok=True)
        _log("Stage manifest: Write manifest")
        stages.write_manifest(rois)
    elif options.stage == "encoding":
        config.output_root.mkdir(parents=True, exist_ok=True)
        _log("Stage encoding: Fit encoding")
        stages.run_encoding()
    else:
        raise ValueError(f"Unsupported pilot stage: {options.stage!r}")


def main(argv: Sequence[str] | None = None) -> None:
    """Run dry-run, full, or failed-batch retry modes."""

    options = parse_args(argv)
    config, rois, counts = _load_run_inputs(options.config_path)
    if options.dry_run:
        _print_dry_run(config=config, rois=rois, counts=counts, options=options)
        return
    deps = default_dependencies()
    stages = ConcurrentPilotStages(config=config, deps=deps, log=_log)
    if options.retry_failed_batches:
        stages.retry_failed_batches(rois, workers=options.scoring_workers)
        return
    _run_stage(config=config, rois=rois, options=options, stages=stages)


if __name__ == "__main__":
    main()
