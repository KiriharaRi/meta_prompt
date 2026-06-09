"""Ridge encoding model fitting and evaluation utilities."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from numpy.typing import NDArray
from sklearn.linear_model import Ridge


STD_EPSILON = 1e-12


@dataclass(frozen=True)
class MatrixStandardizer:
    """Train-fitted z-score transform with constant-column dropping."""

    mean: NDArray[np.float64]
    scale: NDArray[np.float64]
    keep_indices: NDArray[np.int64]
    dropped_indices: NDArray[np.int64]

    @classmethod
    def fit(cls, matrix: NDArray[np.float64]) -> "MatrixStandardizer":
        """Fit z-score parameters on a training matrix."""

        mean = matrix.mean(axis=0)
        scale = matrix.std(axis=0)
        keep = np.where(scale > STD_EPSILON)[0].astype(np.int64)
        dropped = np.where(scale <= STD_EPSILON)[0].astype(np.int64)
        if keep.size == 0:
            raise ValueError("All matrix columns are constant in the training split.")
        return cls(
            mean=mean.astype(np.float64),
            scale=scale.astype(np.float64),
            keep_indices=keep,
            dropped_indices=dropped,
        )

    def transform(self, matrix: NDArray[np.float64]) -> NDArray[np.float64]:
        """Apply train-fitted z-score parameters and keep non-constant columns."""

        safe_scale = self.scale.copy()
        # Constant columns are dropped after transform; use a neutral scale here
        # so validation runs do not emit divide-by-zero warnings.
        safe_scale[self.dropped_indices] = 1.0
        standardized = (matrix - self.mean) / safe_scale
        return standardized[:, self.keep_indices]

    def inverse_transform_kept(self, matrix: NDArray[np.float64]) -> NDArray[np.float64]:
        """Map standardized kept columns back into the original value scale."""

        return (
            matrix * self.scale[self.keep_indices]
            + self.mean[self.keep_indices]
        )


def pearson_1d(x_values: NDArray[np.float64], y_values: NDArray[np.float64]) -> float | None:
    """Compute Pearson r for one target column."""

    valid = np.isfinite(x_values) & np.isfinite(y_values)
    if int(valid.sum()) < 3:
        return None
    xs = x_values[valid]
    ys = y_values[valid]
    x_centered = xs - xs.mean()
    y_centered = ys - ys.mean()
    denominator = math.sqrt(float(np.dot(x_centered, x_centered) * np.dot(y_centered, y_centered)))
    if denominator == 0:
        return None
    return float(np.dot(x_centered, y_centered) / denominator)


def r2_1d(y_true: NDArray[np.float64], y_pred: NDArray[np.float64]) -> float | None:
    """Compute R squared for one target column."""

    valid = np.isfinite(y_true) & np.isfinite(y_pred)
    if int(valid.sum()) < 2:
        return None
    truth = y_true[valid]
    pred = y_pred[valid]
    centered = truth - truth.mean()
    ss_total = float(np.dot(centered, centered))
    if ss_total == 0:
        return None
    residual = truth - pred
    return float(1.0 - np.dot(residual, residual) / ss_total)


def mean_finite(values: Sequence[float | None]) -> float | None:
    """Average finite values, returning None when no value is defined."""

    finite = [float(value) for value in values if value is not None and math.isfinite(value)]
    if not finite:
        return None
    return float(sum(finite) / len(finite))


def median_finite(values: Sequence[float | None]) -> float | None:
    """Median of finite values, returning None when no value is defined."""

    finite = sorted(float(value) for value in values if value is not None and math.isfinite(value))
    if not finite:
        return None
    mid = len(finite) // 2
    if len(finite) % 2:
        return float(finite[mid])
    return float((finite[mid - 1] + finite[mid]) / 2.0)


def fit_ridge(x: NDArray[np.float64], y: NDArray[np.float64], alpha: float) -> Ridge:
    """Fit a multi-output Ridge model."""

    model = Ridge(alpha=float(alpha), fit_intercept=True)
    model.fit(x, y)
    return model


def evaluate_targets(
    *,
    y_true: NDArray[np.float64],
    y_pred: NDArray[np.float64],
    parcel_metadata: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build parcel-wise metrics for prediction outputs."""

    rows: list[dict[str, Any]] = []
    for target_idx, parcel in enumerate(parcel_metadata):
        pearson = pearson_1d(y_true[:, target_idx], y_pred[:, target_idx])
        rows.append(
            {
                "parcel_index": int(parcel["idx_0based"]),
                "parcel_label": str(parcel["label"]),
                "network": str(parcel["network"]),
                "sub_region": str(parcel["sub_region"]),
                "hemisphere": str(parcel["hemisphere"]),
                "pearson": pearson,
                "r2": r2_1d(y_true[:, target_idx], y_pred[:, target_idx]),
                "n_test_trs": int(y_true.shape[0]),
            },
        )
    return rows


def select_global_alpha(
    *,
    x_train: NDArray[np.float64],
    y_train: NDArray[np.float64],
    x_val: NDArray[np.float64],
    y_val: NDArray[np.float64],
    alphas: Sequence[float],
) -> tuple[float, list[dict[str, Any]]]:
    """Select one global alpha by validation mean parcel Pearson."""

    if not alphas:
        raise ValueError("At least one Ridge alpha is required.")
    rows: list[dict[str, Any]] = []
    best_alpha = float(alphas[0])
    best_score = -math.inf
    for alpha in alphas:
        model = fit_ridge(x_train, y_train, float(alpha))
        pred = model.predict(x_val)
        correlations = [
            pearson_1d(y_val[:, target_idx], pred[:, target_idx])
            for target_idx in range(y_val.shape[1])
        ]
        mean_pearson = mean_finite(correlations)
        row = {
            "alpha": float(alpha),
            "mean_val_pearson": mean_pearson,
            "n_val_trs": int(y_val.shape[0]),
            "n_defined_parcels": sum(value is not None for value in correlations),
            "n_total_parcels": int(y_val.shape[1]),
        }
        rows.append(row)
        score = -math.inf if mean_pearson is None else float(mean_pearson)
        if score > best_score:
            best_score = score
            best_alpha = float(alpha)
    return best_alpha, rows
