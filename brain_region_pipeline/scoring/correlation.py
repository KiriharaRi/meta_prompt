"""Pearson correlation helpers for segment scores and GT segment means."""

from __future__ import annotations

import json
import math
from bisect import bisect_right
from pathlib import Path
from typing import Any

from ..core.io_utils import write_json


def _read_row_records(path: str | Path) -> list[dict[str, Any]]:
    """Read row records from JSONL, JSON arrays, or JSON objects with rows."""

    text = Path(path).read_text(encoding="utf-8")
    stripped = text.lstrip()
    if not stripped:
        return []
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(payload, list):
                return [dict(row) for row in payload]
            if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
                return [dict(row) for row in payload["rows"]]
            raise ValueError(f"JSON input must be a list or an object with rows: {path}")
    return [
        json.loads(line)
        for line in text.splitlines()
        if line.strip()
    ]


def _score_time(row: dict[str, Any]) -> float:
    """Return one score segment's midpoint time in seconds."""

    return (float(row["start_s"]) + float(row["end_s"])) / 2.0


def _gt_windows(gt_rows: list[dict[str, Any]]) -> tuple[list[float], list[float]]:
    """Return GT start and end arrays used for lagged time lookup."""

    starts = [float(row["start_seconds"]) for row in gt_rows]
    ends = [float(row["end_seconds"]) for row in gt_rows]
    return starts, ends


def _gt_index_at(
    time_s: float,
    starts: list[float],
    ends: list[float],
) -> int | None:
    """Find the GT segment containing a shifted feature time."""

    idx = bisect_right(starts, time_s) - 1
    if idx < 0 or idx >= len(starts):
        return None
    if starts[idx] <= time_s < ends[idx]:
        return idx
    if idx == len(starts) - 1 and time_s == ends[idx]:
        return idx
    return None


def _dimension_ids(score_rows: list[dict[str, Any]]) -> list[str]:
    """Return stable dimension ids from the first score row."""

    if not score_rows:
        return []
    scores = score_rows[0].get("dimension_scores")
    if not isinstance(scores, dict):
        raise ValueError("Score rows must contain dimension_scores objects.")
    return list(scores)


def _pearson(x_values: list[float], y_values: list[float]) -> float | None:
    """Compute Pearson r, returning None when correlation is undefined."""

    if len(x_values) != len(y_values):
        raise ValueError("Pearson inputs must have the same length.")
    valid_pairs = [
        (float(x), float(y))
        for x, y in zip(x_values, y_values, strict=True)
        if math.isfinite(float(x)) and math.isfinite(float(y))
    ]
    if len(valid_pairs) < 3:
        return None
    xs = [x for x, _ in valid_pairs]
    ys = [y for _, y in valid_pairs]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    centered_x = [x - x_mean for x in xs]
    centered_y = [y - y_mean for y in ys]
    numerator = sum(x * y for x, y in zip(centered_x, centered_y, strict=True))
    x_ss = sum(x * x for x in centered_x)
    y_ss = sum(y * y for y in centered_y)
    if x_ss == 0 or y_ss == 0:
        return None
    return numerator / math.sqrt(x_ss * y_ss)


def _sort_key(row: dict[str, Any]) -> tuple[bool, float]:
    """Sort rows by Pearson descending, with undefined values last."""

    pearson = row.get("pearson")
    return pearson is not None, float(pearson or 0.0)


def compute_score_correlations(
    *,
    score_rows: list[dict[str, Any]],
    gt_rows: list[dict[str, Any]],
    target_emotion: str,
    lag_s: float,
) -> list[dict[str, Any]]:
    """Compute per-dimension Pearson r between segment scores and GT.

    The lag convention is feature-at-time ``t`` compared with GT at
    ``t + lag_s``. Pairs whose shifted time falls outside the GT segment
    coverage are omitted. Undefined correlations, such as all-zero dimensions,
    are represented as ``None``.
    """

    if not score_rows:
        raise ValueError("Score input contains no rows.")
    if not gt_rows:
        raise ValueError("GT input contains no rows.")
    starts, ends = _gt_windows(gt_rows)
    dimensions = _dimension_ids(score_rows)
    rows: list[dict[str, Any]] = []
    for dimension_id in dimensions:
        x_values: list[float] = []
        y_values: list[float] = []
        nonzero = 0
        for score_row in score_rows:
            raw_scores = score_row.get("dimension_scores", {})
            if dimension_id not in raw_scores:
                continue
            score = float(raw_scores[dimension_id])
            nonzero += int(score != 0)
            gt_idx = _gt_index_at(_score_time(score_row) + lag_s, starts, ends)
            if gt_idx is None:
                continue
            gt_emotions = gt_rows[gt_idx].get("gt_emotions", {})
            if target_emotion not in gt_emotions:
                continue
            x_values.append(score)
            y_values.append(float(gt_emotions[target_emotion]))
        rows.append(
            {
                "dimension": dimension_id,
                "pearson": _pearson(x_values, y_values),
                "n": len(x_values),
                "nonzero": nonzero,
            },
        )
    return sorted(rows, key=_sort_key, reverse=True)


def build_correlation_payload(
    *,
    scores_path: str | Path,
    gt_path: str | Path,
    target_emotion: str,
    lag_s: float,
) -> dict[str, Any]:
    """Load score/GT files and build the serialized Pearson output."""

    score_rows = _read_row_records(scores_path)
    gt_rows = _read_row_records(gt_path)
    return {
        "target": target_emotion,
        "lag_s": lag_s,
        "lag_definition": "feature score at time t is compared with GT at t + lag_s",
        "source_scores": str(scores_path),
        "source_gt": str(gt_path),
        "rows": compute_score_correlations(
            score_rows=score_rows,
            gt_rows=gt_rows,
            target_emotion=target_emotion,
            lag_s=lag_s,
        ),
    }


def write_score_correlations(
    *,
    scores_path: str | Path,
    gt_path: str | Path,
    target_emotion: str,
    lag_s: float,
    output_file: str | Path,
) -> dict[str, Any]:
    """Write Pearson correlations to JSON and print a compact CLI summary."""

    payload = build_correlation_payload(
        scores_path=scores_path,
        gt_path=gt_path,
        target_emotion=target_emotion,
        lag_s=lag_s,
    )
    write_json(output_file, payload)
    print(f"Wrote Pearson correlations to {output_file}")
    print("| rank | dimension | Pearson r | n | nonzero |")
    print("|---:|---|---:|---:|---:|")
    for rank, row in enumerate(payload["rows"], start=1):
        pearson = row["pearson"]
        pearson_text = "NA" if pearson is None else f"{pearson:.3f}"
        print(
            "| "
            f"{rank} | `{row['dimension']}` | {pearson_text} | "
            f"{row['n']} | {row['nonzero']} |",
        )
    return payload
