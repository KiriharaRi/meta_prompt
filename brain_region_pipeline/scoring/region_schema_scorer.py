"""LLM scoring of existing dense descriptions using a region schema."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..core.config import ScoreDescriptionsConfig
from ..core.genai import generate_structured_json
from ..schema_design.schema_models import RegionFeatureSchema
from .models import DescriptionSegment, SegmentRegionScore

SCORE_SYSTEM_INSTRUCTION = """\
You infer brain-region-relevant dimensions from existing dense movie descriptions.

Use only the provided text description. Do not invent visual events beyond the
description. Apply the region scoring instruction and score every dimension
according to its anchors. Calibrate intensity from the perspective of a typical
viewer watching the movie, while still scoring the specified brain-region
narrative/appraisal dimension rather than directly predicting the viewer's final
emotion rating. Use evidence and anchors internally, but output scores only.
"""

VIEWER_PERSPECTIVE_INSTRUCTION = (
    "Score from the perspective of a typical viewer watching the movie. "
    "Calibrate each dimension by what the described segment would make salient "
    "or meaningful to that viewer"
)

TARGET_SEGMENT_EVIDENCE_INSTRUCTION = (
    "Use Target Segments as the only direct scoring evidence. Story Context "
    "and Local Buffer may resolve identity, relationships, references, and "
    "narrative continuity, but they must not raise or lower any Target Segment "
    "score unless that Target Segment itself contains evidence that a prior "
    "state continues or becomes salient."
)


def _dimension_scores_schema(schema: RegionFeatureSchema) -> dict[str, Any]:
    """Build the shared dimension-score JSON schema block."""

    properties = {
        dimension.dimension_id: {
            "type": "number",
            "minimum": dimension.score_min,
            "maximum": dimension.score_max,
        }
        for dimension in schema.dimensions
    }
    return {
        "type": "object",
        "required": schema.ordered_dimension_ids(),
        "additionalProperties": False,
        "properties": properties,
    }


def build_score_schema(schema: RegionFeatureSchema) -> dict[str, Any]:
    """Build the dynamic JSON schema for one segment score."""

    return {
        "type": "object",
        "required": ["dimension_scores"],
        "additionalProperties": False,
        "properties": {
            "dimension_scores": _dimension_scores_schema(schema),
        },
    }


def build_batch_score_schema(schema: RegionFeatureSchema) -> dict[str, Any]:
    """Build the dynamic JSON schema for batch dimension scoring."""

    return {
        "type": "object",
        "required": ["segment_scores"],
        "additionalProperties": False,
        "properties": {
            "segment_scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["segment_id", "timestamp", "dimension_scores"],
                    "additionalProperties": False,
                    "properties": {
                        "segment_id": {"type": "integer"},
                        "timestamp": {"type": "string"},
                        "dimension_scores": _dimension_scores_schema(schema),
                    },
                },
            },
        },
    }


def _render_trigger_list(triggers: Sequence[str]) -> list[str]:
    """Render dimension trigger patterns for scorer prompts."""

    if not triggers:
        return []
    return [
        "      trigger_list:",
        *[f"        - {trigger}" for trigger in triggers],
    ]


def _render_graded_anchors(anchors: dict[str, str]) -> list[str]:
    """Render ordered 0-10 anchors and any extra labels."""

    if not anchors:
        return []
    labels = [str(score) for score in range(11)]
    known_labels = set(labels)
    labels.extend(sorted(label for label in anchors if label not in known_labels))
    return [
        "      graded_anchors:",
        *[
            f"        {label}: {anchors[label]}"
            for label in labels
            if anchors.get(label)
        ],
    ]


def _render_calibration_examples(examples: Sequence[dict[str, Any]]) -> list[str]:
    """Render short calibration examples for scorer prompts."""

    if not examples:
        return []
    lines = ["      calibration_examples:"]
    for example in examples:
        score = example.get("score", "?")
        lines.append(f"        - score {score}: {example.get('scene', '')}")
    return lines


def _schema_prompt_block(schema: RegionFeatureSchema) -> str:
    """Render region schema dimensions and anchors for the scorer."""

    lines: list[str] = [
        f"target_region: {schema.target_region}",
        f"functional_hypothesis: {schema.functional_hypothesis}",
        f"scoring_instruction: {schema.scoring_instruction}",
        "dimensions:",
    ]
    for dimension in schema.dimensions:
        lines.extend(
            [
                f"  - {dimension.dimension_id} ({dimension.score_min:g} to {dimension.score_max:g})",
                f"    domain: {dimension.domain}",
                f"    definition: {dimension.definition}",
                f"    scoreability_note: {dimension.scoreability_note}",
                f"    exclusion_note: {dimension.exclusion_note}",
                *_render_trigger_list(dimension.trigger_list),
                *_render_graded_anchors(dimension.graded_anchors),
                *_render_calibration_examples(dimension.calibration_examples),
            ],
        )
    return "\n".join(lines)


def _score_prompt(segment: DescriptionSegment, schema: RegionFeatureSchema) -> str:
    """Build the user prompt for one description segment."""

    return "\n".join(
        [
            "Score this dense description segment for the region schema.",
            f"Time range: [{segment.start_s:.2f}s, {segment.end_s:.2f}s)",
            "",
            "Region schema and dimensions:",
            _schema_prompt_block(schema),
            "",
            "Instruction:",
            VIEWER_PERSPECTIVE_INSTRUCTION,
            "Use evidence and anchors internally, but output scores only. Do not "
            "include rationales or explanatory text.",
            "",
            "Dense description:",
            segment.description,
        ],
    )


def _segment_timestamp(segment: DescriptionSegment) -> str:
    """Return a stable timestamp label for a segment."""

    return f"{segment.start_s:.2f}s - {segment.end_s:.2f}s"


def _render_segment_line(segment_id: int, segment: DescriptionSegment) -> str:
    """Render one segment line for batch prompts."""

    return (
        f"[segment_id={segment_id}] "
        f"{_segment_timestamp(segment)} "
        f"{segment.description}"
    )


def _summary_context(
    summaries: Sequence[dict[str, Any]] | None,
    batch_idx: int,
) -> str:
    """Return the cumulative summary available before a target batch."""

    if not summaries or batch_idx <= 0 or batch_idx - 1 >= len(summaries):
        return ""
    return str(summaries[batch_idx - 1].get("cumulative_summary", "")).strip()


def _batch_score_prompt(
    *,
    batch_idx: int,
    buffer_segments: Sequence[tuple[int, DescriptionSegment]],
    target_segments: Sequence[tuple[int, DescriptionSegment]],
    schema: RegionFeatureSchema,
    summaries: Sequence[dict[str, Any]] | None,
) -> str:
    """Build the user prompt for one context-enhanced target segment batch."""

    cumulative_summary = _summary_context(summaries, batch_idx)
    lines = [
        "Score the Target Segments for the region schema.",
        "Use Story Context and Local Buffer only to resolve narrative context.",
        "Do not output scores for Local Buffer segments.",
        "",
        "# Story Context (L1 - Long-term Memory)",
        '"""',
        cumulative_summary or "(Beginning of the movie - no prior context)",
        '"""',
        "",
        "# Local Buffer (L2 - Short-term Memory, FOR REFERENCE ONLY)",
        '"""',
    ]
    if buffer_segments:
        lines.extend(
            _render_segment_line(idx, segment)
            for idx, segment in buffer_segments
        )
    else:
        lines.append("(No prior segments in this batch)")
    lines.extend(
        [
            '"""',
            "",
            "# Target Segments (SCORE THESE ONLY)",
            '"""',
        ],
    )
    lines.extend(_render_segment_line(idx, segment) for idx, segment in target_segments)
    lines.extend(
        [
            '"""',
            "",
            "Region schema and dimensions:",
            _schema_prompt_block(schema),
            "",
            "# Instruction",
            "Return one result for every Target Segment segment_id, in target order.",
            "Each score must follow the dimension anchors.",
            TARGET_SEGMENT_EVIDENCE_INSTRUCTION,
            VIEWER_PERSPECTIVE_INSTRUCTION,
            "Use evidence and anchors internally, but output scores only. Do not "
            "include rationales or explanatory text.",
        ],
    )
    return "\n".join(lines)


