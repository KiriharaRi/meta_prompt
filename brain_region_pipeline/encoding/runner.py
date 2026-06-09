"""Runner for unified Ridge encoding over one or more ROI feature sets."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from numpy.typing import NDArray

from ..atlas.labels import expand_region_indices, parse_atlas_labels
from ..core.config import RidgeEncodingConfig
from ..core.io_utils import read_json, read_jsonl, write_json, write_jsonl
from ..schema_design.region_schema import load_region_schema
from ..schema_design.schema_models import RegionFeatureSchema
from .features import (
    LaggedSample,
    build_lagged_sample,
    expanded_feature_names,
    trim_matrix,
)
from .fmri import load_selected_parcel_timeseries
from .manifest import RoiEncodingManifestEntry, load_roi_encoding_manifest
from .ridge import (
    MatrixStandardizer,
    evaluate_targets,
    fit_ridge,
    mean_finite,
    median_finite,
    select_global_alpha,
)


def _log(message: str) -> None:
    print(f"[brain_region_pipeline] {message}", flush=True)


def _resolve_schema_mapping(path: str | Path) -> dict[str, Path]:
    """Load ROI id -> schema path mapping."""

    mapping_path = Path(path)
    payload = read_json(mapping_path)
    raw_mapping = payload.get("roi_schemas", payload)
    if not isinstance(raw_mapping, dict) or not raw_mapping:
        raise ValueError("--roi-schemas must contain a non-empty JSON object.")
    resolved: dict[str, Path] = {}
    for roi_id, raw_path in raw_mapping.items():
        key = str(roi_id).strip()
        if not key:
            raise ValueError("ROI schema mapping contains an empty ROI id.")
        schema_path = Path(str(raw_path).strip())
        if not schema_path.is_absolute():
            schema_path = mapping_path.parent / schema_path
        resolved[key] = schema_path
    return resolved


def _load_roi_schemas(
    path: str | Path,
) -> tuple[list[str], dict[str, RegionFeatureSchema], dict[str, Path]]:
    """Load ROI schemas in mapping-file order."""

    mapping = _resolve_schema_mapping(path)
    schemas = {roi_id: load_region_schema(schema_path) for roi_id, schema_path in mapping.items()}
    for roi_id, schema in schemas.items():
        if schema.target_region != roi_id:
            raise ValueError(
                f"ROI schema mapping key must match schema target_region: "
                f"{roi_id!r} != {schema.target_region!r}.",
            )
    return list(mapping), schemas, mapping


def _split_subject_entries(
    entries: Sequence[RoiEncodingManifestEntry],
) -> dict[str, dict[str, list[RoiEncodingManifestEntry]]]:
    """Group manifest rows by subject and split, requiring train/val/test."""

    grouped: dict[str, dict[str, list[RoiEncodingManifestEntry]]] = defaultdict(
        lambda: {"train": [], "val": [], "test": []},
    )
    for entry in entries:
        grouped[entry.subject_id][entry.split].append(entry)
    for subject_id, split_entries in grouped.items():
        missing = [split for split, rows in split_entries.items() if not rows]
        if missing:
            raise ValueError(
                f"Subject {subject_id!r} is missing required split(s): "
                + ", ".join(missing),
            )
    return dict(grouped)


def _feature_axis(rows: Sequence[dict[str, Any]], path: Path) -> list[tuple[int, float, float]]:
    """Return comparable TR provenance tuples for one feature file."""

    axis: list[tuple[int, float, float]] = []
    for row_idx, row in enumerate(rows, start=1):
        try:
            axis.append(
                (
                    int(row["tr_index"]),
                    float(row["tr_start_s"]),
                    float(row["tr_end_s"]),
                ),
            )
        except KeyError as exc:
            raise ValueError(
                f"{path}: row {row_idx} missing TR provenance field {exc.args[0]!r}.",
            ) from exc
    return axis


def _load_one_roi_feature_matrix(
    path: Path,
    feature_names: Sequence[str],
) -> tuple[NDArray[np.float64], list[tuple[int, float, float]]]:
    """Read one ROI ``tr_features.jsonl`` with TR-axis provenance."""

    rows = read_jsonl(path)
    if not rows:
        raise ValueError(f"TR feature file contains no rows: {path}")
    expected_len = len(feature_names)
    vectors: list[list[float]] = []
    for row_idx, row in enumerate(rows, start=1):
        vector = row.get("feature_vector")
        if not isinstance(vector, list):
            raise ValueError(f"{path}: row {row_idx} missing feature_vector list.")
        if len(vector) != expected_len:
            raise ValueError(
                f"{path}: row {row_idx} feature_vector has length {len(vector)}, "
                f"expected {expected_len} from ROI schema.",
            )
        vectors.append([float(value) for value in vector])
    return np.asarray(vectors, dtype=np.float64), _feature_axis(rows, path)


def _load_roi_feature_matrix(
    entry: RoiEncodingManifestEntry,
    *,
    roi_order: Sequence[str],
    schemas: dict[str, RegionFeatureSchema],
) -> tuple[NDArray[np.float64], list[str]]:
    """Load and horizontally concatenate ROI feature matrices for one sample."""

    matrices: list[NDArray[np.float64]] = []
    names: list[str] = []
    reference_axis: list[tuple[int, float, float]] | None = None
    reference_roi = ""
    for roi_id in roi_order:
        if roi_id not in entry.roi_features:
            raise ValueError(f"Sample {entry.sample_id!r} missing features for ROI {roi_id!r}.")
        roi_feature_names = schemas[roi_id].ordered_dimension_ids()
        matrix, axis = _load_one_roi_feature_matrix(
            entry.roi_features[roi_id],
            roi_feature_names,
        )
        if reference_axis is None:
            reference_axis = axis
            reference_roi = roi_id
        elif axis != reference_axis:
            raise ValueError(
                f"Sample {entry.sample_id!r}: TR axis mismatch between ROI "
                f"{reference_roi!r} and {roi_id!r}.",
            )
        matrices.append(matrix)
        names.extend(f"{roi_id}::{feature_name}" for feature_name in roi_feature_names)
    return np.hstack(matrices).astype(np.float64), names


def _selected_parcel_metadata(
    *,
    roi_order: Sequence[str],
    schemas: dict[str, RegionFeatureSchema],
    parcels: Sequence[dict[str, str | int]],
) -> list[dict[str, Any]]:
    """Return de-duplicated selected parcels with ROI membership metadata."""

    by_index = {int(parcel["idx_0based"]): parcel for parcel in parcels}
    memberships: dict[int, list[str]] = defaultdict(list)
    for roi_id in roi_order:
        indices = expand_region_indices(schemas[roi_id], list(parcels))
        if not indices:
            raise ValueError(f"ROI schema {roi_id!r} selects no parcels.")
        for parcel_idx in indices:
            memberships[int(parcel_idx)].append(roi_id)

    rows: list[dict[str, Any]] = []
    for parcel_idx in sorted(memberships):
        parcel = by_index[parcel_idx]
        rows.append(
            {
                "idx_0based": parcel_idx,
                "label": str(parcel["label"]),
                "network": str(parcel["network"]),
                "sub_region": str(parcel["sub_region"]),
                "hemisphere": str(parcel["hemisphere"]),
                "roi_memberships": list(memberships[parcel_idx]),
            },
        )
    if not rows:
        raise ValueError("ROI schema selection produced no parcels.")
    return rows


def _load_lagged_sample(
    entry: RoiEncodingManifestEntry,
    *,
    roi_order: Sequence[str],
    schemas: dict[str, RegionFeatureSchema],
    selected_parcels: Sequence[dict[str, Any]],
    atlas_parcel_count: int,
    cfg: RidgeEncodingConfig,
) -> tuple[LaggedSample, list[str]]:
    """Load one manifest row into a lag-expanded ROI sample."""

    x_raw, feature_names = _load_roi_feature_matrix(
        entry,
        roi_order=roi_order,
        schemas=schemas,
    )
    selected_indices = [int(parcel["idx_0based"]) for parcel in selected_parcels]
    y_raw = load_selected_parcel_timeseries(
        h5_file=entry.h5_file,
        h5_dataset=entry.h5_dataset,
        selected_parcel_indices=selected_indices,
        atlas_parcel_count=atlas_parcel_count,
    )
    x_trimmed = trim_matrix(
        x_raw,
        start_tr=entry.feature_trim_start_tr,
        end_tr=entry.feature_trim_end_tr,
        label=f"{entry.sample_id} ROI features",
    )
    y_trimmed = trim_matrix(
        y_raw,
        start_tr=entry.fmri_trim_start_tr,
        end_tr=entry.fmri_trim_end_tr,
        label=f"{entry.sample_id} fMRI",
    )
    if x_trimmed.shape[0] != y_trimmed.shape[0]:
        raise ValueError(
            f"Sample {entry.sample_id!r}: feature and fMRI lengths differ after "
            "explicit manifest trimming "
            f"({x_trimmed.shape[0]} != {y_trimmed.shape[0]}).",
        )
    sample = build_lagged_sample(
        sample_id=entry.sample_id,
        subject_id=entry.subject_id,
        split=entry.split,
        x_raw=x_trimmed,
        y_raw=y_trimmed,
        lags=cfg.lags,
        feature_start_tr=entry.feature_trim_start_tr,
        fmri_start_tr=entry.fmri_trim_start_tr,
    )
    return sample, feature_names


def _concat_samples(samples: Sequence[LaggedSample]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Concatenate lagged sample matrices."""

    if not samples:
        raise ValueError("Cannot concatenate an empty sample list.")
    return (
        np.vstack([sample.x for sample in samples]).astype(np.float64),
        np.vstack([sample.y for sample in samples]).astype(np.float64),
    )


