"""TR alignment for region-schema dimension scores."""

from __future__ import annotations

from typing import Sequence

from ..core.config import ScoreDescriptionsConfig
from ..schema_design.schema_models import RegionFeatureSchema
from .models import SegmentRegionScore, TRFeatureRow


def _overlap_s(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Return interval overlap in seconds."""

    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def _nearest_score_idx(tr_mid: float, scores: Sequence[SegmentRegionScore]) -> int:
    """Return the score segment whose midpoint is closest to the TR midpoint."""

    return min(
        range(len(scores)),
        key=lambda idx: abs((scores[idx].start_s + scores[idx].end_s) / 2 - tr_mid),
    )


def _score_vector(score: SegmentRegionScore, schema: RegionFeatureSchema) -> list[float]:
    """Flatten dimension scores in region-schema order."""

    return [
        float(score.dimension_scores[dimension.dimension_id])
        for dimension in schema.dimensions
    ]


def _weighted_average_vectors(vectors: list[list[float]], weights: list[float]) -> list[float]:
    """Compute a weighted average of score vectors."""

    total_weight = sum(weights) or float(len(vectors))
    if sum(weights) == 0:
        weights = [1.0] * len(vectors)
    result = [0.0] * len(vectors[0])
    for vector, weight in zip(vectors, weights):
        for idx, value in enumerate(vector):
            result[idx] += value * weight
    return [value / total_weight for value in result]


def align_scores_to_trs(
    *,
    scores: Sequence[SegmentRegionScore],
    schema: RegionFeatureSchema,
    total_trs: int,
    cfg: ScoreDescriptionsConfig,
) -> list[TRFeatureRow]:
    """Align segment-level region scores to TR rows."""

    if not scores:
        return []
    rows: list[TRFeatureRow] = []
    for tr_idx in range(total_trs):
        tr_start = tr_idx * cfg.tr_s
        tr_end = (tr_idx + 1) * cfg.tr_s
        overlaps = [
            (seg_idx, _overlap_s(tr_start, tr_end, score.start_s, score.end_s) / cfg.tr_s)
            for seg_idx, score in enumerate(scores)
        ]
        overlaps = [(seg_idx, weight) for seg_idx, weight in overlaps if weight > 0]
        if overlaps and cfg.alignment_strategy == "repeat":
            best_idx, best_weight = max(overlaps, key=lambda item: item[1])
            feature_vector = _score_vector(scores[best_idx], schema)
            weight_dict = {f"seg_{best_idx}": round(best_weight, 4)}
        elif overlaps:
            best_idx = max(overlaps, key=lambda item: item[1])[0]
            feature_vector = _weighted_average_vectors(
                [_score_vector(scores[idx], schema) for idx, _ in overlaps],
                [weight for _, weight in overlaps],
            )
            weight_dict = {f"seg_{idx}": round(weight, 4) for idx, weight in overlaps}
        else:
            nearest_idx = _nearest_score_idx((tr_start + tr_end) / 2, scores)
            best_idx = nearest_idx
            feature_vector = _score_vector(scores[nearest_idx], schema)
            weight_dict = {f"seg_{nearest_idx}_nearest": 1.0}
        rows.append(
            TRFeatureRow(
                tr_index=tr_idx,
                tr_start_s=round(tr_start, 4),
                tr_end_s=round(tr_end, 4),
                source_description=scores[best_idx].description,
                feature_vector=feature_vector,
                weights=weight_dict,
            ),
        )
    return rows