def _parse_dimension_scores(raw_scores: dict[str, Any]) -> dict[str, float]:
    """Parse dimension score payloads into floats."""

    return {
        str(dimension_id): float(score)
        for dimension_id, score in raw_scores.items()
    }


def _zero_dimension_scores(schema: RegionFeatureSchema) -> dict[str, float]:
    """Build zero-valued scores for every active dimension."""

    return {
        dimension.dimension_id: 0.0
        for dimension in schema.dimensions
    }


def _segment_score_from_payload(
    *,
    segment: DescriptionSegment,
    payload: dict[str, Any],
    schema: RegionFeatureSchema,
    warnings: list[dict[str, Any]],
    batch_idx: int,
    segment_id: int,
) -> SegmentRegionScore:
    """Parse one batch payload row, filling missing dimensions with zeros."""

    raw_dimension_scores = payload.get("dimension_scores") or {}
    dimension_scores: dict[str, float] = {}
    missing_dimensions: list[str] = []
    for dimension in schema.dimensions:
        if dimension.dimension_id in raw_dimension_scores:
            dimension_scores[dimension.dimension_id] = float(
                raw_dimension_scores[dimension.dimension_id],
            )
        else:
            dimension_scores[dimension.dimension_id] = 0.0
            missing_dimensions.append(dimension.dimension_id)
    if missing_dimensions:
        warnings.append(
            {
                "batch_idx": batch_idx,
                "segment_id": segment_id,
                "reason": "missing_dimensions_zero_filled",
                "dimension_ids": missing_dimensions,
            },
        )
    return SegmentRegionScore(
        start_s=segment.start_s,
        end_s=segment.end_s,
        description=segment.description,
        dimension_scores=dimension_scores,
        rationale=str(payload.get("rationale", "")).strip(),
        segment_id=segment_id,
        batch_idx=batch_idx,
    )


