"""Generate a presentation-readable interpretability report for round8 encoding.

This is a run-specific analysis script. It reads existing Ridge encoding
outputs, region schemas, and test-split TR features; it does not rerun scoring
or encoding and is intentionally kept outside the maintained
``brain_region_pipeline`` package.
"""

from __future__ import annotations

import csv
import json
import math
import textwrap
from argparse import ArgumentParser, Namespace
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import matplotlib
import numpy as np
from numpy.typing import NDArray

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENCODING_DIR = (
    REPO_ROOT
    / "friends"
    / "analysis"
    / "train_size_sweep_20260629_round8"
    / "encoding_145train_10test_snapshot"
)
DEFAULT_FULL_RUN_ENCODING_DIR = (
    REPO_ROOT
    / "friends"
    / "full_runs"
    / "friends_full_scoring_start_14roi_gemini35_20260612"
    / "encoding"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "friends"
    / "analysis"
    / "train_size_sweep_20260629_round8"
    / "interpretability_report_145train_10test"
)
TOP_ROI_COUNT = 8
TOP_FEATURE_ROWS = 10
CONTRIBUTION_TOP_FEATURES = 20
HEATMAP_FEATURES_PER_ROI = 3
EXAMPLES_PER_ROI = 3


@dataclass(frozen=True)
class DimensionInfo:
    """Schema metadata for one source ROI feature dimension."""

    source_schema_roi: str
    dimension_id: str
    dimension_index: int
    domain: str
    definition: str
    trigger_list: tuple[str, ...]
    scoreability_note: str
    exclusion_note: str


@dataclass(frozen=True)
class FeatureInfo:
    """Expanded Ridge feature mapped back to schema metadata."""

    feature_index: int
    expanded_feature_name: str
    source_schema_roi: str
    dimension_id: str
    lag: int
    dimension_index: int
    domain: str
    definition: str
    trigger_list: tuple[str, ...]
    scoreability_note: str
    exclusion_note: str


@dataclass(frozen=True)
class RoiPerformance:
    """One ROI-level performance row from the encoding group summary."""

    rank: int
    roi_id: str
    mean_test_pearson: float
    median_test_pearson: float
    n_retained_parcels: int
    n_total_selected_parcels: int


@dataclass(frozen=True)
class WeightRow:
    """One target-ROI coefficient aggregation row."""

    target_roi: str
    rank: int
    direction: str
    feature_index: int
    expanded_feature_name: str
    source_schema_roi: str
    dimension_id: str
    domain: str
    lag: int
    mean_coef: float
    mean_abs_coef: float
    positive_fraction: float
    negative_fraction: float
    sign_consistency: float
    n_target_parcels: int
    definition: str
    trigger_list: tuple[str, ...]
    scoreability_note: str
    exclusion_note: str


@dataclass(frozen=True)
class ExampleRow:
    """Representative held-out test example for one ROI-feature link."""

    target_roi: str
    direction: str
    source_schema_roi: str
    dimension_id: str
    domain: str
    lag: int
    episode_id: str
    sample_id: str
    target_tr_index: int
    feature_tr_index: int
    feature_score: float
    local_mean_abs_error: float
    local_error_percentile: float
    tr_start_s: float | None
    tr_end_s: float | None
    source_description: str
    definition: str


