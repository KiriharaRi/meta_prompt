"""Stage runner for description scoring."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.config import ScoreDescriptionsConfig
from ..core.dependencies import PipelineDependencies, default_dependencies
from ..core.io_utils import append_jsonl, write_json, write_jsonl
from ..schema_design.region_schema import load_region_schema
from ..schema_design.schema_models import RegionFeatureSchema
from .checkpoint import (
    build_progress_payload,
    build_scoring_run_signature,
    build_scoring_source_paths,
    ensure_output_policy,
    load_scoring_checkpoint,
    scoring_output_paths,
    write_progress,
)
from .description_io import load_description_segments
from .gt_aligner import average_gt_to_segments, load_averaged_gt_csvs
from .models import DescriptionSegment, SegmentRegionScore
from .score_aligner import align_scores_to_trs
from .tr_output import save_readable_tr_rows


def _log(message: str) -> None:
    print(f"[brain_region_pipeline] {message}", flush=True)


def _infer_score_total_trs(
    scores: list[SegmentRegionScore],
    cfg: ScoreDescriptionsConfig,
    total_trs: int | None,
) -> int:
    """Infer TR count from scored segment end times when no override is given."""

    if total_trs is not None:
        return total_trs
    if not scores:
        return 0
    return int(math.ceil(max(score.end_s for score in scores) / cfg.tr_s))


def _load_scoring_summaries(path: str | None) -> list[dict[str, Any]] | None:
    """Load notebook-style batch summaries for Story Context."""

    if not path:
        return None
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("Scoring summary file must contain a JSON array.")
    return [dict(item) for item in data]


def _scoring_warning_summary(warnings: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize batch scoring warnings for metadata."""

    reason_counts: dict[str, int] = {}
    failed_batches: set[int] = set()
    zero_filled_segments = 0
    for warning in warnings:
        reason = str(warning.get("reason", "unknown"))
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        batch_idx = warning.get("batch_idx")
        if reason == "batch_generation_failed_zero_filled" and batch_idx is not None:
            failed_batches.add(int(batch_idx))
        zero_filled_segments += int(warning.get("zero_filled_segments", 0))
        if reason == "missing_segment_zero_filled":
            zero_filled_segments += 1
    return {
        "warning_count": len(warnings),
        "reason_counts": reason_counts,
        "failed_batches": sorted(failed_batches),
        "zero_filled_segments": zero_filled_segments,
    }


def _write_checkpoint_progress(
    *,
    output_dir: Path,
    status: str,
    total_segments: int,
    completed_segments: int,
    cfg: ScoreDescriptionsConfig,
    run_signature: dict[str, Any],
    source_paths: dict[str, str | None],
    scoring_warnings: list[dict[str, Any]],
) -> None:
    """Persist score-descriptions progress after each committed batch."""

    paths = scoring_output_paths(output_dir)
    write_progress(
        paths["progress"],
        build_progress_payload(
            status=status,
            total_segments=total_segments,
            completed_segments=completed_segments,
            cfg=cfg,
            run_signature=run_signature,
            source_paths=source_paths,
            warning_summary=_scoring_warning_summary(scoring_warnings),
        ),
    )


def _normalize_batch_score_metadata(
    *,
    batch_scores: list[SegmentRegionScore],
    batch_start: int,
    batch_idx: int,
    total_segments: int,
    cfg: ScoreDescriptionsConfig,
) -> list[SegmentRegionScore]:
    """Ensure dependency-provided score rows carry stable resume metadata."""

    expected_count = min(batch_start + cfg.scoring_batch_size, total_segments) - batch_start
    if len(batch_scores) != expected_count:
        raise ValueError(
            "Score batch returned an unexpected number of rows: "
            f"{len(batch_scores)} != {expected_count}",
        )
    rows: list[SegmentRegionScore] = []
    for offset, score in enumerate(batch_scores):
        expected_segment_id = batch_start + offset
        if score.segment_id is not None and score.segment_id != expected_segment_id:
            raise ValueError("Score batch returned inconsistent segment_id metadata.")
        if score.batch_idx is not None and score.batch_idx != batch_idx:
            raise ValueError("Score batch returned inconsistent batch_idx metadata.")
        rows.append(
            replace(
                score,
                segment_id=expected_segment_id,
                batch_idx=batch_idx,
            ),
        )
    return rows