def _zero_segment_score(
    segment: DescriptionSegment,
    schema: RegionFeatureSchema,
    rationale: str,
    segment_id: int | None = None,
    batch_idx: int | None = None,
) -> SegmentRegionScore:
    """Build one zero-valued segment score."""

    return SegmentRegionScore(
        start_s=segment.start_s,
        end_s=segment.end_s,
        description=segment.description,
        dimension_scores=_zero_dimension_scores(schema),
        rationale=rationale,
        segment_id=segment_id,
        batch_idx=batch_idx,
    )


def _score_segment_batch(
    *,
    batch_idx: int,
    batch_start: int,
    segments: list[DescriptionSegment],
    schema_obj: RegionFeatureSchema,
    cfg: ScoreDescriptionsConfig,
    response_schema: dict[str, Any],
    summaries: Sequence[dict[str, Any]] | None,
    warnings: list[dict[str, Any]],
) -> list[SegmentRegionScore]:
    """Score one target batch, zero-filling failures while recording warnings."""

    batch_end = min(batch_start + cfg.scoring_batch_size, len(segments))
    buffer_start = max(0, batch_start - cfg.local_buffer_size)
    target_pairs = list(enumerate(segments[batch_start:batch_end], start=batch_start))
    buffer_pairs = list(
        enumerate(segments[buffer_start:batch_start], start=buffer_start),
    )
    prompt = _batch_score_prompt(
        batch_idx=batch_idx,
        buffer_segments=buffer_pairs,
        target_segments=target_pairs,
        schema=schema_obj,
        summaries=summaries,
    )
    try:
        payload = generate_structured_json(
            model=cfg.generation_model,
            system_instruction=SCORE_SYSTEM_INSTRUCTION,
            contents=[prompt],
            response_schema=response_schema,
            cfg=cfg,
        )
    except Exception as exc:
        warnings.append(
            {
                "batch_idx": batch_idx,
                "segment_range": [batch_start, batch_end - 1],
                "reason": "batch_generation_failed_zero_filled",
                "error": str(exc),
                "zero_filled_segments": len(target_pairs),
            },
        )
        rationale = f"Zero-filled because batch scoring failed: {exc}"
        return [
            _zero_segment_score(
                segment,
                schema_obj,
                rationale,
                segment_id=segment_id,
                batch_idx=batch_idx,
            )
            for segment_id, segment in target_pairs
        ]

    payload_by_id: dict[int, dict[str, Any]] = {}
    for item in payload.get("segment_scores", []):
        try:
            payload_by_id[int(item["segment_id"])] = item
        except (KeyError, TypeError, ValueError):
            warnings.append(
                {
                    "batch_idx": batch_idx,
                    "reason": "invalid_segment_score_ignored",
                    "payload": item,
                },
            )

    rows: list[SegmentRegionScore] = []
    for segment_id, segment in target_pairs:
        item = payload_by_id.get(segment_id)
        if item is None:
            warnings.append(
                {
                    "batch_idx": batch_idx,
                    "segment_id": segment_id,
                    "reason": "missing_segment_zero_filled",
                },
            )
            rows.append(
                _zero_segment_score(
                    segment,
                    schema_obj,
                    "Zero-filled because this target segment was missing from "
                    "the batch scoring response.",
                    segment_id=segment_id,
                    batch_idx=batch_idx,
                ),
            )
            continue
        rows.append(
            _segment_score_from_payload(
                segment=segment,
                payload=item,
                schema=schema_obj,
                warnings=warnings,
                batch_idx=batch_idx,
                segment_id=segment_id,
            ),
        )
    return rows