def _concat_test_provenance(samples: Sequence[LaggedSample]) -> tuple[NDArray[np.str_], NDArray[np.int64], NDArray[np.int64]]:
    """Return per-test-row sample and TR provenance arrays."""

    sample_ids: list[str] = []
    feature_tr_indices: list[int] = []
    fmri_tr_indices: list[int] = []
    for sample in samples:
        sample_ids.extend([sample.sample_id] * sample.x.shape[0])
        feature_tr_indices.extend(int(value) for value in sample.feature_tr_indices)
        fmri_tr_indices.extend(int(value) for value in sample.fmri_tr_indices)
    return (
        np.asarray(sample_ids, dtype=str),
        np.asarray(feature_tr_indices, dtype=np.int64),
        np.asarray(fmri_tr_indices, dtype=np.int64),
    )


def _parcel_subset(
    parcel_metadata: Sequence[dict[str, Any]],
    indices: Sequence[int],
) -> list[dict[str, Any]]:
    """Select parcel metadata by matrix-column indices."""

    return [dict(parcel_metadata[int(index)]) for index in indices]


def _index_metadata(indices: Sequence[int], labels: Sequence[str]) -> list[dict[str, Any]]:
    """Serialize dropped matrix-column metadata."""

    return [
        {"index": int(index), "name": str(labels[int(index)])}
        for index in indices
    ]