def _score_segments_with_checkpoints(
    *,
    output_dir: Path,
    segments: list[DescriptionSegment],
    schema: RegionFeatureSchema,
    cfg: ScoreDescriptionsConfig,
    summaries: list[dict[str, Any]] | None,
    deps: PipelineDependencies,
    resume: bool,
    run_signature: dict[str, Any],
    source_paths: dict[str, str | None],
) -> tuple[list[SegmentRegionScore], list[dict[str, Any]]]:
    """Score segments batch-by-batch, appending completed batches to disk."""

    paths = scoring_output_paths(output_dir)
    checkpoint = load_scoring_checkpoint(
        output_dir=output_dir,
        segments=segments,
        schema=schema,
        cfg=cfg,
        run_signature=run_signature,
        resume=resume,
    )
    scores = list(checkpoint.scores)
    scoring_warnings = list(checkpoint.warnings)
    if scores:
        _log(f"  Resuming from {len(scores)} committed segment score row(s)")
    _write_checkpoint_progress(
        output_dir=output_dir,
        status="running",
        total_segments=len(segments),
        completed_segments=len(scores),
        cfg=cfg,
        run_signature=run_signature,
        source_paths=source_paths,
        scoring_warnings=scoring_warnings,
    )
    if len(scores) == len(segments):
        _log("  All segment scores are already committed; skipping LLM scoring")
        return scores, scoring_warnings

    batch_size = max(1, cfg.scoring_batch_size)
    for batch_start in range(len(scores), len(segments), batch_size):
        batch_idx = batch_start // batch_size
        previous_warning_count = len(scoring_warnings)
        batch_scores = deps.score_description_segment_batch(
            batch_idx,
            batch_start,
            segments,
            schema,
            cfg,
            summaries,
            scoring_warnings,
        )
        batch_scores = _normalize_batch_score_metadata(
            batch_scores=batch_scores,
            batch_start=batch_start,
            batch_idx=batch_idx,
            total_segments=len(segments),
            cfg=cfg,
        )
        append_jsonl(
            paths["scores"],
            [score.to_dict() for score in batch_scores],
        )
        new_warnings = scoring_warnings[previous_warning_count:]
        if new_warnings:
            append_jsonl(paths["warnings"], new_warnings)
        scores.extend(batch_scores)
        _write_checkpoint_progress(
            output_dir=output_dir,
            status="running",
            total_segments=len(segments),
            completed_segments=len(scores),
            cfg=cfg,
            run_signature=run_signature,
            source_paths=source_paths,
            scoring_warnings=scoring_warnings,
        )
        _log(
            "  Committed score batch "
            f"{batch_idx} ({len(scores)}/{len(segments)} segment(s))",
        )
    return scores, scoring_warnings