def score_description_segment_batch(
    batch_idx: int,
    batch_start: int,
    segments: list[DescriptionSegment],
    schema: RegionFeatureSchema,
    cfg: ScoreDescriptionsConfig,
    summaries: Sequence[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> list[SegmentRegionScore]:
    """Score one runner-managed batch while preserving original segment ids."""

    warning_rows = warnings if warnings is not None else []
    if cfg.scoring_batch_size > 1:
        return _score_segment_batch(
            batch_idx=batch_idx,
            batch_start=batch_start,
            segments=segments,
            schema_obj=schema,
            cfg=cfg,
            response_schema=build_batch_score_schema(schema),
            summaries=summaries,
            warnings=warning_rows,
        )

    if batch_start >= len(segments):
        return []
    segment = segments[batch_start]
    payload = generate_structured_json(
        model=cfg.generation_model,
        system_instruction=SCORE_SYSTEM_INSTRUCTION,
        contents=[_score_prompt(segment, schema)],
        response_schema=build_score_schema(schema),
        cfg=cfg,
    )
    return [
        SegmentRegionScore(
            start_s=segment.start_s,
            end_s=segment.end_s,
            description=segment.description,
            dimension_scores=_parse_dimension_scores(payload["dimension_scores"]),
            segment_id=batch_start,
            batch_idx=batch_idx,
        ),
    ]


def score_description_segments(
    segments: list[DescriptionSegment],
    schema: RegionFeatureSchema,
    cfg: ScoreDescriptionsConfig,
    summaries: Sequence[dict[str, Any]] | None = None,
    warnings: list[dict[str, Any]] | None = None,
) -> list[SegmentRegionScore]:
    """Score dense description segments with the configured LLM."""

    if cfg.scoring_batch_size > 1:
        warning_rows = warnings if warnings is not None else []
        rows: list[SegmentRegionScore] = []
        batch_size = max(1, cfg.scoring_batch_size)
        for batch_idx, batch_start in enumerate(range(0, len(segments), batch_size)):
            rows.extend(
                score_description_segment_batch(
                    batch_idx,
                    batch_start,
                    segments,
                    schema,
                    cfg,
                    summaries,
                    warning_rows,
                ),
            )
        return rows

    rows: list[SegmentRegionScore] = []
    response_schema = build_score_schema(schema)
    for segment in segments:
        payload = generate_structured_json(
            model=cfg.generation_model,
            system_instruction=SCORE_SYSTEM_INSTRUCTION,
            contents=[_score_prompt(segment, schema)],
            response_schema=response_schema,
            cfg=cfg,
        )
        rows.append(
            SegmentRegionScore(
                start_s=segment.start_s,
                end_s=segment.end_s,
                description=segment.description,
                dimension_scores=_parse_dimension_scores(payload["dimension_scores"]),
            ),
        )
    return rows