def _roi_counts(selected_parcels: Sequence[dict[str, Any]]) -> dict[str, int]:
    """Count selected parcels per ROI membership."""

    counts: dict[str, int] = defaultdict(int)
    for parcel in selected_parcels:
        for roi_id in parcel["roi_memberships"]:
            counts[str(roi_id)] += 1
    return dict(counts)


def _roi_metric_summary(
    *,
    subject_id: str,
    parcel_metrics: Sequence[dict[str, Any]],
    selected_parcels: Sequence[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Aggregate retained parcel metrics by ROI membership."""

    total_counts = _roi_counts(selected_parcels)
    summaries: dict[str, dict[str, Any]] = {}
    roi_ids = sorted(total_counts)
    for roi_id in roi_ids:
        rows = [
            row for row in parcel_metrics
            if roi_id in row.get("roi_memberships", [])
        ]
        pearsons = [row["pearson"] for row in rows]
        summaries[roi_id] = {
            "subject_id": subject_id,
            "roi_id": roi_id,
            "primary_metric": "mean_test_pearson",
            "mean_test_pearson": mean_finite(pearsons),
            "median_test_pearson": median_finite(pearsons),
            "n_total_selected_parcels": total_counts[roi_id],
            "n_retained_parcels": len(rows),
        }
    return summaries


def _subject_output_paths(output_dir: Path, subject_id: str) -> dict[str, Path]:
    """Return subject-level output paths for a ROI encoding run."""

    subject_dir = output_dir / subject_id
    return {
        "dir": subject_dir,
        "alpha_search": subject_dir / "alpha_search.json",
        "parcel_metrics": subject_dir / "parcel_metrics.jsonl",
        "roi_summaries": subject_dir / "roi_summaries.json",
        "predictions": subject_dir / "test_predictions.npz",
        "coefficients": subject_dir / "ridge_coefficients.npz",
    }


def _parcel_metrics_with_memberships(
    *,
    y_true: NDArray[np.float64],
    y_pred: NDArray[np.float64],
    parcel_metadata: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Evaluate retained parcels and attach ROI membership metadata."""

    rows = evaluate_targets(
        y_true=y_true,
        y_pred=y_pred,
        parcel_metadata=parcel_metadata,
    )
    for row, parcel in zip(rows, parcel_metadata, strict=True):
        row["roi_memberships"] = list(parcel["roi_memberships"])
    return rows


def _run_subject_encoding(
    *,
    subject_id: str,
    split_entries: dict[str, list[RoiEncodingManifestEntry]],
    roi_order: Sequence[str],
    schemas: dict[str, RegionFeatureSchema],
    selected_parcels: Sequence[dict[str, Any]],
    atlas_parcel_count: int,
    cfg: RidgeEncodingConfig,
    output_dir: Path,
) -> dict[str, Any]:
    """Fit and evaluate one subject-level joint ROI Ridge model."""

    lagged_by_split: dict[str, list[LaggedSample]] = {}
    base_feature_names: list[str] | None = None
    for split, entries in split_entries.items():
        lagged_by_split[split] = []
        for entry in entries:
            sample, feature_names = _load_lagged_sample(
                entry,
                roi_order=roi_order,
                schemas=schemas,
                selected_parcels=selected_parcels,
                atlas_parcel_count=atlas_parcel_count,
                cfg=cfg,
            )
            if base_feature_names is None:
                base_feature_names = feature_names
            elif feature_names != base_feature_names:
                raise ValueError(
                    f"Sample {entry.sample_id!r}: ROI feature order changed.",
                )
            lagged_by_split[split].append(sample)
    if base_feature_names is None:
        raise ValueError(f"Subject {subject_id!r} has no samples.")

    x_train_raw, y_train_raw = _concat_samples(lagged_by_split["train"])
    x_val_raw, y_val_raw = _concat_samples(lagged_by_split["val"])
    x_test_raw, y_test_raw = _concat_samples(lagged_by_split["test"])
    feature_labels = expanded_feature_names(base_feature_names, cfg.lags)

    x_standardizer = MatrixStandardizer.fit(x_train_raw)
    y_standardizer = MatrixStandardizer.fit(y_train_raw)
    kept_feature_names = [feature_labels[int(index)] for index in x_standardizer.keep_indices]
    retained_parcels = _parcel_subset(selected_parcels, y_standardizer.keep_indices)

    x_train = x_standardizer.transform(x_train_raw)
    x_val = x_standardizer.transform(x_val_raw)
    x_test = x_standardizer.transform(x_test_raw)
    y_train = y_standardizer.transform(y_train_raw)
    y_val = y_standardizer.transform(y_val_raw)
    y_test = y_standardizer.transform(y_test_raw)

    best_alpha, alpha_rows = select_global_alpha(
        x_train=x_train,
        y_train=y_train,
        x_val=x_val,
        y_val=y_val,
        alphas=cfg.alphas,
    )
    model = fit_ridge(
        np.vstack([x_train, x_val]),
        np.vstack([y_train, y_val]),
        best_alpha,
    )
    y_pred_z = model.predict(x_test)
    y_pred = y_standardizer.inverse_transform_kept(y_pred_z)
    y_true = y_test_raw[:, y_standardizer.keep_indices]
    parcel_metrics = _parcel_metrics_with_memberships(
        y_true=y_true,
        y_pred=y_pred,
        parcel_metadata=retained_parcels,
    )
    pearsons = [row["pearson"] for row in parcel_metrics]
    roi_summaries = _roi_metric_summary(
        subject_id=subject_id,
        parcel_metrics=parcel_metrics,
        selected_parcels=selected_parcels,
    )
    subject_summary = {
        "subject_id": subject_id,
        "best_alpha": best_alpha,
        "primary_metric": "mean_test_pearson",
        "mean_test_pearson": mean_finite(pearsons),
        "median_test_pearson": median_finite(pearsons),
        "n_total_selected_parcels": len(selected_parcels),
        "n_retained_parcels": len(retained_parcels),
        "n_dropped_constant_y_parcels": int(y_standardizer.dropped_indices.size),
        "n_train_trs": int(y_train.shape[0]),
        "n_val_trs": int(y_val.shape[0]),
        "n_test_trs": int(y_test.shape[0]),
        "roi_summaries": roi_summaries,
        "dropped_x_columns": _index_metadata(
            x_standardizer.dropped_indices,
            feature_labels,
        ),
        "dropped_y_parcels": _parcel_subset(
            selected_parcels,
            y_standardizer.dropped_indices,
        ),
    }

    paths = _subject_output_paths(output_dir, subject_id)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    write_json(
        paths["alpha_search"],
        {
            "subject_id": subject_id,
            "selected_alpha": best_alpha,
            "selection_metric": "mean_val_pearson",
            "rows": alpha_rows,
        },
    )
    write_jsonl(paths["parcel_metrics"], parcel_metrics)
    write_json(paths["roi_summaries"], roi_summaries)
    sample_ids, feature_tr_indices, fmri_tr_indices = _concat_test_provenance(
        lagged_by_split["test"],
    )
    np.savez_compressed(
        paths["predictions"],
        y_true=y_true,
        y_pred=y_pred,
        parcel_indices=np.asarray(
            [int(parcel["idx_0based"]) for parcel in retained_parcels],
            dtype=np.int64,
        ),
        parcel_labels=np.asarray([str(parcel["label"]) for parcel in retained_parcels]),
        parcel_roi_memberships=np.asarray([
            "|".join(str(item) for item in parcel["roi_memberships"])
            for parcel in retained_parcels
        ]),
        sample_ids=sample_ids,
        feature_tr_indices=feature_tr_indices,
        fmri_tr_indices=fmri_tr_indices,
    )
    np.savez_compressed(
        paths["coefficients"],
        coef=np.asarray(model.coef_, dtype=np.float64),
        intercept=np.asarray(model.intercept_, dtype=np.float64),
        expanded_feature_names=np.asarray(kept_feature_names),
        parcel_indices=np.asarray(
            [int(parcel["idx_0based"]) for parcel in retained_parcels],
            dtype=np.int64,
        ),
        parcel_labels=np.asarray([str(parcel["label"]) for parcel in retained_parcels]),
        parcel_roi_memberships=np.asarray([
            "|".join(str(item) for item in parcel["roi_memberships"])
            for parcel in retained_parcels
        ]),
    )
    return {
        "subject_id": subject_id,
        "best_alpha": best_alpha,
        "mean_test_pearson": subject_summary["mean_test_pearson"],
        "median_test_pearson": subject_summary["median_test_pearson"],
        "n_retained_parcels": len(retained_parcels),
        "n_test_trs": int(y_test.shape[0]),
        "roi_summaries": roi_summaries,
        "output_dir": str(paths["dir"]),
    }


def _group_summary(subject_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Summarize subject-level ROI metrics."""

    mean_values = [row["mean_test_pearson"] for row in subject_rows]
    median_values = [row["median_test_pearson"] for row in subject_rows]
    roi_ids = sorted({
        roi_id
        for row in subject_rows
        for roi_id in row.get("roi_summaries", {})
    })
    roi_summaries: dict[str, dict[str, Any]] = {}
    for roi_id in roi_ids:
        roi_means = [
            row["roi_summaries"][roi_id]["mean_test_pearson"]
            for row in subject_rows
            if roi_id in row.get("roi_summaries", {})
        ]
        roi_summaries[roi_id] = {
            "roi_id": roi_id,
            "primary_metric": "mean_subject_mean_test_pearson",
            "mean_subject_mean_test_pearson": mean_finite(roi_means),
            "median_subject_mean_test_pearson": median_finite(roi_means),
            "n_subjects": len(roi_means),
        }
    payload = {
        "primary_metric": "mean_subject_mean_test_pearson",
        "n_subjects": len(subject_rows),
        "mean_subject_mean_test_pearson": mean_finite(mean_values),
        "median_subject_mean_test_pearson": median_finite(mean_values),
        "mean_subject_median_test_pearson": mean_finite(median_values),
        "roi_summaries": roi_summaries,
        "subjects": list(subject_rows),
    }
    return payload


def fit_roi_encoding_from_manifest(args, cfg: RidgeEncodingConfig) -> None:
    """Run joint H5 Ridge encoding from a unified ROI JSONL manifest."""

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _log("Step 1/5: Load manifest, ROI schemas, and atlas labels")
    entries = load_roi_encoding_manifest(args.manifest)
    roi_order, schemas, schema_paths = _load_roi_schemas(args.roi_schemas)
    manifest_roi_ids = set(entries[0].roi_features)
    if set(roi_order) != manifest_roi_ids:
        raise ValueError(
            "ROI schema mapping must match manifest roi_features exactly: "
            f"{roi_order!r} != {sorted(manifest_roi_ids)!r}.",
        )
    parcels = parse_atlas_labels(args.atlas_labels)
    selected_parcels = _selected_parcel_metadata(
        roi_order=roi_order,
        schemas=schemas,
        parcels=parcels,
    )
    grouped = _split_subject_entries(entries)
    _log(
        f"  Loaded {len(entries)} sample(s), {len(grouped)} subject(s), "
        f"{len(roi_order)} ROI feature set(s), {len(selected_parcels)} unique selected parcel(s)",
    )

    _log("Step 2/5: Fit subject-level joint ROI Ridge encoding models")
    subject_rows = []
    for subject_id, split_entries in sorted(grouped.items()):
        _log(f"  Subject {subject_id}: load matrices, select alpha, evaluate test split")
        subject_rows.append(
            _run_subject_encoding(
                subject_id=subject_id,
                split_entries=split_entries,
                roi_order=roi_order,
                schemas=schemas,
                selected_parcels=selected_parcels,
                atlas_parcel_count=len(parcels),
                cfg=cfg,
                output_dir=output_dir,
            ),
        )

    _log("Step 3/5: Write group summary")
    group_payload = _group_summary(subject_rows)
    write_json(output_dir / "group_summary.json", group_payload)

    _log("Step 4/5: Write encoding metadata")
    write_json(
        output_dir / "encoding_metadata.json",
        {
            "command": "fit-roi-encoding",
            "manifest": str(args.manifest),
            "roi_schemas": {
                roi_id: str(schema_paths[roi_id])
                for roi_id in roi_order
            },
            "atlas_labels": str(args.atlas_labels),
            "feature_set_name": entries[0].feature_set_name,
            "roi_order": list(roi_order),
            "lags": list(cfg.lags),
            "alphas": list(cfg.alphas),
            "alpha_selection": "global alpha per subject by mean validation parcel Pearson",
            "normalization": "X and Y z-scored with train split statistics; constants dropped",
            "target_granularity": "unique selected parcels, with ROI membership summaries",
            "selected_parcels": [dict(parcel) for parcel in selected_parcels],
            "samples": [entry.to_metadata() for entry in entries],
            "subjects": subject_rows,
        },
    )

    _log("Step 5/5: ROI encoding stage complete")
    _log(f"  Wrote group summary to {output_dir / 'group_summary.json'}")
    _log(f"  Wrote metadata to {output_dir / 'encoding_metadata.json'}")
    print(json.dumps(group_payload, ensure_ascii=False, indent=2))
