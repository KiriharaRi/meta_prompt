"""Feature-matrix construction for Ridge encoding."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from numpy.typing import NDArray

from ..core.io_utils import read_jsonl


@dataclass(frozen=True)
class LaggedSample:
    """Lag-expanded feature and target matrices for one manifest sample."""

    sample_id: str
    subject_id: str
    split: str
    x: NDArray[np.float64]
    y: NDArray[np.float64]
    feature_tr_indices: NDArray[np.int64]
    fmri_tr_indices: NDArray[np.int64]


@dataclass(frozen=True)
class RawTrAlignedMatrices:
    """Feature and fMRI matrices aligned on the same raw TR interval."""

    x: NDArray[np.float64]
    y: NDArray[np.float64]
    feature_start_tr: int
    fmri_start_tr: int


def load_tr_feature_matrix(
    path: str | Path,
    feature_names: Sequence[str],
) -> NDArray[np.float64]:
    """Read ``tr_features.jsonl`` into a numeric TR x feature matrix."""

    rows = read_jsonl(path)
    if not rows:
        raise ValueError(f"TR feature file contains no rows: {path}")
    vectors: list[list[float]] = []
    expected_len = len(feature_names)
    for row_idx, row in enumerate(rows, start=1):
        vector = row.get("feature_vector")
        if not isinstance(vector, list):
            raise ValueError(f"{path}: row {row_idx} missing feature_vector list.")
        if len(vector) != expected_len:
            raise ValueError(
                f"{path}: row {row_idx} feature_vector has length {len(vector)}, "
                f"expected {expected_len} from region schema.",
            )
        vectors.append([float(value) for value in vector])
    return np.asarray(vectors, dtype=np.float64)


def _trim_interval(
    n_rows: int,
    *,
    start_tr: int,
    end_tr: int,
    label: str,
) -> tuple[int, int]:
    """Return the half-open raw TR interval left after explicit trimming."""

    if start_tr < 0 or end_tr < 0:
        raise ValueError(f"{label}: trim counts must be non-negative.")
    end_index = n_rows - end_tr if end_tr else n_rows
    if start_tr >= end_index:
        raise ValueError(
            f"{label}: trimming removes all rows "
            f"(n={n_rows}, start={start_tr}, end={end_tr}).",
        )
    return start_tr, end_index


def trim_matrix(
    matrix: NDArray[np.float64],
    *,
    start_tr: int,
    end_tr: int,
    label: str,
) -> NDArray[np.float64]:
    """Apply explicit manifest trimming to a TR x column matrix."""

    start_index, end_index = _trim_interval(
        matrix.shape[0],
        start_tr=start_tr,
        end_tr=end_tr,
        label=label,
    )
    return matrix[start_index:end_index, :]


def align_feature_matrix_to_trimmed_fmri(
    *,
    sample_id: str,
    x_raw: NDArray[np.float64],
    y_raw: NDArray[np.float64],
    feature_trim_start_tr: int,
    feature_trim_end_tr: int,
    fmri_trim_start_tr: int,
    fmri_trim_end_tr: int,
) -> RawTrAlignedMatrices:
    """Align features to the raw TR interval retained after fMRI trimming.

    Scoring can produce fewer feature rows than the corresponding H5 dataset
    when descriptions stop before the episode tail. Encoding therefore treats
    the fMRI trim interval as authoritative and slices features by the same raw
    TR indices. Longer feature files are truncated; shorter feature coverage is
    a hard error so callers do not silently reuse stale scores.
    """

    feature_start, feature_end = _trim_interval(
        x_raw.shape[0],
        start_tr=feature_trim_start_tr,
        end_tr=feature_trim_end_tr,
        label=f"{sample_id} ROI features",
    )
    fmri_start, fmri_end = _trim_interval(
        y_raw.shape[0],
        start_tr=fmri_trim_start_tr,
        end_tr=fmri_trim_end_tr,
        label=f"{sample_id} fMRI",
    )

    if feature_start > fmri_start:
        raise ValueError(
            f"Sample {sample_id!r}: feature rows cover raw TR "
            f"[{feature_start}, {feature_end}), but trimmed fMRI requires "
            f"[{fmri_start}, {fmri_end}). Set fmri_trim_start_tr to at least "
            f"{feature_start}, or decrease feature_trim_start_tr.",
        )
    if feature_end < fmri_end:
        suggested_end_trim = max(y_raw.shape[0] - feature_end, 0)
        raise ValueError(
            f"Sample {sample_id!r}: feature rows cover raw TR "
            f"[{feature_start}, {feature_end}), but trimmed fMRI requires "
            f"[{fmri_start}, {fmri_end}). Set fmri_trim_end_tr to at least "
            f"{suggested_end_trim}, or regenerate/fix the feature file.",
        )

    return RawTrAlignedMatrices(
        x=x_raw[fmri_start:fmri_end, :].astype(np.float64),
        y=y_raw[fmri_start:fmri_end, :].astype(np.float64),
        feature_start_tr=fmri_start,
        fmri_start_tr=fmri_start,
    )


def expanded_feature_names(
    base_feature_names: Sequence[str],
    lags: Sequence[int],
) -> list[str]:
    """Return feature names after lag expansion."""

    return [
        f"{feature_name}_lag{lag}"
        for lag in lags
        for feature_name in base_feature_names
    ]


def build_lagged_sample(
    *,
    sample_id: str,
    subject_id: str,
    split: str,
    x_raw: NDArray[np.float64],
    y_raw: NDArray[np.float64],
    lags: Sequence[int],
    feature_start_tr: int,
    fmri_start_tr: int,
) -> LaggedSample:
    """Build a lagged design matrix aligned to current-TR fMRI targets."""

    if x_raw.shape[0] != y_raw.shape[0]:
        raise ValueError(
            f"Sample {sample_id!r}: feature and fMRI lengths must match before "
            f"lagging, got {x_raw.shape[0]} and {y_raw.shape[0]}.",
        )
    if not lags:
        raise ValueError("At least one lag is required.")
    if any(lag < 0 for lag in lags):
        raise ValueError(f"Lags must be non-negative, got {list(lags)}.")
    max_lag = max(lags)
    if x_raw.shape[0] <= max_lag:
        raise ValueError(
            f"Sample {sample_id!r}: {x_raw.shape[0]} TRs are insufficient for "
            f"max lag {max_lag}.",
        )
    rows: list[NDArray[np.float64]] = []
    for tr_idx in range(max_lag, x_raw.shape[0]):
        # The lagged row uses past feature values to predict current fMRI.
        rows.append(np.concatenate([x_raw[tr_idx - lag, :] for lag in lags]))
    target_indices = np.arange(max_lag, x_raw.shape[0], dtype=np.int64)
    return LaggedSample(
        sample_id=sample_id,
        subject_id=subject_id,
        split=split,
        x=np.vstack(rows).astype(np.float64),
        y=y_raw[max_lag:, :].astype(np.float64),
        feature_tr_indices=target_indices + feature_start_tr,
        fmri_tr_indices=target_indices + fmri_start_tr,
    )
