"""CLI for the brain-region prompt scoring pipeline."""

from __future__ import annotations

import argparse

from .core.config import (
    DEFAULT_ENCODING_LAGS,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_GENERATION_PROVIDER,
    DEFAULT_RIDGE_ALPHAS,
    DomainPoolConfig,
    GENERATION_PROVIDERS,
    RegionSchemaConfig,
    RidgeEncodingConfig,
    ScoreDescriptionsConfig,
    SummaryDescriptionsConfig,
)
from .core.dependencies import PipelineDependencies
from .encoding.runner import fit_roi_encoding_from_manifest
from .pilot.runner import PILOT_STAGES, run_multi_roi_pilot
from .schema_design.runner import (
    make_domain_pool,
    make_region_schema,
)
from .scoring.correlation import write_score_correlations
from .scoring.runner import (
    score_descriptions_from_file,
)
from .scoring.summary_generator import summarize_descriptions_from_file


def _add_generation_args(parser: argparse.ArgumentParser) -> None:
    """Add shared LLM provider/model flags to generation-backed commands."""

    parser.add_argument(
        "--provider",
        default=DEFAULT_GENERATION_PROVIDER,
        choices=GENERATION_PROVIDERS,
        help="LLM generation provider.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_GENERATION_MODEL,
        help="LLM generation model.",
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser."""

    parser = argparse.ArgumentParser(description="Brain-region prompt scoring pipeline")
    subparsers = parser.add_subparsers(dest="command")

    domain_pool_parser = subparsers.add_parser(
        "make-domain-pool",
        help="Generate a draft target-region coarse-domain pool from atlas labels.",
    )
    domain_pool_parser.add_argument("--atlas-labels", required=True, help="Atlas label table matching H5 parcel columns.")
    domain_pool_parser.add_argument("--target-region", default="vmPFC", help="Target region name.")
    domain_pool_parser.add_argument("--output-file", required=True, help="Output domain-pool JSON path.")
    _add_generation_args(domain_pool_parser)
    domain_pool_parser.add_argument(
        "--proposal-runs",
        type=int,
        default=5,
        help="Number of independent coarse-domain proposal runs before consolidation.",
    )

    schema_parser = subparsers.add_parser(
        "make-region-schema",
        help="Generate a region feature schema from atlas labels and a confirmed domain pool.",
    )
    schema_parser.add_argument("--atlas-labels", required=True, help="Atlas label table matching H5 parcel columns.")
    schema_parser.add_argument("--target-region", default="vmPFC", help="Target region name.")
    schema_parser.add_argument("--output-file", required=True, help="Output region schema JSON path.")
    _add_generation_args(schema_parser)
    schema_parser.add_argument(
        "--domain-pool",
        required=True,
        help="Confirmed coarse-domain pool JSON used to guide region schema generation.",
    )
    schema_parser.add_argument(
        "--roi-definitions",
        default=None,
        help="Optional ROI definition JSON used to apply fixed atlas selection rules.",
    )
    schema_parser.add_argument(
        "--roi-id",
        default=None,
        help="ROI id to load from --roi-definitions; must match --target-region.",
    )

    score_parser = subparsers.add_parser(
        "score-descriptions",
        help="Score existing dense descriptions with a region schema.",
    )
    score_parser.add_argument("--descriptions", required=True, help="Timestamped dense description text file.")
    score_parser.add_argument("--region-schema", required=True, help="Region schema JSON path.")
    score_parser.add_argument("--output-dir", required=True, help="Output directory for scored features.")
    _add_generation_args(score_parser)
    score_parser.add_argument("--tr-s", type=float, default=1.49, help="TR in seconds.")
    score_parser.add_argument("--total-trs", type=int, default=None, help="Override total TR count.")
    score_parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a matching interrupted scoring run from committed segment scores.",
    )
    score_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Remove existing score-descriptions outputs in --output-dir before rerunning.",
    )
    score_parser.add_argument(
        "--summary-file",
        default=None,
        help="Optional notebook-style summary.json used as Story Context for batch scoring.",
    )
    score_parser.add_argument(
        "--scoring-batch-size",
        type=int,
        default=40,
        help="Number of target description segments scored per LLM request.",
    )
    score_parser.add_argument(
        "--local-buffer-size",
        type=int,
        default=10,
        help="Number of prior segments included as Local Buffer context per batch.",
    )
    score_parser.add_argument(
        "--gt-dir",
        default=None,
        help="Optional directory containing notebook-style GT CSV files to average onto segments.",
    )
    score_parser.add_argument(
        "--gt-file-pattern",
        default="*.csv",
        help="Glob pattern for GT CSV files under --gt-dir.",
    )
    score_parser.add_argument(
        "--gt-time-column",
        default="视频时间(s)",
        help="Time column name in GT CSV files.",
    )
    score_parser.add_argument(
        "--gt-emotion-column",
        default="情绪值",
        help="Emotion value column name in GT CSV files.",
    )
    score_parser.add_argument(
        "--alignment",
        default="overlap_weighted",
        choices=["overlap_weighted", "repeat"],
        help="TR alignment strategy.",
    )

    summary_parser = subparsers.add_parser(
        "summarize-descriptions",
        help="Generate notebook-style rolling narrative summaries for dense descriptions.",
    )
    summary_parser.add_argument("--descriptions", required=True, help="Timestamped dense description text file.")
    summary_parser.add_argument("--output-file", required=True, help="Output summary JSON array path.")
    _add_generation_args(summary_parser)

    correlate_parser = subparsers.add_parser(
        "correlate-scores",
        help="Compute per-dimension Pearson correlations between segment scores and GT.",
    )
    correlate_parser.add_argument("--scores-jsonl", required=True, help="Segment score JSON/JSONL path.")
    correlate_parser.add_argument("--gt-jsonl", required=True, help="Segment GT mean JSON/JSONL path.")
    correlate_parser.add_argument(
        "--target-emotion",
        default="agitation",
        help="GT emotion key under each row's gt_emotions object.",
    )
    correlate_parser.add_argument(
        "--lag-s",
        type=float,
        default=0.0,
        help="Lag in seconds. Positive values compare feature time t with GT at t + lag.",
    )
    correlate_parser.add_argument("--output-file", required=True, help="Output Pearson JSON path.")

    encoding_parser = subparsers.add_parser(
        "fit-roi-encoding",
        help="Fit one Ridge model from one or more ROI score feature sets to H5 fMRI targets.",
    )
    encoding_parser.add_argument("--manifest", required=True, help="Unified ROI JSONL encoding manifest.")
    encoding_parser.add_argument(
        "--roi-schemas",
        required=True,
        help="JSON object mapping ROI ids to region schema files.",
    )
    encoding_parser.add_argument("--atlas-labels", required=True, help="Atlas label table matching H5 parcel columns.")
    encoding_parser.add_argument("--output-dir", required=True, help="Output directory for encoding results.")
    encoding_parser.add_argument(
        "--lags",
        default=",".join(str(lag) for lag in DEFAULT_ENCODING_LAGS),
        help="Comma-separated feature lags in TRs.",
    )
    encoding_parser.add_argument(
        "--alphas",
        default=",".join(f"{alpha:g}" for alpha in DEFAULT_RIDGE_ALPHAS),
        help="Comma-separated Ridge alpha grid.",
    )

    pilot_parser = subparsers.add_parser(
        "run-multi-roi-pilot",
        help="Run staged Friends multi-ROI domain/scoring/encoding workflow from config.",
    )
    pilot_parser.add_argument("--config", required=True, help="Pilot run config JSON.")
    pilot_parser.add_argument(
        "--stage",
        choices=PILOT_STAGES,
        default="all",
        help="Pipeline stage to run. 'all' runs every stage in order.",
    )
    pilot_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the planned run without calling the configured LLM or writing outputs.",
    )
    pilot_parser.add_argument(
        "--no-auto-confirm-domain-pools",
        action="store_true",
        help="For --stage all, stop using auto-confirmed domain-pool copies.",
    )
    pilot_parser.add_argument(
        "--resume-scoring",
        action="store_true",
        help="Resume score-descriptions jobs during the scoring stage.",
    )
    pilot_parser.add_argument(
        "--overwrite-scoring",
        action="store_true",
        help="Overwrite score-descriptions outputs during the scoring stage.",
    )

    return parser


def _build_domain_pool_config(args: argparse.Namespace) -> DomainPoolConfig:
    """Build domain-pool generation configuration from CLI args."""

    return DomainPoolConfig(
        generation_provider=args.provider,
        generation_model=args.model,
        target_region=args.target_region,
        proposal_runs=args.proposal_runs,
    )


def _build_region_schema_config(args: argparse.Namespace) -> RegionSchemaConfig:
    """Build region schema generation configuration from CLI args."""

    return RegionSchemaConfig(
        generation_provider=args.provider,
        generation_model=args.model,
        target_region=args.target_region,
    )


def _build_score_config(args: argparse.Namespace) -> ScoreDescriptionsConfig:
    """Build description scoring configuration from CLI args."""

    if args.resume and args.overwrite:
        raise ValueError("--resume and --overwrite cannot be used together.")
    if args.scoring_batch_size < 1:
        raise ValueError("--scoring-batch-size must be at least 1.")
    if args.local_buffer_size < 0:
        raise ValueError("--local-buffer-size must be non-negative.")
    return ScoreDescriptionsConfig(
        generation_provider=args.provider,
        generation_model=args.model,
        tr_s=args.tr_s,
        alignment_strategy=args.alignment,
        scoring_batch_size=args.scoring_batch_size,
        local_buffer_size=args.local_buffer_size,
    )


def _build_summary_config(args: argparse.Namespace) -> SummaryDescriptionsConfig:
    """Build rolling-summary generation configuration from CLI args."""

    return SummaryDescriptionsConfig(
        generation_provider=args.provider,
        generation_model=args.model,
    )


def _parse_int_list(raw_value: str, flag: str) -> tuple[int, ...]:
    """Parse a comma-separated integer CLI list."""

    try:
        values = tuple(int(item.strip()) for item in raw_value.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError(f"{flag} must be a comma-separated integer list.") from exc
    if not values:
        raise ValueError(f"{flag} must include at least one value.")
    if any(value < 0 for value in values):
        raise ValueError(f"{flag} cannot contain negative values.")
    return values


def _parse_float_list(raw_value: str, flag: str) -> tuple[float, ...]:
    """Parse a comma-separated float CLI list."""

    try:
        values = tuple(float(item.strip()) for item in raw_value.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError(f"{flag} must be a comma-separated numeric list.") from exc
    if not values:
        raise ValueError(f"{flag} must include at least one value.")
    if any(value <= 0 for value in values):
        raise ValueError(f"{flag} values must be positive.")
    return values


def _build_ridge_encoding_config(args: argparse.Namespace) -> RidgeEncodingConfig:
    """Build Ridge encoding configuration from CLI args."""

    return RidgeEncodingConfig(
        lags=_parse_int_list(args.lags, "--lags"),
        alphas=_parse_float_list(args.alphas, "--alphas"),
    )


def main(
    argv: list[str] | None = None,
    deps: PipelineDependencies | None = None,
) -> None:
    """CLI entrypoint for the brain-region prompt pipeline."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return
    if args.command == "make-domain-pool":
        make_domain_pool(args, _build_domain_pool_config(args), deps=deps)
        return
    if args.command == "make-region-schema":
        make_region_schema(args, _build_region_schema_config(args), deps=deps)
        return
    if args.command == "score-descriptions":
        score_descriptions_from_file(args, _build_score_config(args), deps=deps)
        return
    if args.command == "summarize-descriptions":
        summarize_descriptions_from_file(args, _build_summary_config(args))
        return
    if args.command == "correlate-scores":
        write_score_correlations(
            scores_path=args.scores_jsonl,
            gt_path=args.gt_jsonl,
            target_emotion=args.target_emotion,
            lag_s=args.lag_s,
            output_file=args.output_file,
        )
        return
    if args.command == "fit-roi-encoding":
        fit_roi_encoding_from_manifest(args, _build_ridge_encoding_config(args))
        return
    if args.command == "run-multi-roi-pilot":
        if args.resume_scoring and args.overwrite_scoring:
            raise ValueError("--resume-scoring and --overwrite-scoring cannot be used together.")
        run_multi_roi_pilot(args, deps=deps)
        return
    raise ValueError(f"Unknown command: {args.command!r}")