def score_descriptions_from_file(
    args,
    cfg: ScoreDescriptionsConfig,
    deps: PipelineDependencies | None = None,
) -> None:
    """Run stage: existing dense descriptions -> region-dimension scores."""

    deps = deps or default_dependencies()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    ensure_output_policy(
        output_dir,
        resume=bool(getattr(args, "resume", False)),
        overwrite=bool(getattr(args, "overwrite", False)),
    )
    _log("Step 1/4: Load region schema")
    schema = load_region_schema(args.region_schema)
    _log(f"  Region schema ready: {len(schema.dimensions)} dimension(s) from {args.region_schema}")
    _log("Step 2/4: Load dense descriptions")
    segments = load_description_segments(args.descriptions)
    _log(f"  Loaded {len(segments)} description segments from {args.descriptions}")
    summaries = _load_scoring_summaries(getattr(args, "summary_file", None))
    if summaries is not None:
        _log(f"  Loaded {len(summaries)} Story Context summaries from {args.summary_file}")
    _log(f"Step 3/4: Score {len(segments)} description segments")
    _log(
        f"  Batch scoring config: target_batch_size={cfg.scoring_batch_size}, "
        f"local_buffer_size={cfg.local_buffer_size}",
    )
    run_signature = build_scoring_run_signature(args=args, cfg=cfg)
    source_paths = build_scoring_source_paths(args)
    scores, scoring_warnings = _score_segments_with_checkpoints(
        output_dir=output_dir,
        segments=segments,
        schema=schema,
        cfg=cfg,
        summaries=summaries,
        deps=deps,
        resume=bool(getattr(args, "resume", False)),
        run_signature=run_signature,
        source_paths=source_paths,
    )
    _log(f"  Wrote segment scores to {output_dir / 'segment_region_scores.jsonl'}")
    if scoring_warnings:
        warning_summary = _scoring_warning_summary(scoring_warnings)
        _log(
            "  Batch scoring warnings: "
            f"{warning_summary['warning_count']} warning(s), "
            f"{warning_summary['zero_filled_segments']} zero-filled segment(s)",
        )
    else:
        warning_summary = _scoring_warning_summary(scoring_warnings)
    gt_metadata: dict | None = None
    if getattr(args, "gt_dir", None):
        _log("  Average GT CSV values onto description segments")
        gt_by_emotion, gt_metadata = load_averaged_gt_csvs(
            args.gt_dir,
            file_pattern=args.gt_file_pattern,
            time_column=args.gt_time_column,
            emotion_column=args.gt_emotion_column,
        )
        gt_rows = average_gt_to_segments(segments, gt_by_emotion)
        write_jsonl(output_dir / "segment_gt_means.jsonl", gt_rows)
        _log(f"  Wrote segment GT means to {output_dir / 'segment_gt_means.jsonl'}")
    _log("Step 4/4: Align scores to TR features")
    total_trs = _infer_score_total_trs(scores, cfg, args.total_trs)
    tr_rows = align_scores_to_trs(
        scores=scores,
        schema=schema,
        total_trs=total_trs,
        cfg=cfg,
    )
    write_jsonl(output_dir / "tr_features.jsonl", [row.to_dict() for row in tr_rows])
    save_readable_tr_rows(output_dir, tr_rows)
    write_json(
        output_dir / "scoring_metadata.json",
        {
            "n_segments": len(segments),
            "n_trs": total_trs,
            "tr_s": cfg.tr_s,
            "alignment": cfg.alignment_strategy,
            "scoring_batch_size": cfg.scoring_batch_size,
            "local_buffer_size": cfg.local_buffer_size,
            "provider": cfg.generation_provider,
            "model": cfg.generation_model,
            "summary_file": getattr(args, "summary_file", None),
            "scoring_warnings": warning_summary,
            "gt": gt_metadata,
            "region_schema": args.region_schema,
            "feature_names": schema.ordered_dimension_ids(),
            "feature_metadata": [
                {
                    "dimension_id": dimension.dimension_id,
                    "domain": dimension.domain,
                }
                for dimension in schema.dimensions
            ],
        },
    )
    _write_checkpoint_progress(
        output_dir=output_dir,
        status="complete",
        total_segments=len(segments),
        completed_segments=len(scores),
        cfg=cfg,
        run_signature=run_signature,
        source_paths=source_paths,
        scoring_warnings=scoring_warnings,
    )
    _log(f"  Wrote {len(tr_rows)} TR rows to {output_dir / 'tr_features.jsonl'}")
    _log(f"  Wrote readable TR descriptions to {output_dir / 'tr_descriptions_readable.jsonl'}")
    _log(f"  Wrote scoring metadata to {output_dir / 'scoring_metadata.json'}")
    _log(f"Description-scoring stage complete. Outputs in {output_dir}")

