"""H5 fMRI loading helpers for parcel-wise encoding targets."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import h5py
import numpy as np
from numpy.typing import NDArray


def load_selected_parcel_timeseries(
    *,
    h5_file: str | Path,
    h5_dataset: str,
    selected_parcel_indices: Sequence[int],
    atlas_parcel_count: int,
) -> NDArray[np.float64]:
    """Load selected parcel columns from one H5 fMRI dataset."""

    if not selected_parcel_indices:
        raise ValueError("At least one selected parcel index is required.")
    with h5py.File(h5_file, "r") as handle:
        if h5_dataset not in handle:
            raise ValueError(f"H5 dataset {h5_dataset!r} not found in {h5_file}.")
        dataset = handle[h5_dataset]
        if len(dataset.shape) != 2:
            raise ValueError(
                f"H5 dataset {h5_dataset!r} must be 2D TR x parcel, "
                f"got shape {dataset.shape}.",
            )
        if int(dataset.shape[1]) != atlas_parcel_count:
            raise ValueError(
                f"H5 dataset {h5_dataset!r} has {dataset.shape[1]} parcel columns, "
                f"but atlas labels contain {atlas_parcel_count} parcels.",
            )
        max_index = max(selected_parcel_indices)
        if max_index >= atlas_parcel_count:
            raise ValueError(
                f"Selected parcel index {max_index} exceeds atlas parcel count "
                f"{atlas_parcel_count}.",
            )
        ordered_indices = sorted(int(idx) for idx in selected_parcel_indices)
        return np.asarray(dataset[:, ordered_indices], dtype=np.float64)
