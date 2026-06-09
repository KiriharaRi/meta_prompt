"""Manifest contract for unified ROI Ridge encoding samples."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VALID_SPLITS = {"train", "val", "test"}
REQUIRED_FIELDS = (
    "sample_id",
    "subject_id",
    "feature_set_name",
    "split",
    "roi_features",
    "h5_file",
    "h5_dataset",
)


@dataclass(frozen=True)
class RoiEncodingManifestEntry:
    """One sample row linking one or more ROI feature files to one H5 dataset."""

    sample_id: str
    subject_id: str
    feature_set_name: str
    split: str
    roi_features: dict[str, Path]
    h5_file: Path
    h5_dataset: str
    feature_trim_start_tr: int = 0
    feature_trim_end_tr: int = 0
    fmri_trim_start_tr: int = 0
    fmri_trim_end_tr: int = 0
    line_number: int = 0

    def to_metadata(self) -> dict[str, Any]:
        """Serialize this manifest row for run metadata."""

        return {
            "sample_id": self.sample_id,
            "subject_id": self.subject_id,
            "feature_set_name": self.feature_set_name,
            "split": self.split,
            "roi_features": {
                roi_id: str(path)
                for roi_id, path in sorted(self.roi_features.items())
            },
            "h5_file": str(self.h5_file),
            "h5_dataset": self.h5_dataset,
            "feature_trim_start_tr": self.feature_trim_start_tr,
            "feature_trim_end_tr": self.feature_trim_end_tr,
            "fmri_trim_start_tr": self.fmri_trim_start_tr,
            "fmri_trim_end_tr": self.fmri_trim_end_tr,
            "line_number": self.line_number,
        }


def _resolve_path(raw_path: str, manifest_dir: Path) -> Path:
    """Resolve manifest-relative paths without requiring files to exist yet."""

    path = Path(raw_path)
    if path.is_absolute():
        return path
    return manifest_dir / path


def _required_str(data: dict[str, Any], field: str, line_number: int) -> str:
    """Read a required non-empty string field from one manifest row."""

    if field not in data:
        raise ValueError(f"Manifest line {line_number}: missing required field {field!r}.")
    value = str(data[field]).strip()
    if not value:
        raise ValueError(f"Manifest line {line_number}: field {field!r} cannot be empty.")
    return value


def _nonnegative_int(data: dict[str, Any], field: str, line_number: int) -> int:
    """Read a non-negative trim count, defaulting to zero."""

    value = int(data.get(field, 0))
    if value < 0:
        raise ValueError(f"Manifest line {line_number}: {field!r} must be non-negative.")
    return value


def _roi_features(
    data: dict[str, Any],
    *,
    manifest_dir: Path,
    line_number: int,
) -> dict[str, Path]:
    """Read and normalize the ROI feature mapping for one row."""

    raw = data.get("roi_features")
    if not isinstance(raw, dict) or not raw:
        raise ValueError(
            f"Manifest line {line_number}: 'roi_features' must be a non-empty object.",
        )
    features: dict[str, Path] = {}
    for roi_id, raw_path in raw.items():
        key = str(roi_id).strip()
        if not key:
            raise ValueError(f"Manifest line {line_number}: ROI ids cannot be empty.")
        value = str(raw_path).strip()
        if not value:
            raise ValueError(
                f"Manifest line {line_number}: feature path for ROI {key!r} is empty.",
            )
        features[key] = _resolve_path(value, manifest_dir)
    return features


def _entry_from_payload(
    payload: dict[str, Any],
    *,
    manifest_dir: Path,
    line_number: int,
) -> RoiEncodingManifestEntry:
    """Validate and normalize one manifest JSON object."""

    for field in REQUIRED_FIELDS:
        _required_str(payload, field, line_number)
    split = _required_str(payload, "split", line_number)
    if split not in VALID_SPLITS:
        raise ValueError(
            f"Manifest line {line_number}: split must be one of "
            f"{sorted(VALID_SPLITS)}, got {split!r}.",
        )
    return RoiEncodingManifestEntry(
        sample_id=_required_str(payload, "sample_id", line_number),
        subject_id=_required_str(payload, "subject_id", line_number),
        feature_set_name=_required_str(payload, "feature_set_name", line_number),
        split=split,
        roi_features=_roi_features(
            payload,
            manifest_dir=manifest_dir,
            line_number=line_number,
        ),
        h5_file=_resolve_path(_required_str(payload, "h5_file", line_number), manifest_dir),
        h5_dataset=_required_str(payload, "h5_dataset", line_number),
        feature_trim_start_tr=_nonnegative_int(payload, "feature_trim_start_tr", line_number),
        feature_trim_end_tr=_nonnegative_int(payload, "feature_trim_end_tr", line_number),
        fmri_trim_start_tr=_nonnegative_int(payload, "fmri_trim_start_tr", line_number),
        fmri_trim_end_tr=_nonnegative_int(payload, "fmri_trim_end_tr", line_number),
        line_number=line_number,
    )


def load_roi_encoding_manifest(path: str | Path) -> list[RoiEncodingManifestEntry]:
    """Load and validate a unified ROI JSONL encoding manifest."""

    manifest_path = Path(path)
    manifest_dir = manifest_path.parent
    entries: list[RoiEncodingManifestEntry] = []
    seen_sample_ids: set[str] = set()
    with manifest_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Manifest line {line_number}: invalid JSON: {exc.msg}",
                ) from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Manifest line {line_number}: row must be a JSON object.")
            entry = _entry_from_payload(
                payload,
                manifest_dir=manifest_dir,
                line_number=line_number,
            )
            if entry.sample_id in seen_sample_ids:
                raise ValueError(
                    f"Manifest line {line_number}: duplicate sample_id "
                    f"{entry.sample_id!r}.",
                )
            seen_sample_ids.add(entry.sample_id)
            entries.append(entry)

    if not entries:
        raise ValueError(f"ROI encoding manifest contains no samples: {manifest_path}")
    feature_sets = {entry.feature_set_name for entry in entries}
    if len(feature_sets) != 1:
        raise ValueError(
            "ROI encoding runs must contain exactly one feature_set_name; "
            f"got {sorted(feature_sets)}.",
        )
    roi_sets = {tuple(sorted(entry.roi_features)) for entry in entries}
    if len(roi_sets) != 1:
        raise ValueError("Every ROI encoding manifest row must contain the same ROI ids.")
    return entries
