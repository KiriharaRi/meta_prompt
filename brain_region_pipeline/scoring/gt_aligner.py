"""Ground-truth CSV averaging onto dense-description segments."""

from __future__ import annotations

import csv
import glob
import os
from bisect import bisect_left
from pathlib import Path
from typing import Any

from .models import DescriptionSegment

EMOTION_MAPPING_ZH = {
    "焦虑": "agitation",
    "愉悦": "amusement",
    "悲伤": "sadness",
    "不适": "uneasiness",
    "困惑": "confusion",
}


def extract_emotion_from_filename(filename: str) -> str:
    """Infer the emotion label from the notebook-style CSV filename."""

    stem = Path(filename).stem
    parts = stem.split("_")
    if len(parts) >= 2 and parts[1] in EMOTION_MAPPING_ZH:
        return EMOTION_MAPPING_ZH[parts[1]]
    for emotion_zh, emotion_en in EMOTION_MAPPING_ZH.items():
        if emotion_zh in filename:
            return emotion_en
    return ""


def _timestamp_label(segment: DescriptionSegment) -> str:
    """Render a stable segment timestamp label."""

    start_min, start_s = int(segment.start_s // 60), int(segment.start_s % 60)
    end_min, end_s = int(segment.end_s // 60), int(segment.end_s % 60)
    return f"{start_min:02d}:{start_s:02d} - {end_min:02d}:{end_s:02d}"


def _read_subject_csv(
    path: str | Path,
    *,
    time_column: str,
    emotion_column: str,
) -> list[tuple[float, float]]:
    """Read one subject CSV as sorted ``(time_seconds, emotion_value)`` rows."""

    rows: list[tuple[float, float]] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or time_column not in reader.fieldnames:
            raise ValueError(f"CSV missing time column {time_column!r}: {path}")
        if emotion_column not in reader.fieldnames:
            raise ValueError(f"CSV missing emotion column {emotion_column!r}: {path}")
        for row in reader:
            rows.append((float(row[time_column]), float(row[emotion_column])))
    return sorted(rows, key=lambda item: item[0])


def _nearest_value(rows: list[tuple[float, float]], time_s: float) -> float:
    """Return the value nearest to ``time_s`` from sorted subject rows."""

    if not rows:
        return 0.0
    times = [time for time, _ in rows]
    pos = bisect_left(times, time_s)
    if pos == 0:
        return rows[0][1]
    if pos >= len(rows):
        return rows[-1][1]
    before = rows[pos - 1]
    after = rows[pos]
    if abs(before[0] - time_s) <= abs(after[0] - time_s):
        return before[1]
    return after[1]


def _average_subjects(subject_rows: list[list[tuple[float, float]]]) -> list[tuple[float, float]]:
    """Replicate the notebook's nearest-time cross-subject averaging."""

    all_times = sorted({time for rows in subject_rows for time, _ in rows})
    averaged: list[tuple[float, float]] = []
    for time_s in all_times:
        values = [_nearest_value(rows, time_s) for rows in subject_rows]
        averaged.append((time_s, sum(values) / len(values)))
    return averaged


def load_averaged_gt_csvs(
    gt_dir: str | Path,
    *,
    file_pattern: str = "*.csv",
    time_column: str = "视频时间(s)",
    emotion_column: str = "情绪值",
) -> tuple[dict[str, list[tuple[float, float]]], dict[str, Any]]:
    """Load GT CSVs and average subjects per emotion before segment resampling."""

    if not Path(gt_dir).is_dir():
        raise ValueError(f"GT directory does not exist: {gt_dir}")
    grouped: dict[str, list[list[tuple[float, float]]]] = {}
    skipped_files: list[dict[str, str]] = []
    for csv_file in sorted(glob.glob(os.path.join(str(gt_dir), file_pattern))):
        filename = os.path.basename(csv_file)
        emotion = extract_emotion_from_filename(filename)
        if not emotion:
            skipped_files.append({"file": filename, "reason": "unknown_emotion"})
            continue
        try:
            grouped.setdefault(emotion, []).append(
                _read_subject_csv(
                    csv_file,
                    time_column=time_column,
                    emotion_column=emotion_column,
                ),
            )
        except Exception as exc:
            skipped_files.append({"file": filename, "reason": str(exc)})

    if not grouped:
        raise ValueError(f"No usable GT CSV files found in {gt_dir}")

    averaged = {
        emotion: _average_subjects(rows)
        for emotion, rows in grouped.items()
    }
    metadata = {
        "gt_dir": str(gt_dir),
        "file_pattern": file_pattern,
        "time_column": time_column,
        "emotion_column": emotion_column,
        "subject_counts": {
            emotion: len(rows)
            for emotion, rows in grouped.items()
        },
        "time_point_counts": {
            emotion: len(rows)
            for emotion, rows in averaged.items()
        },
        "skipped_files": skipped_files,
    }
    return averaged, metadata


def average_gt_to_segments(
    segments: list[DescriptionSegment],
    gt_by_emotion: dict[str, list[tuple[float, float]]],
) -> list[dict[str, Any]]:
    """Average time-series GT values over each description segment interval."""

    rows: list[dict[str, Any]] = []
    for segment_id, segment in enumerate(segments):
        emotion_values: dict[str, float] = {}
        point_counts: dict[str, int] = {}
        for emotion, gt_rows in gt_by_emotion.items():
            values = [
                value
                for time_s, value in gt_rows
                if segment.start_s <= time_s < segment.end_s
            ]
            point_counts[emotion] = len(values)
            emotion_values[emotion] = sum(values) / len(values) if values else 0.0
        rows.append(
            {
                "segment_id": segment_id,
                "start_seconds": segment.start_s,
                "end_seconds": segment.end_s,
                "timestamp_str": _timestamp_label(segment),
                "gt_emotions": emotion_values,
                "point_counts": point_counts,
            },
        )
    return rows
