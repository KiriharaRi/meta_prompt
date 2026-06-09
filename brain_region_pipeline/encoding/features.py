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


def trim_matrix(
    matrix: NDArray[np.float64],
    *,
    start_tr: int,
    end_tr: int,
    label: str,
) -> NDArray[np.float64]:
    """Apply explicit manifest trimming to a TR x column matrix."""

    if start_tr < 0 or end_tr < 0:
        raise ValueError(f"{label}: trim counts must be non-negative.")
    end_index = matrix.shape[0] - end_tr if end_tr else matrix.shape[0]
    if start_tr >= end_index:
        raise ValueError(
            f"{label}: trimming removes all rows "
            f"(n={matrix.shape[0]}, start={start_tr}, end={end_tr}).",
        )
    return matrix[start_tr:end_index, :]


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