def _repo_path(raw_path: str | Path) -> Path:
    """Resolve CLI paths relative to the repository root."""

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_idx, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}: invalid JSON on line {line_idx}") from exc
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _write_csv(path: Path, rows: Sequence[dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _load_dimension_lookup(roi_schemas_path: Path) -> dict[tuple[str, str], DimensionInfo]:
    """Load source ROI schema metadata keyed by ``(roi_id, dimension_id)``."""

    payload = _read_json(roi_schemas_path)
    schema_paths = payload.get("roi_schemas")
    if not isinstance(schema_paths, dict) or not schema_paths:
        raise ValueError(f"{roi_schemas_path} must contain non-empty roi_schemas.")

    lookup: dict[tuple[str, str], DimensionInfo] = {}
    for roi_id, raw_schema_path in schema_paths.items():
        schema_path = (roi_schemas_path.parent / str(raw_schema_path)).resolve()
        schema = _read_json(schema_path)
        dimensions = schema.get("dimensions")
        if not isinstance(dimensions, list) or not dimensions:
            raise ValueError(f"{schema_path} has no dimensions.")
        for dim_idx, item in enumerate(dimensions):
            dimension_id = str(item["dimension_id"])
            lookup[(str(roi_id), dimension_id)] = DimensionInfo(
                source_schema_roi=str(roi_id),
                dimension_id=dimension_id,
                dimension_index=dim_idx,
                domain=str(item.get("domain", "")),
                definition=str(item.get("definition", "")),
                trigger_list=tuple(str(value) for value in item.get("trigger_list", [])),
                scoreability_note=str(item.get("scoreability_note", "")),
                exclusion_note=str(item.get("exclusion_note", "")),
            )
    return lookup


def _parse_expanded_feature_name(name: str) -> tuple[str, str, int]:
    """Parse ``ROI::dimension_id_lagN`` while allowing underscores in IDs."""

    if "::" not in name:
        raise ValueError(f"Expanded feature name lacks source ROI delimiter: {name}")
    source_roi, rest = name.split("::", 1)
    dimension_id, separator, lag_text = rest.rpartition("_lag")
    if not separator or not dimension_id or not lag_text.isdigit():
        raise ValueError(f"Expanded feature name lacks numeric lag suffix: {name}")
    return source_roi, dimension_id, int(lag_text)


def _load_feature_infos(
    expanded_feature_names: Sequence[str],
    dimension_lookup: dict[tuple[str, str], DimensionInfo],
) -> list[FeatureInfo]:
    """Map kept Ridge feature columns to schema dimensions and lags."""

    infos: list[FeatureInfo] = []
    for feature_idx, raw_name in enumerate(expanded_feature_names):
        name = str(raw_name)
        source_roi, dimension_id, lag = _parse_expanded_feature_name(name)
        dimension = dimension_lookup.get((source_roi, dimension_id))
        if dimension is None:
            raise ValueError(
                f"Feature {name!r} references missing schema dimension "
                f"{source_roi}::{dimension_id}."
            )
        infos.append(
            FeatureInfo(
                feature_index=feature_idx,
                expanded_feature_name=name,
                source_schema_roi=source_roi,
                dimension_id=dimension_id,
                lag=lag,
                dimension_index=dimension.dimension_index,
                domain=dimension.domain,
                definition=dimension.definition,
                trigger_list=dimension.trigger_list,
                scoreability_note=dimension.scoreability_note,
                exclusion_note=dimension.exclusion_note,
            )
        )
    return infos


def _load_performance(group_summary_path: Path) -> list[RoiPerformance]:
    """Load all ROI metrics and rank by mean test Pearson."""

    summary = _read_json(group_summary_path)
    roi_summaries = summary.get("roi_summaries")
    if not isinstance(roi_summaries, dict) or not roi_summaries:
        raise ValueError(f"{group_summary_path} is missing roi_summaries.")

    subjects = summary.get("subjects") or []
    subject_roi_summaries = subjects[0].get("roi_summaries", {}) if subjects else {}
    metric_key = (
        "mean_subject_mean_test_pearson"
        if all("mean_subject_mean_test_pearson" in row for row in roi_summaries.values())
        else "mean_test_pearson"
    )
    rows: list[RoiPerformance] = []
    for rank, (roi_id, group_row) in enumerate(
        sorted(roi_summaries.items(), key=lambda item: float(item[1][metric_key]), reverse=True),
        start=1,
    ):
        subject_row = subject_roi_summaries.get(roi_id, {})
        median = subject_row.get(
            "median_test_pearson",
            group_row.get("median_subject_mean_test_pearson", group_row.get("median_test_pearson")),
        )
        rows.append(
            RoiPerformance(
                rank=rank,
                roi_id=str(roi_id),
                mean_test_pearson=float(group_row[metric_key]),
                median_test_pearson=float(median),
                n_retained_parcels=int(subject_row.get("n_retained_parcels", 0)),
                n_total_selected_parcels=int(subject_row.get("n_total_selected_parcels", 0)),
            )
        )
    return rows


def _membership_mask(memberships: NDArray[Any], target_roi: str) -> NDArray[np.bool_]:
    """Return parcel mask for ROI membership strings such as ``TPJ|IPL``."""

    mask = []
    for raw_value in memberships:
        values = {item for item in str(raw_value).split("|") if item}
        mask.append(target_roi in values)
    result = np.asarray(mask, dtype=bool)
    if not result.any():
        raise ValueError(f"No retained parcels found for ROI {target_roi!r}.")
    return result


def _weight_rows_for_roi(
    *,
    target_roi: str,
    coef: NDArray[np.float64],
    memberships: NDArray[Any],
    feature_infos: Sequence[FeatureInfo],
    direction: str,
    top_n: int,
) -> list[WeightRow]:
    """Aggregate parcel coefficients within a target ROI and rank features."""

    mask = _membership_mask(memberships, target_roi)
    roi_coef = coef[mask, :]
    mean_coef = roi_coef.mean(axis=0)
    mean_abs_coef = np.abs(roi_coef).mean(axis=0)
    positive_fraction = (roi_coef > 0).mean(axis=0)
    negative_fraction = (roi_coef < 0).mean(axis=0)
    sign_consistency = np.maximum(positive_fraction, negative_fraction)

    if direction == "positive":
        order = np.argsort(-mean_coef)
    elif direction == "negative":
        order = np.argsort(mean_coef)
    elif direction == "absolute":
        order = np.argsort(-mean_abs_coef)
    else:
        raise ValueError(f"Unknown direction: {direction}")

    rows: list[WeightRow] = []
    for rank, feature_idx in enumerate(order[:top_n], start=1):
        info = feature_infos[int(feature_idx)]
        rows.append(
            WeightRow(
                target_roi=target_roi,
                rank=rank,
                direction=direction,
                feature_index=int(feature_idx),
                expanded_feature_name=info.expanded_feature_name,
                source_schema_roi=info.source_schema_roi,
                dimension_id=info.dimension_id,
                domain=info.domain,
                lag=info.lag,
                mean_coef=float(mean_coef[feature_idx]),
                mean_abs_coef=float(mean_abs_coef[feature_idx]),
                positive_fraction=float(positive_fraction[feature_idx]),
                negative_fraction=float(negative_fraction[feature_idx]),
                sign_consistency=float(sign_consistency[feature_idx]),
                n_target_parcels=int(mask.sum()),
                definition=info.definition,
                trigger_list=info.trigger_list,
                scoreability_note=info.scoreability_note,
                exclusion_note=info.exclusion_note,
            )
        )
    return rows


def _weight_row_to_dict(row: WeightRow) -> dict[str, Any]:
    return {
        "target_roi": row.target_roi,
        "rank": row.rank,
        "direction": row.direction,
        "feature_index": row.feature_index,
        "expanded_feature_name": row.expanded_feature_name,
        "source_schema_roi": row.source_schema_roi,
        "dimension_id": row.dimension_id,
        "domain": row.domain,
        "lag": row.lag,
        "mean_coef": f"{row.mean_coef:.12f}",
        "mean_abs_coef": f"{row.mean_abs_coef:.12f}",
        "positive_fraction": f"{row.positive_fraction:.6f}",
        "negative_fraction": f"{row.negative_fraction:.6f}",
        "sign_consistency": f"{row.sign_consistency:.6f}",
        "n_target_parcels": row.n_target_parcels,
        "definition": row.definition,
        "trigger_list": "; ".join(row.trigger_list),
        "scoreability_note": row.scoreability_note,
        "exclusion_note": row.exclusion_note,
    }


def _contribution_rows(
    *,
    target_rois: Sequence[str],
    coef: NDArray[np.float64],
    memberships: NDArray[Any],
    feature_infos: Sequence[FeatureInfo],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Summarize source-schema and lag mass among each ROI's top absolute features."""

    source_rows: list[dict[str, Any]] = []
    lag_rows: list[dict[str, Any]] = []
    for target_roi in target_rois:
        mask = _membership_mask(memberships, target_roi)
        mean_abs = np.abs(coef[mask, :]).mean(axis=0)
        top_indices = [int(idx) for idx in np.argsort(-mean_abs)[:CONTRIBUTION_TOP_FEATURES]]
        total_mass = float(sum(mean_abs[idx] for idx in top_indices)) or 1.0

        source_mass: dict[str, float] = defaultdict(float)
        source_count: Counter[str] = Counter()
        lag_mass: dict[int, float] = defaultdict(float)
        lag_count: Counter[int] = Counter()
        for idx in top_indices:
            info = feature_infos[idx]
            value = float(mean_abs[idx])
            source_mass[info.source_schema_roi] += value
            source_count[info.source_schema_roi] += 1
            lag_mass[info.lag] += value
            lag_count[info.lag] += 1

        for source_roi, value in sorted(source_mass.items(), key=lambda item: item[1], reverse=True):
            source_rows.append(
                {
                    "target_roi": target_roi,
                    "source_schema_roi": source_roi,
                    "top_feature_count": source_count[source_roi],
                    "mean_abs_coef_mass": f"{value:.12f}",
                    "fraction_of_top_abs_mass": f"{value / total_mass:.6f}",
                    "self_schema": str(source_roi == target_roi).lower(),
                    "top_n_features": CONTRIBUTION_TOP_FEATURES,
                }
            )

        for lag, value in sorted(lag_mass.items()):
            lag_rows.append(
                {
                    "target_roi": target_roi,
                    "lag": lag,
                    "top_feature_count": lag_count[lag],
                    "mean_abs_coef_mass": f"{value:.12f}",
                    "fraction_of_top_abs_mass": f"{value / total_mass:.6f}",
                    "top_n_features": CONTRIBUTION_TOP_FEATURES,
                }
            )
    return source_rows, lag_rows


def _load_manifest_by_sample(manifest_path: Path, prediction_sample_ids: set[str]) -> dict[str, dict[str, Any]]:
    """Load manifest rows for prediction sample IDs only."""

    rows = _read_jsonl(manifest_path)
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        sample_id = str(row.get("sample_id", ""))
        if sample_id in prediction_sample_ids:
            selected[sample_id] = row
    missing = sorted(prediction_sample_ids.difference(selected))
    if missing:
        raise ValueError(f"Manifest is missing prediction sample IDs: {missing}")
    return selected


def _load_tr_rows(path: Path) -> dict[int, dict[str, Any]]:
    rows_by_tr: dict[int, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        rows_by_tr[int(row["tr_index"])] = row
    return rows_by_tr


def _episode_from_sample(sample_id: str) -> str:
    return sample_id.split("_", 1)[1] if "_" in sample_id else sample_id


def _clip_text(value: str, max_chars: int) -> str:
    text = " ".join(str(value).split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _local_error_percentile(errors: NDArray[np.float64], value: float) -> float:
    if errors.size == 0:
        return math.nan
    return float((errors <= value).sum() / errors.size * 100.0)


def _select_example(
    *,
    target_roi: str,
    row: WeightRow,
    feature_info: FeatureInfo,
    manifest_by_sample: dict[str, dict[str, Any]],
    manifest_path: Path,
    prediction_sample_ids: NDArray[Any],
    prediction_feature_trs: NDArray[np.int64],
    local_errors: NDArray[np.float64],
    tr_cache: dict[tuple[str, str], dict[int, dict[str, Any]]],
) -> ExampleRow | None:
    """Pick a high-activation held-out feature row with low local prediction error."""

    candidates: list[tuple[float, float, int, dict[str, Any], str, int]] = []
    for pred_idx, raw_sample_id in enumerate(prediction_sample_ids):
        sample_id = str(raw_sample_id)
        manifest_row = manifest_by_sample.get(sample_id)
        if manifest_row is None:
            continue
        feature_tr_index = int(prediction_feature_trs[pred_idx]) - feature_info.lag
        if feature_tr_index < 0:
            continue
        cache_key = (feature_info.source_schema_roi, sample_id)
        if cache_key not in tr_cache:
            raw_feature_path = manifest_row["roi_features"][feature_info.source_schema_roi]
            feature_path = (manifest_path.parent / str(raw_feature_path)).resolve()
            tr_cache[cache_key] = _load_tr_rows(feature_path)
        tr_row = tr_cache[cache_key].get(feature_tr_index)
        if tr_row is None:
            continue
        vector = tr_row.get("feature_vector")
        if not isinstance(vector, list) or feature_info.dimension_index >= len(vector):
            continue
        feature_score = float(vector[feature_info.dimension_index])
        if not math.isfinite(feature_score):
            continue
        error = float(local_errors[pred_idx])
        if not math.isfinite(error):
            continue
        candidates.append((feature_score, error, pred_idx, tr_row, sample_id, feature_tr_index))

    if not candidates:
        return None
    positive_candidates = [item for item in candidates if item[0] > 0]
    active_candidates = positive_candidates or candidates
    scores = np.asarray([item[0] for item in active_candidates], dtype=np.float64)
    activation_threshold = float(np.quantile(scores, 0.50)) if scores.size > 3 else float(scores.max())
    high_activation_candidates = [
        item for item in active_candidates if item[0] >= activation_threshold
    ] or active_candidates
    # Within visibly active held-out rows, prefer a low local ROI prediction
    # error so the qualitative example reflects a region the model predicted
    # comparatively well, not merely the largest feature score.
    high_activation_candidates.sort(key=lambda item: (item[1], -item[0]))
    feature_score, error, pred_idx, tr_row, sample_id, feature_tr_index = high_activation_candidates[0]
    return ExampleRow(
        target_roi=target_roi,
        direction=row.direction,
        source_schema_roi=feature_info.source_schema_roi,
        dimension_id=feature_info.dimension_id,
        domain=feature_info.domain,
        lag=feature_info.lag,
        episode_id=_episode_from_sample(sample_id),
        sample_id=sample_id,
        target_tr_index=int(prediction_feature_trs[pred_idx]),
        feature_tr_index=int(feature_tr_index),
        feature_score=float(feature_score),
        local_mean_abs_error=float(error),
        local_error_percentile=_local_error_percentile(local_errors, error),
        tr_start_s=float(tr_row["tr_start_s"]) if "tr_start_s" in tr_row else None,
        tr_end_s=float(tr_row["tr_end_s"]) if "tr_end_s" in tr_row else None,
        source_description=str(tr_row.get("source_description", "")),
        definition=feature_info.definition,
    )


def _example_rows(
    *,
    target_rois: Sequence[str],
    weight_rows_by_direction: dict[str, dict[str, list[WeightRow]]],
    feature_infos: Sequence[FeatureInfo],
    manifest_path: Path,
    prediction_data: dict[str, NDArray[Any]],
    memberships: NDArray[Any],
) -> list[ExampleRow]:
    """Select positive, negative, and absolute held-out examples per target ROI."""

    sample_ids = prediction_data["sample_ids"]
    manifest = _load_manifest_by_sample(manifest_path, {str(value) for value in sample_ids})
    y_true = prediction_data["y_true"].astype(np.float64)
    y_pred = prediction_data["y_pred"].astype(np.float64)
    feature_trs = prediction_data["feature_tr_indices"].astype(np.int64)
    tr_cache: dict[tuple[str, str], dict[int, dict[str, Any]]] = {}

    examples: list[ExampleRow] = []
    for target_roi in target_rois:
        mask = _membership_mask(memberships, target_roi)
        local_errors = np.mean(np.abs(y_true[:, mask] - y_pred[:, mask]), axis=1)
        selected: list[WeightRow] = []
        seen_feature_indices: set[int] = set()
        for direction in ("positive", "negative", "absolute"):
            for row in weight_rows_by_direction[target_roi][direction]:
                if row.feature_index not in seen_feature_indices:
                    selected.append(row)
                    seen_feature_indices.add(row.feature_index)
                    break
            if len(selected) >= EXAMPLES_PER_ROI:
                break

        for row in selected[:EXAMPLES_PER_ROI]:
            example = _select_example(
                target_roi=target_roi,
                row=row,
                feature_info=feature_infos[row.feature_index],
                manifest_by_sample=manifest,
                manifest_path=manifest_path,
                prediction_sample_ids=sample_ids,
                prediction_feature_trs=feature_trs,
                local_errors=local_errors,
                tr_cache=tr_cache,
            )
            if example is not None:
                examples.append(example)
    return examples


def _performance_csv_rows(rows: Sequence[RoiPerformance]) -> list[dict[str, Any]]:
    return [
        {
            "rank": row.rank,
            "roi_id": row.roi_id,
            "mean_test_pearson": f"{row.mean_test_pearson:.12f}",
            "median_test_pearson": f"{row.median_test_pearson:.12f}",
            "n_retained_parcels": row.n_retained_parcels,
            "n_total_selected_parcels": row.n_total_selected_parcels,
        }
        for row in rows
    ]


def _example_to_dict(row: ExampleRow) -> dict[str, Any]:
    return {
        "target_roi": row.target_roi,
        "direction": row.direction,
        "source_schema_roi": row.source_schema_roi,
        "dimension_id": row.dimension_id,
        "domain": row.domain,
        "lag": row.lag,
        "episode_id": row.episode_id,
        "sample_id": row.sample_id,
        "target_tr_index": row.target_tr_index,
        "feature_tr_index": row.feature_tr_index,
        "feature_score": f"{row.feature_score:.6f}",
        "local_mean_abs_error": f"{row.local_mean_abs_error:.6f}",
        "local_error_percentile": f"{row.local_error_percentile:.2f}",
        "tr_start_s": "" if row.tr_start_s is None else f"{row.tr_start_s:.2f}",
        "tr_end_s": "" if row.tr_end_s is None else f"{row.tr_end_s:.2f}",
        "source_description": row.source_description,
        "definition": row.definition,
    }


def _plot_performance(path: Path, rows: Sequence[RoiPerformance], top_rois: set[str]) -> None:
    plot_rows = list(reversed(rows))
    labels = [row.roi_id.replace("_", " ") for row in plot_rows]
    values = [row.mean_test_pearson for row in plot_rows]
    colors = ["#2563eb" if row.roi_id in top_rois else "#94a3b8" for row in plot_rows]

    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    fig.patch.set_facecolor("white")
    ax.barh(labels, values, color=colors, height=0.68)
    ax.set_title("Round8 ROI Encoding Performance", fontsize=15, weight="bold")
    ax.set_xlabel("Mean test Pearson r")
    ax.set_ylabel("Target ROI")
    ax.grid(axis="x", alpha=0.22)
    for y_idx, value in enumerate(values):
        ax.text(value + 0.004, y_idx, f"{value:.3f}", va="center", fontsize=9)
    ax.set_xlim(0, max(values) + 0.055)
    fig.tight_layout()
    fig.savefig(path, dpi=220)
    plt.close(fig)


def _plot_heatmap(
    path: Path,
    *,
    target_rois: Sequence[str],
    coef: NDArray[np.float64],
    memberships: NDArray[Any],
    feature_infos: Sequence[FeatureInfo],
) -> list[int]:
    """Plot ROI-averaged coefficients for a compact union of top features."""

    selected_indices: list[int] = []
    seen: set[int] = set()
    for target_roi in target_rois:
        mask = _membership_mask(memberships, target_roi)
        mean_abs = np.abs(coef[mask, :]).mean(axis=0)
        for idx in np.argsort(-mean_abs)[:HEATMAP_FEATURES_PER_ROI]:
            feature_idx = int(idx)
            if feature_idx not in seen:
                selected_indices.append(feature_idx)
                seen.add(feature_idx)

    matrix = []
    for target_roi in target_rois:
        mask = _membership_mask(memberships, target_roi)
        matrix.append(coef[mask, :].mean(axis=0)[selected_indices])
    data = np.vstack(matrix)
    limit = float(np.nanmax(np.abs(data))) or 1.0
    labels = [
        f"{feature_infos[idx].source_schema_roi}::{feature_infos[idx].dimension_id}_L{feature_infos[idx].lag}"
        for idx in selected_indices
    ]

    fig_width = max(12.0, len(labels) * 0.42)
    fig, ax = plt.subplots(figsize=(fig_width, 6.2))
    image = ax.imshow(data, cmap="RdBu_r", aspect="auto", vmin=-limit, vmax=limit)
    ax.set_title("Top ROI-Averaged Ridge Weights", fontsize=15, weight="bold")
    ax.set_xlabel("Source schema feature")
    ax.set_ylabel("Target ROI")
    ax.set_yticks(np.arange(len(target_rois)))
    ax.set_yticklabels(target_rois)
    ax.set_xticks(np.arange(len(labels)))
    ax.set_xticklabels(labels, rotation=65, ha="right", fontsize=7)
    colorbar = fig.colorbar(image, ax=ax, fraction=0.025, pad=0.02)
    colorbar.set_label("Mean standardized coefficient")
    fig.tight_layout()
    fig.savefig(path, dpi=220)
    plt.close(fig)
    return selected_indices


def _plot_stacked_bar(
    path: Path,
    *,
    rows: Sequence[dict[str, Any]],
    target_rois: Sequence[str],
    category_field: str,
    value_field: str,
    title: str,
    xlabel: str,
) -> None:
    categories = sorted({str(row[category_field]) for row in rows})
    values_by_roi = {roi: {category: 0.0 for category in categories} for roi in target_rois}
    for row in rows:
        values_by_roi[str(row["target_roi"])][str(row[category_field])] = float(row[value_field])

    fig, ax = plt.subplots(figsize=(11.5, 5.8))
    fig.patch.set_facecolor("white")
    left = np.zeros(len(target_rois), dtype=np.float64)
    color_map = plt.get_cmap("tab20")
    for cat_idx, category in enumerate(categories):
        values = np.asarray([values_by_roi[roi][category] for roi in target_rois], dtype=np.float64)
        ax.barh(
            target_rois,
            values,
            left=left,
            label=str(category),
            color=color_map(cat_idx % 20),
            height=0.68,
        )
        left += values
    ax.set_title(title, fontsize=15, weight="bold")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Target ROI")
    ax.set_xlim(0, 1.0)
    ax.grid(axis="x", alpha=0.18)
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=220)
    plt.close(fig)


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    escaped_headers = [_escape_md(str(header)) for header in headers]
    lines = [
        "| " + " | ".join(escaped_headers) + " |",
        "| " + " | ".join("---" for _ in escaped_headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_escape_md(str(value)) for value in row) + " |")
    return "\n".join(lines)


def _escape_md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _relative_link(path: Path, base_dir: Path) -> str:
    return path.relative_to(base_dir).as_posix()


def _top_source_summary(source_rows: Sequence[dict[str, Any]], target_roi: str) -> str:
    roi_rows = [row for row in source_rows if row["target_roi"] == target_roi]
    if not roi_rows:
        return "No source-schema summary available."
    top = roi_rows[0]
    self_row = next((row for row in roi_rows if row["source_schema_roi"] == target_roi), None)
    self_fraction = float(self_row["fraction_of_top_abs_mass"]) if self_row else 0.0
    return (
        f"Top source schema: `{top['source_schema_roi']}` "
        f"({float(top['fraction_of_top_abs_mass']):.1%} of top-|coef| mass); "
        f"self-schema mass: {self_fraction:.1%}."
    )


def _report_lines(
    *,
    output_dir: Path,
    encoding_dir: Path,
    full_run_encoding_dir: Path,
    figures: dict[str, Path],
    performance_rows: Sequence[RoiPerformance],
    top_rois: Sequence[str],
    weights_by_direction: dict[str, dict[str, list[WeightRow]]],
    source_rows: Sequence[dict[str, Any]],
    lag_rows: Sequence[dict[str, Any]],
    examples: Sequence[ExampleRow],
    prediction_sample_ids: Sequence[str],
) -> list[str]:
    """Render the Chinese report body with English plot/table labels."""

    test_episodes = sorted({_episode_from_sample(sample_id) for sample_id in prediction_sample_ids})
    lines = [
        "# Friends round8 encoding interpretability report",
        "",
        "这份报告是当前 round8 `145train_10test` encoding snapshot 的探索性解释分析。"
        "它读取已有 Ridge encoding 输出、ROI schema 和 held-out test split 的 TR-level features，"
        "不重跑 scoring，也不重跑 encoding。",
        "",
        "## Scope",
        "",
        f"- Encoding snapshot: `{encoding_dir.relative_to(REPO_ROOT)}`",
        f"- Schema / manifest source: `{full_run_encoding_dir.relative_to(REPO_ROOT)}`",
        f"- Subject: `sub-01`",
        f"- Test episodes in this snapshot: `{', '.join(test_episodes)}`",
        "- Interpretation target: top 8 ROI by mean test Pearson.",
        "- Weight unit: ROI-averaged standardized Ridge coefficient.",
        "",
        "## Method summary",
        "",
        "- ROI ranking 使用 `group_summary.json` 中的 `mean_subject_mean_test_pearson`。",
        "- 对每个 target ROI，只聚合该 ROI retained parcels 的 Ridge 系数。",
        "- Positive ranking 使用 `mean(coef)`，negative ranking 使用 `mean(coef)` 的最小值，"
        "absolute ranking 使用 `mean(abs(coef))`。",
        "- 每个 feature 都追溯到 `source schema ROI`、`domain`、`dimension_id`、`lag` 和 schema definition。",
        "- Test examples 只从 held-out test split 选择；对于 `lag L` 的 feature，示例文本来自 "
        "`target TR - L` 对应的 source ROI `tr_features.jsonl`。",
        "",
        "## Figures",
        "",
        f"![Round8 ROI Encoding Performance]({_relative_link(figures['performance'], output_dir)})",
        "",
        f"![Top ROI-Averaged Ridge Weights]({_relative_link(figures['heatmap'], output_dir)})",
        "",
        f"![Source Schema Contribution]({_relative_link(figures['source'], output_dir)})",
        "",
        f"![Lag Distribution]({_relative_link(figures['lag'], output_dir)})",
        "",
        "## Overall ROI performance",
        "",
    ]
    lines.append(
        _markdown_table(
            ["Rank", "ROI", "Mean test Pearson", "Median test Pearson", "Retained parcels"],
            [
                [
                    row.rank,
                    row.roi_id,
                    f"{row.mean_test_pearson:.3f}",
                    f"{row.median_test_pearson:.3f}",
                    row.n_retained_parcels,
                ]
                for row in performance_rows
            ],
        )
    )
    lines.extend(
        [
            "",
            "## Top 8 ROI interpretations",
            "",
        ]
    )

    examples_by_roi: dict[str, list[ExampleRow]] = defaultdict(list)
    for example in examples:
        examples_by_roi[example.target_roi].append(example)

    for target_roi in top_rois:
        perf = next(row for row in performance_rows if row.roi_id == target_roi)
        positive = weights_by_direction[target_roi]["positive"][:5]
        negative = weights_by_direction[target_roi]["negative"][:5]
        absolute = weights_by_direction[target_roi]["absolute"][:5]
        top_abs = absolute[0]
        lines.extend(
            [
                f"### {target_roi}",
                "",
                f"- Performance: mean r = `{perf.mean_test_pearson:.3f}`, "
                f"median r = `{perf.median_test_pearson:.3f}`, "
                f"retained parcels = `{perf.n_retained_parcels}`.",
                f"- {_top_source_summary(source_rows, target_roi)}",
                f"- Strongest absolute feature: `{top_abs.source_schema_roi}::{top_abs.dimension_id}` "
                f"(lag {top_abs.lag}, domain `{top_abs.domain}`, "
                f"mean |coef| = {top_abs.mean_abs_coef:.4f}).",
                "",
                "候选解释：这一 ROI 的当前预测权重主要说明哪些 schema feature 在标准化线性模型中有较强预测贡献。"
                "如果 top source schema 不是同名 ROI，应该理解为 cross-schema semantic feature contribution，"
                "而不是脑区间因果影响。",
                "",
                "**Top positive features**",
                "",
            ]
        )
        lines.append(_feature_rows_table(positive))
        lines.extend(["", "**Top negative features**", ""])
        lines.append(_feature_rows_table(negative))
        lines.extend(["", "**Top absolute features**", ""])
        lines.append(_feature_rows_table(absolute))
        roi_examples = examples_by_roi.get(target_roi, [])
        if roi_examples:
            lines.extend(["", "**Representative test examples**", ""])
            lines.append(_examples_table(roi_examples))
        lines.append("")

    lines.extend(
        [
            "## Cross-ROI notes",
            "",
            "- `source schema contribution` 图只统计每个 target ROI 的 top-20 absolute features；"
            "它适合看解释主导来源，不适合当作全特征空间的严格方差分解。",
            "- `lag distribution` 同样基于 top-20 absolute features；当前 lags 为 2-6 TR，"
            "对应约 3.0-8.9 秒的过去语义信息。",
            "- sign consistency 低的 feature 表示它在同一 ROI 的不同 parcels 上方向不一致；"
            "这类 feature 可称为强但异质，不应写成统一的 ROI-level direction。",
            "",
            "## Limitations",
            "",
            "- 当前结果来自 `sub-01` 和尚未 final 的 round8 encoding snapshot；结论应写作候选解释。",
            "- Ridge coefficient 是标准化线性预测权重，不是因果归因。",
            "- 多个 schema feature 可能高度相关，单个 feature 的权重会受共线性和 Ridge regularization 影响。",
            "- 本版按要求未做 permutation importance 或 drop-one ablation；这些应放到 final encoding 稳定后再做。",
            "- cross-schema contribution 表示 feature schema 来源，不表示 source ROI 对 target ROI 的神经因果作用。",
            "",
            "## Output files",
            "",
            "- `tables/roi_performance.csv`",
            "- `tables/top_positive_weights.csv`",
            "- `tables/top_negative_weights.csv`",
            "- `tables/top_absolute_weights.csv`",
            "- `tables/source_schema_contribution.csv`",
            "- `tables/lag_distribution.csv`",
            "- `tables/representative_test_examples.csv`",
            "- `interpretability_summary.json`",
        ]
    )
    return lines


def _feature_rows_table(rows: Sequence[WeightRow]) -> str:
    return _markdown_table(
        ["Rank", "Source schema", "Feature", "Domain", "Lag", "Mean coef", "Mean |coef|", "Sign consistency", "Schema definition"],
        [
            [
                row.rank,
                row.source_schema_roi,
                row.dimension_id,
                row.domain,
                row.lag,
                f"{row.mean_coef:.4f}",
                f"{row.mean_abs_coef:.4f}",
                f"{row.sign_consistency:.2f}",
                _clip_text(row.definition, 130),
            ]
            for row in rows
        ],
    )


def _examples_table(rows: Sequence[ExampleRow]) -> str:
    return _markdown_table(
        ["Direction", "Episode", "Feature", "Lag", "Score", "Error pct", "Time", "Source description"],
        [
            [
                row.direction,
                row.episode_id,
                f"{row.source_schema_roi}::{row.dimension_id}",
                row.lag,
                f"{row.feature_score:.2f}",
                f"{row.local_error_percentile:.1f}",
                (
                    ""
                    if row.tr_start_s is None or row.tr_end_s is None
                    else f"{row.tr_start_s:.1f}-{row.tr_end_s:.1f}s"
                ),
                _clip_text(row.source_description, 180),
            ]
            for row in rows
        ],
    )


def _summary_payload(
    *,
    encoding_dir: Path,
    full_run_encoding_dir: Path,
    output_dir: Path,
    performance_rows: Sequence[RoiPerformance],
    top_rois: Sequence[str],
    source_rows: Sequence[dict[str, Any]],
    lag_rows: Sequence[dict[str, Any]],
    examples: Sequence[ExampleRow],
    heatmap_feature_indices: Sequence[int],
    feature_infos: Sequence[FeatureInfo],
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "encoding_dir": str(encoding_dir.relative_to(REPO_ROOT)),
        "full_run_encoding_dir": str(full_run_encoding_dir.relative_to(REPO_ROOT)),
        "output_dir": str(output_dir.relative_to(REPO_ROOT)),
        "top_roi_count": TOP_ROI_COUNT,
        "top_rois": list(top_rois),
        "performance": _performance_csv_rows(performance_rows),
        "source_schema_contribution": list(source_rows),
        "lag_distribution": list(lag_rows),
        "representative_test_examples": [_example_to_dict(row) for row in examples],
        "heatmap_features": [
            {
                "feature_index": int(idx),
                "expanded_feature_name": feature_infos[int(idx)].expanded_feature_name,
                "source_schema_roi": feature_infos[int(idx)].source_schema_roi,
                "dimension_id": feature_infos[int(idx)].dimension_id,
                "lag": feature_infos[int(idx)].lag,
                "domain": feature_infos[int(idx)].domain,
            }
            for idx in heatmap_feature_indices
        ],
        "notes": [
            "Exploratory report for non-final round8 encoding.",
            "Ridge coefficients are standardized linear prediction weights, not causal effects.",
            "Cross-schema contribution refers to feature schema source, not neural causal influence.",
        ],
    }


def _build_report(args: Namespace) -> None:
    encoding_dir = _repo_path(args.encoding_dir)
    full_run_encoding_dir = _repo_path(args.full_run_encoding_dir)
    output_dir = _repo_path(args.output_dir)
    figures_dir = output_dir / "figures"
    tables_dir = output_dir / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    coefficient_data = np.load(encoding_dir / "sub-01" / "ridge_coefficients.npz", allow_pickle=True)
    prediction_npz = np.load(encoding_dir / "sub-01" / "test_predictions.npz", allow_pickle=True)
    prediction_data = {key: prediction_npz[key] for key in prediction_npz.files}

    coef = coefficient_data["coef"].astype(np.float64)
    memberships = coefficient_data["parcel_roi_memberships"]
    feature_infos = _load_feature_infos(
        [str(value) for value in coefficient_data["expanded_feature_names"]],
        _load_dimension_lookup(full_run_encoding_dir / "roi_schemas.json"),
    )
    performance_rows = _load_performance(encoding_dir / "group_summary.json")
    top_rois = [row.roi_id for row in performance_rows[: args.top_roi_count]]
    top_roi_set = set(top_rois)

    weights_by_direction: dict[str, dict[str, list[WeightRow]]] = {}
    for roi in top_rois:
        weights_by_direction[roi] = {
            direction: _weight_rows_for_roi(
                target_roi=roi,
                coef=coef,
                memberships=memberships,
                feature_infos=feature_infos,
                direction=direction,
                top_n=args.top_feature_rows,
            )
            for direction in ("positive", "negative", "absolute")
        }

    source_rows, lag_rows = _contribution_rows(
        target_rois=top_rois,
        coef=coef,
        memberships=memberships,
        feature_infos=feature_infos,
    )
    examples = _example_rows(
        target_rois=top_rois,
        weight_rows_by_direction=weights_by_direction,
        feature_infos=feature_infos,
        manifest_path=full_run_encoding_dir / "roi_encoding_manifest.jsonl",
        prediction_data=prediction_data,
        memberships=memberships,
    )

    _write_csv(
        tables_dir / "roi_performance.csv",
        _performance_csv_rows(performance_rows),
        [
            "rank",
            "roi_id",
            "mean_test_pearson",
            "median_test_pearson",
            "n_retained_parcels",
            "n_total_selected_parcels",
        ],
    )
    weight_fields = list(_weight_row_to_dict(weights_by_direction[top_rois[0]]["positive"][0]).keys())
    for direction in ("positive", "negative", "absolute"):
        rows = [
            _weight_row_to_dict(row)
            for roi in top_rois
            for row in weights_by_direction[roi][direction]
        ]
        _write_csv(tables_dir / f"top_{direction}_weights.csv", rows, weight_fields)
    _write_csv(
        tables_dir / "source_schema_contribution.csv",
        list(source_rows),
        [
            "target_roi",
            "source_schema_roi",
            "top_feature_count",
            "mean_abs_coef_mass",
            "fraction_of_top_abs_mass",
            "self_schema",
            "top_n_features",
        ],
    )
    _write_csv(
        tables_dir / "lag_distribution.csv",
        list(lag_rows),
        [
            "target_roi",
            "lag",
            "top_feature_count",
            "mean_abs_coef_mass",
            "fraction_of_top_abs_mass",
            "top_n_features",
        ],
    )
    _write_csv(
        tables_dir / "representative_test_examples.csv",
        [_example_to_dict(row) for row in examples],
        [
            "target_roi",
            "direction",
            "source_schema_roi",
            "dimension_id",
            "domain",
            "lag",
            "episode_id",
            "sample_id",
            "target_tr_index",
            "feature_tr_index",
            "feature_score",
            "local_mean_abs_error",
            "local_error_percentile",
            "tr_start_s",
            "tr_end_s",
            "source_description",
            "definition",
        ],
    )

    figures = {
        "performance": figures_dir / "roi_performance_bar.png",
        "heatmap": figures_dir / "top8_feature_weight_heatmap.png",
        "source": figures_dir / "source_schema_contribution.png",
        "lag": figures_dir / "lag_distribution.png",
    }
    _plot_performance(figures["performance"], performance_rows, top_roi_set)
    heatmap_feature_indices = _plot_heatmap(
        figures["heatmap"],
        target_rois=top_rois,
        coef=coef,
        memberships=memberships,
        feature_infos=feature_infos,
    )
    _plot_stacked_bar(
        figures["source"],
        rows=source_rows,
        target_rois=top_rois,
        category_field="source_schema_roi",
        value_field="fraction_of_top_abs_mass",
        title="Source Schema Contribution in Top Absolute Weights",
        xlabel="Fraction of top-20 |coef| mass",
    )
    _plot_stacked_bar(
        figures["lag"],
        rows=lag_rows,
        target_rois=top_rois,
        category_field="lag",
        value_field="fraction_of_top_abs_mass",
        title="Lag Distribution in Top Absolute Weights",
        xlabel="Fraction of top-20 |coef| mass",
    )

    report_lines = _report_lines(
        output_dir=output_dir,
        encoding_dir=encoding_dir,
        full_run_encoding_dir=full_run_encoding_dir,
        figures=figures,
        performance_rows=performance_rows,
        top_rois=top_rois,
        weights_by_direction=weights_by_direction,
        source_rows=source_rows,
        lag_rows=lag_rows,
        examples=examples,
        prediction_sample_ids=[str(value) for value in prediction_data["sample_ids"]],
    )
    report_path = output_dir / "interpretability_report.md"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    _write_json(
        output_dir / "interpretability_summary.json",
        _summary_payload(
            encoding_dir=encoding_dir,
            full_run_encoding_dir=full_run_encoding_dir,
            output_dir=output_dir,
            performance_rows=performance_rows,
            top_rois=top_rois,
            source_rows=source_rows,
            lag_rows=lag_rows,
            examples=examples,
            heatmap_feature_indices=heatmap_feature_indices,
            feature_infos=feature_infos,
        ),
    )

    print(f"Wrote report to {report_path.relative_to(REPO_ROOT)}")
    print(f"Wrote figures to {figures_dir.relative_to(REPO_ROOT)}")
    print(f"Wrote tables to {tables_dir.relative_to(REPO_ROOT)}")


def _parse_args() -> Namespace:
    parser = ArgumentParser(
        description=textwrap.dedent(
            """\
            Generate an exploratory interpretability report for the Friends
            round8 145-train 10-test encoding snapshot.
            """
        )
    )
    parser.add_argument("--encoding-dir", default=str(DEFAULT_ENCODING_DIR.relative_to(REPO_ROOT)))
    parser.add_argument(
        "--full-run-encoding-dir",
        default=str(DEFAULT_FULL_RUN_ENCODING_DIR.relative_to(REPO_ROOT)),
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR.relative_to(REPO_ROOT)))
    parser.add_argument("--top-roi-count", type=int, default=TOP_ROI_COUNT)
    parser.add_argument("--top-feature-rows", type=int, default=TOP_FEATURE_ROWS)
    args = parser.parse_args()
    if args.top_roi_count < 1:
        raise ValueError("--top-roi-count must be positive.")
    if args.top_feature_rows < 1:
        raise ValueError("--top-feature-rows must be positive.")
    return args


def main() -> None:
    _build_report(_parse_args())


if __name__ == "__main__":
    main()
