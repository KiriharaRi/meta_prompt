"""Run a one-off Tribe word-feature Ridge encoding baseline.

This script intentionally stays outside the maintained CLI surface. It compares
Tribe word-level Llama features against the current Friends BN246 ROI-union
Ridge encoding baseline while reusing the maintained Ridge utilities.
"""

from __future__ import annotations

import csv
import json
import sys
from argparse import ArgumentParser
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
from numpy.typing import NDArray
from sklearn.decomposition import PCA

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brain_region_pipeline.core.io_utils import write_json, write_jsonl
from brain_region_pipeline.encoding.fmri import load_selected_parcel_timeseries
from brain_region_pipeline.encoding.features import LaggedSample, build_lagged_sample
from brain_region_pipeline.encoding.ridge import (
    MatrixStandardizer,
    evaluate_targets,
    fit_ridge,
    mean_finite,
    median_finite,
    select_global_alpha,
)


VALID_AGGREGATIONS = ("sum", "mean")
TRIBE_DIR = REPO_ROOT / "friends" / "tribe"
H5_FILE = REPO_ROOT / "friends" / "BN" / "sub-01" / "BN_246.h5"
DEFAULT_BASELINE_DIR = (
    REPO_ROOT
    / "friends"
    / "demo"
    / "multi_roi_pilot"
    / "encoding_first7_mimo_v25_lag2_6_bn246_feature_gauss_sigma0p5"
)
OUTPUT_ROOT = REPO_ROOT / "friends" / "demo" / "multi_roi_pilot"

TR_SECONDS = 1.49
LAGS = (2, 3, 4, 5, 6)
ALPHAS = (
    0.01,
    0.03,
    0.1,
    0.3,
    1.0,
    3.0,
    10.0,
    30.0,
    100.0,
    300.0,
    1000.0,
    3000.0,
    10000.0,
)
ATLAS_PARCEL_COUNT = 246
SUBJECT_ID = "sub-01"

DEFAULT_TRAIN_EPISODES = ("s01e01a", "s01e05a", "s01e06a")
DEFAULT_VAL_EPISODES = ("s01e02a",)
DEFAULT_TEST_EPISODES = ("s01e03a",)
H5_DATASETS = {
    "s01e01a": "ses-003_task-s01e01a",
    "s01e05a": "ses-002_task-s01e05a",
    "s01e06a": "ses-003_task-s01e06a",
    "s01e02a": "ses-001_task-s01e02a",
    "s01e03a": "ses-001_task-s01e03a",
    "s02e01a": "ses-010_task-s02e01a",
    "s02e02a": "ses-011_task-s02e02a",
    "s02e03a": "ses-011_task-s02e03a",
    "s02e04a": "ses-011_task-s02e04a",
    "s02e05a": "ses-011_task-s02e05a",
}


@dataclass(frozen=True)
class RunConfig:
    """Runtime options for one Tribe baseline run."""

    aggregation: str
    baseline_dir: Path
    output_dir: Path
    train_episodes: tuple[str, ...]
    val_episodes: tuple[str, ...]
    test_episodes: tuple[str, ...]
    episode_splits: dict[str, str]
    pca_components: int | None
    pca_random_state: int


@dataclass(frozen=True)
class RawEpisodeSample:
    """Unlagged TR-level features and fMRI targets for one episode."""

    episode: str
    split: str
    x_raw: NDArray[np.float64]
    y_raw: NDArray[np.float64]
    aggregation_metadata: dict[str, Any]


@dataclass(frozen=True)
class FeatureProjection:
    """Optional train-fitted PCA projection for TR-level Tribe features."""

    standardizer: MatrixStandardizer | None
    pca: PCA | None
    metadata: dict[str, Any]

    @property
    def enabled(self) -> bool:
        """Return whether a PCA projection should be applied."""

        return self.pca is not None


def _resolve_repo_path(raw_path: str) -> Path:
    """Resolve a CLI path relative to the repo root when it is not absolute."""

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _resolve_baseline_dir(raw_path: str) -> Path:
    """Resolve an encoding output directory that owns encoding_metadata.json."""

    path = _resolve_repo_path(raw_path)
    if (path / "encoding_metadata.json").exists():
        return path
    nested = path / "encoding"
    if (nested / "encoding_metadata.json").exists():
        return nested
    raise FileNotFoundError(
        "Baseline directory must contain encoding_metadata.json, or an "
        f"encoding/ subdirectory that contains it: {path}",
    )


def _parse_episode_list(raw_value: str, *, flag_name: str) -> tuple[str, ...]:
    """Parse a comma-separated episode list from the one-off CLI."""

    episodes = tuple(
        episode.strip()
        for episode in raw_value.split(",")
        if episode.strip()
    )
    if not episodes:
        raise ValueError(f"{flag_name} must include at least one episode.")
    return episodes


def _build_episode_splits(
    *,
    train_episodes: Sequence[str],
    val_episodes: Sequence[str],
    test_episodes: Sequence[str],
) -> dict[str, str]:
    """Build and validate the train/val/test split map.

    The H5 pairing stays explicit in H5_DATASETS; this one-off script should not
    infer fMRI datasets from filenames when users pass custom episode splits.
    """

    split_map: dict[str, str] = {}
    for split, episodes in (
        ("train", train_episodes),
        ("val", val_episodes),
        ("test", test_episodes),
    ):
        for episode in episodes:
            if episode in split_map:
                raise ValueError(
                    f"Episode {episode!r} appears in both {split_map[episode]!r} "
                    f"and {split!r} splits.",
                )
            if episode not in H5_DATASETS:
                raise ValueError(
                    f"Episode {episode!r} has no explicit H5_DATASETS mapping.",
                )
            split_map[episode] = split
    return split_map


def _parse_args() -> RunConfig:
    """Parse one-off script options."""

    parser = ArgumentParser(description="Run a Tribe word-feature Ridge baseline.")
    parser.add_argument(
        "--aggregation",
        choices=VALID_AGGREGATIONS,
        default="sum",
        help="How word-level features are combined inside each TR bin.",
    )
    parser.add_argument(
        "--baseline-dir",
        default=str(DEFAULT_BASELINE_DIR.relative_to(REPO_ROOT)),
        help=(
            "Encoding output directory whose encoding_metadata.json supplies "
            "selected_parcels. Relative paths are resolved from the repo root."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Directory for Tribe result artifacts. Defaults to the historical "
            "multi_roi_pilot output root for the default baseline, otherwise "
            "a subdirectory inside --baseline-dir."
        ),
    )
    parser.add_argument(
        "--train-episodes",
        default=",".join(DEFAULT_TRAIN_EPISODES),
        help="Comma-separated training episodes.",
    )
    parser.add_argument(
        "--val-episodes",
        default=",".join(DEFAULT_VAL_EPISODES),
        help="Comma-separated validation episodes used for alpha selection.",
    )
    parser.add_argument(
        "--test-episodes",
        default=",".join(DEFAULT_TEST_EPISODES),
        help="Comma-separated test episodes.",
    )
    parser.add_argument(
        "--pca-components",
        type=int,
        default=None,
        help=(
            "Optionally reduce TR-level Tribe features to this many PCA "
            "components before lag expansion. PCA is fit on train episodes only."
        ),
    )
    parser.add_argument(
        "--pca-random-state",
        type=int,
        default=0,
        help="Random state for randomized PCA when --pca-components is set.",
    )
    args = parser.parse_args()
    if args.pca_components is not None and args.pca_components < 1:
        raise ValueError("--pca-components must be a positive integer when provided.")
    baseline_dir = _resolve_baseline_dir(args.baseline_dir)
    train_episodes = _parse_episode_list(args.train_episodes, flag_name="--train-episodes")
    val_episodes = _parse_episode_list(args.val_episodes, flag_name="--val-episodes")
    test_episodes = _parse_episode_list(args.test_episodes, flag_name="--test-episodes")
    episode_splits = _build_episode_splits(
        train_episodes=train_episodes,
        val_episodes=val_episodes,
        test_episodes=test_episodes,
    )
    output_leaf = f"tribe_encoding_baseline_{args.aggregation}_lag2_6_bn246_roi_union"
    if args.output_dir is not None:
        output_dir = _resolve_repo_path(args.output_dir)
    elif baseline_dir == DEFAULT_BASELINE_DIR:
        output_dir = OUTPUT_ROOT / output_leaf
    else:
        output_dir = baseline_dir / output_leaf
    return RunConfig(
        aggregation=args.aggregation,
        baseline_dir=baseline_dir,
        output_dir=output_dir,
        train_episodes=train_episodes,
        val_episodes=val_episodes,
        test_episodes=test_episodes,
        episode_splits=episode_splits,
        pca_components=args.pca_components,
        pca_random_state=args.pca_random_state,
    )


def _repo_relative(path: Path) -> str:
    """Render paths relative to the repo root when possible."""

    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _read_json(path: Path) -> dict[str, Any]:
    """Read a JSON object from disk."""

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return payload


def _load_selected_parcels(baseline_dir: Path) -> list[dict[str, Any]]:
    """Load the exact target parcel set from a baseline encoding run."""

    metadata = _read_json(baseline_dir / "encoding_metadata.json")
    parcels = metadata.get("selected_parcels")
    if not isinstance(parcels, list) or not parcels:
        raise ValueError(f"{baseline_dir} metadata has no selected_parcels list.")
    return [dict(parcel) for parcel in parcels]


def _load_comparison_summary(baseline_dir: Path) -> dict[str, Any]:
    """Load the model-scoring comparison metric when the baseline wrote it."""

    path = baseline_dir / "group_summary.json"
    if not path.exists():
        return {
            "path": None,
            "primary_metric": None,
            "mean_test_pearson": None,
            "median_test_pearson": None,
        }
    payload = _read_json(path)
    # The maintained encoding runner records group-level subject means here.
    # Keep the extraction isolated so older or partial baseline dirs can still
    # be used for target selection without failing the Tribe run.
    return {
        "path": _repo_relative(path),
        "primary_metric": payload.get("primary_metric"),
        "mean_test_pearson": payload.get("mean_subject_mean_test_pearson"),
        "median_test_pearson": payload.get("mean_subject_median_test_pearson"),
    }


def _word_start_times(path: Path, expected_rows: int) -> NDArray[np.float64]:
    """Load word start times and validate alignment with the feature matrix."""

    starts: list[float] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "start" not in reader.fieldnames:
            raise ValueError(f"{path} must contain a 'start' column.")
        for row_idx, row in enumerate(reader, start=1):
            raw_start = row.get("start", "")
            if raw_start == "":
                raise ValueError(f"{path}: row {row_idx} has an empty start value.")
            starts.append(float(raw_start))
    if len(starts) != expected_rows:
        raise ValueError(
            f"{path}: expected {expected_rows} word rows from agg.npy, got {len(starts)}.",
        )
    if any(next_start < start for start, next_start in zip(starts, starts[1:], strict=False)):
        raise ValueError(f"{path}: word start times must be monotonic.")
    return np.asarray(starts, dtype=np.float64)


def _load_word_features(episode: str) -> tuple[NDArray[np.float32], NDArray[np.float64]]:
    """Load flattened Tribe word features and matching start times."""

    feature_path = TRIBE_DIR / f"friends_{episode}_llama3p2_agg.npy"
    words_path = TRIBE_DIR / f"friends_{episode}_words.csv"
    if not feature_path.exists():
        raise FileNotFoundError(f"Missing Tribe feature file: {feature_path}")
    if not words_path.exists():
        raise FileNotFoundError(f"Missing Tribe word timing file: {words_path}")

    raw = np.load(feature_path)
    if raw.ndim != 3:
        raise ValueError(f"{feature_path} must be 3D N_words x layer_groups x hidden.")
    # Flatten the two aggregated layer groups into one word-level feature vector.
    # This preserves Tribe's group representation while matching Ridge's 2D input.
    features = raw.reshape(raw.shape[0], -1).astype(np.float32, copy=False)
    starts = _word_start_times(words_path, expected_rows=features.shape[0])
    return features, starts


def _words_to_tr(
    word_features: NDArray[np.float32],
    word_starts: NDArray[np.float64],
    *,
    n_trs: int,
    aggregation: str,
) -> tuple[NDArray[np.float32], dict[str, Any]]:
    """Aggregate word-level features into fMRI TR bins by word start time."""

    tr_features = np.zeros((n_trs, word_features.shape[1]), dtype=np.float32)
    word_counts = np.zeros(n_trs, dtype=np.int64)
    tr_indices = np.floor(word_starts / TR_SECONDS).astype(np.int64)
    valid = (tr_indices >= 0) & (tr_indices < n_trs)
    # Sum preserves language-input amount per TR. Mean normalizes that amount
    # out and tests whether average semantic content alone carries signal.
    np.add.at(tr_features, tr_indices[valid], word_features[valid])
    np.add.at(word_counts, tr_indices[valid], 1)
    if aggregation == "mean":
        nonempty = word_counts > 0
        tr_features[nonempty] /= word_counts[nonempty, None]
    elif aggregation != "sum":
        raise ValueError(f"Unsupported aggregation: {aggregation!r}")
    metadata = {
        "aggregation": aggregation,
        "n_words": int(word_features.shape[0]),
        "n_valid_words": int(valid.sum()),
        "n_words_outside_fmri_axis": int((~valid).sum()),
        "n_trs": int(n_trs),
        "n_nonempty_trs": int((word_counts > 0).sum()),
        "n_empty_trs": int((word_counts == 0).sum()),
        "max_words_per_tr": int(word_counts.max(initial=0)),
    }
    return tr_features, metadata


def _load_episode_sample(
    episode: str,
    selected_indices: Sequence[int],
    *,
    aggregation: str,
) -> tuple[NDArray[np.float64], NDArray[np.float64], dict[str, Any]]:
    """Load one episode into TR-level feature and selected-fMRI matrices."""

    y_raw = load_selected_parcel_timeseries(
        h5_file=H5_FILE,
        h5_dataset=H5_DATASETS[episode],
        selected_parcel_indices=selected_indices,
        atlas_parcel_count=ATLAS_PARCEL_COUNT,
    )
    word_features, word_starts = _load_word_features(episode)
    x_tr, aggregation_metadata = _words_to_tr(
        word_features,
        word_starts,
        n_trs=y_raw.shape[0],
        aggregation=aggregation,
    )
    return (
        x_tr.astype(np.float64, copy=False),
        y_raw.astype(np.float64, copy=False),
        aggregation_metadata,
    )


def _load_raw_episode(
    episode: str,
    selected_indices: Sequence[int],
    *,
    split: str,
    aggregation: str,
) -> RawEpisodeSample:
    """Load one episode before optional PCA projection and lag expansion."""

    x_raw, y_raw, aggregation_metadata = _load_episode_sample(
        episode,
        selected_indices,
        aggregation=aggregation,
    )
    return RawEpisodeSample(
        episode=episode,
        split=split,
        x_raw=x_raw,
        y_raw=y_raw,
        aggregation_metadata=aggregation_metadata,
    )


def _fit_feature_projection(
    *,
    train_x_raw: Sequence[NDArray[np.float64]],
    pca_components: int | None,
    pca_random_state: int,
) -> FeatureProjection:
    """Fit an optional train-only PCA projection for TR-level features."""

    if not train_x_raw:
        raise ValueError("Cannot fit feature projection without training episodes.")
    n_input_features = int(train_x_raw[0].shape[1])
    if any(matrix.shape[1] != n_input_features for matrix in train_x_raw):
        raise ValueError("All train feature matrices must have the same column count.")
    if pca_components is None:
        return FeatureProjection(
            standardizer=None,
            pca=None,
            metadata={
                "enabled": False,
                "fit_split": None,
                "input_dim": n_input_features,
                "output_dim": n_input_features,
            },
        )

    train_matrix = np.vstack(train_x_raw).astype(np.float64, copy=False)
    standardizer = MatrixStandardizer.fit(train_matrix)
    train_standardized = standardizer.transform(train_matrix)
    max_components = min(train_standardized.shape)
    if pca_components > max_components:
        raise ValueError(
            f"--pca-components={pca_components} exceeds the maximum possible "
            f"components {max_components} from train shape {train_standardized.shape}.",
        )
    # PCA is fit only on train TRs to avoid validation/test leakage. The input
    # standardizer is also train-fitted so high-variance raw dimensions do not
    # dominate the projection.
    pca = PCA(
        n_components=pca_components,
        svd_solver="randomized",
        random_state=pca_random_state,
    )
    pca.fit(train_standardized)
    base_labels = _base_feature_names(n_input_features)
    return FeatureProjection(
        standardizer=standardizer,
        pca=pca,
        metadata={
            "enabled": True,
            "fit_split": "train",
            "input_dim": n_input_features,
            "kept_input_dim": int(standardizer.keep_indices.size),
            "output_dim": int(pca_components),
            "random_state": int(pca_random_state),
            "svd_solver": "randomized",
            "explained_variance_ratio_sum": float(np.sum(pca.explained_variance_ratio_)),
            "explained_variance_ratio": [
                float(value)
                for value in pca.explained_variance_ratio_
            ],
            "dropped_input_columns_count": int(standardizer.dropped_indices.size),
            "dropped_input_columns_preview": _index_metadata(
                standardizer.dropped_indices[:50],
                base_labels,
            ),
        },
    )


def _project_features(
    x_raw: NDArray[np.float64],
    projection: FeatureProjection,
) -> NDArray[np.float64]:
    """Apply the optional train-fitted PCA projection to one episode."""

    if not projection.enabled:
        return x_raw
    if projection.standardizer is None or projection.pca is None:
        raise ValueError("PCA projection is enabled but not fully fitted.")
    x_standardized = projection.standardizer.transform(x_raw)
    return projection.pca.transform(x_standardized).astype(np.float64, copy=False)


def _build_lagged_episode(
    raw_sample: RawEpisodeSample,
    *,
    projection: FeatureProjection,
) -> tuple[LaggedSample, dict[str, Any]]:
    """Project and lag one episode sample for Ridge encoding."""

    x_model = _project_features(raw_sample.x_raw, projection)
    sample = build_lagged_sample(
        sample_id=f"{SUBJECT_ID}_{raw_sample.episode}",
        subject_id=SUBJECT_ID,
        split=raw_sample.split,
        x_raw=x_model,
        y_raw=raw_sample.y_raw,
        lags=LAGS,
        feature_start_tr=0,
        fmri_start_tr=0,
    )
    episode_metadata = {
        "episode": raw_sample.episode,
        "split": raw_sample.split,
        "h5_dataset": H5_DATASETS[raw_sample.episode],
        "raw_feature_shape": list(raw_sample.x_raw.shape),
        "model_feature_shape": list(x_model.shape),
        "raw_fmri_shape": list(raw_sample.y_raw.shape),
        "lagged_feature_shape": list(sample.x.shape),
        "lagged_fmri_shape": list(sample.y.shape),
        "aggregation": raw_sample.aggregation_metadata,
    }
    return sample, episode_metadata


def _concat(samples: Sequence[LaggedSample]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Concatenate lagged samples into X/Y matrices."""

    if not samples:
        raise ValueError("Cannot concatenate an empty sample list.")
    return (
        np.vstack([sample.x for sample in samples]).astype(np.float64, copy=False),
        np.vstack([sample.y for sample in samples]).astype(np.float64, copy=False),
    )


def _index_metadata(indices: Sequence[int], labels: Sequence[str]) -> list[dict[str, Any]]:
    """Serialize dropped feature-column metadata without huge per-column dumps."""

    return [
        {"index": int(index), "name": str(labels[int(index)])}
        for index in indices
    ]


def _base_feature_names(n_base_features: int, *, prefix: str = "tribe_dim") -> list[str]:
    """Build compact labels for unlagged Tribe feature dimensions."""

    return [f"{prefix}_{idx}" for idx in range(n_base_features)]


def _feature_names(n_base_features: int, *, prefix: str = "tribe_dim") -> list[str]:
    """Build compact feature labels for lag-expanded Tribe dimensions."""

    base = _base_feature_names(n_base_features, prefix=prefix)
    return [
        f"{name}_lag{lag}"
        for lag in LAGS
        for name in base
    ]


def _parcel_subset(
    selected_parcels: Sequence[dict[str, Any]],
    indices: Sequence[int],
) -> list[dict[str, Any]]:
    """Select parcel metadata by target-column indices."""

    return [dict(selected_parcels[int(index)]) for index in indices]


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
        row["roi_memberships"] = list(parcel.get("roi_memberships", []))
    return rows


def _roi_counts(selected_parcels: Sequence[dict[str, Any]]) -> dict[str, int]:
    """Count selected parcels per ROI membership."""

    counts: dict[str, int] = defaultdict(int)
    for parcel in selected_parcels:
        for roi_id in parcel.get("roi_memberships", []):
            counts[str(roi_id)] += 1
    return dict(counts)


def _roi_metric_summary(
    *,
    parcel_metrics: Sequence[dict[str, Any]],
    selected_parcels: Sequence[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Aggregate retained parcel metrics by ROI membership."""

    total_counts = _roi_counts(selected_parcels)
    summaries: dict[str, dict[str, Any]] = {}
    for roi_id in sorted(total_counts):
        rows = [
            row
            for row in parcel_metrics
            if roi_id in row.get("roi_memberships", [])
        ]
        pearsons = [row["pearson"] for row in rows]
        summaries[roi_id] = {
            "subject_id": SUBJECT_ID,
            "roi_id": roi_id,
            "primary_metric": "mean_test_pearson",
            "mean_test_pearson": mean_finite(pearsons),
            "median_test_pearson": median_finite(pearsons),
            "n_total_selected_parcels": total_counts[roi_id],
            "n_retained_parcels": len(rows),
        }
    return summaries


def _write_markdown_summary(
    *,
    cfg: RunConfig,
    metrics: dict[str, Any],
    roi_summaries: dict[str, dict[str, Any]],
) -> None:
    """Write a compact human-readable result summary."""

    subject = metrics["subject"]
    split = metrics["split"]
    target = metrics["target"]
    comparison = metrics["comparison"]
    projection = metrics["feature_projection"]
    comparison_mean = comparison["model_scoring_mean_test_pearson"]
    comparison_median = comparison["model_scoring_median_test_pearson"]
    feature_label = "Tribe Llama agg"
    if projection["enabled"]:
        feature_label = f"{feature_label} PCA{projection['output_dim']}"
    lines = [
        "# Tribe Encoding Baseline",
        "",
        "## Primary Result",
        "",
        "| Feature set | Aggregation | Test mean Pearson | Test median Pearson | Best alpha | n parcels |",
        "|---|---|---:|---:|---:|---:|",
        (
            f"| {feature_label} | `{cfg.aggregation}` | "
            f"{subject['mean_test_pearson']:.6f} | "
            f"{subject['median_test_pearson']:.6f} | "
            f"{subject['best_alpha']:.6g} | "
            f"{subject['n_retained_parcels']} |"
        ),
    ]
    if comparison_mean is not None:
        median_text = "NA" if comparison_median is None else f"{comparison_median:.6f}"
        lines.append(
            "| Current model-scoring baseline | "
            f"`{comparison['model_scoring_baseline_dir']}` | "
            f"{comparison_mean:.6f} | {median_text} | NA | "
            f"{target['n_selected_parcels']} |"
        )
    if projection["enabled"]:
        lines.extend([
            "",
            "## Feature Projection",
            "",
            "| Method | Fit split | Input dim | Output dim | Explained variance ratio sum |",
            "|---|---|---:|---:|---:|",
            (
                f"| PCA | `{projection['fit_split']}` | "
                f"{projection['input_dim']} | "
                f"{projection['output_dim']} | "
                f"{projection['explained_variance_ratio_sum']:.6f} |"
            ),
        ])
    lines.extend([
        "",
        "## ROI Summary",
        "",
        "| ROI | Mean Pearson | Median Pearson | n retained / n selected |",
        "|---|---:|---:|---:|",
    ])
    for roi_id, row in sorted(roi_summaries.items()):
        lines.append(
            f"| {roi_id} | "
            f"{row['mean_test_pearson']:.6f} | "
            f"{row['median_test_pearson']:.6f} | "
            f"{row['n_retained_parcels']} / {row['n_total_selected_parcels']} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            f"- Word-level Tribe features were flattened from `(N_words, 2, 3072)` to `(N_words, 6144)`.",
            f"- Word features were assigned to TR bins by `floor(start / {TR_SECONDS})` and aggregated with `{cfg.aggregation}`.",
        ],
    )
    if projection["enabled"]:
        lines.extend([
            (
                "- TR-level Tribe features were z-scored with train split "
                f"statistics and PCA-reduced to {projection['output_dim']} "
                "components before lag expansion."
            ),
            (
                "- Lag-expanded PCA feature dimensionality was "
                f"{projection['output_dim'] * len(LAGS)}."
            ),
        ])
    lines.extend(
        [
            f"- Lags were `{list(LAGS)}` TRs.",
            f"- Train episodes were `{split['train']}`.",
            f"- Alpha was selected on validation episodes `{split['val']}`.",
            f"- Ridge was refit on train+val and evaluated on test episodes `{split['test']}`.",
            f"- The target set comes from `{target['selected_parcels_source']}`.",
            f"- The target set contains {target['n_selected_parcels']} selected BN246 parcels before constant-target filtering.",
        ],
    )
    (cfg.output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """Run the baseline and write result artifacts."""

    cfg = _parse_args()
    selected_parcels = _load_selected_parcels(cfg.baseline_dir)
    comparison_summary = _load_comparison_summary(cfg.baseline_dir)
    selected_indices = [int(parcel["idx_0based"]) for parcel in selected_parcels]

    raw_samples: list[RawEpisodeSample] = []
    for episode, split in cfg.episode_splits.items():
        raw_samples.append(
            _load_raw_episode(
                episode,
                selected_indices,
                split=split,
                aggregation=cfg.aggregation,
            ),
        )
    projection = _fit_feature_projection(
        train_x_raw=[
            sample.x_raw
            for sample in raw_samples
            if sample.split == "train"
        ],
        pca_components=cfg.pca_components,
        pca_random_state=cfg.pca_random_state,
    )

    by_split: dict[str, list[LaggedSample]] = {"train": [], "val": [], "test": []}
    episodes_metadata: list[dict[str, Any]] = []
    for raw_sample in raw_samples:
        sample, metadata = _build_lagged_episode(
            raw_sample,
            projection=projection,
        )
        by_split[sample.split].append(sample)
        episodes_metadata.append(metadata)

    x_train_raw, y_train_raw = _concat(by_split["train"])
    x_val_raw, y_val_raw = _concat(by_split["val"])
    x_test_raw, y_test_raw = _concat(by_split["test"])
    feature_prefix = "tribe_pca_dim" if projection.enabled else "tribe_dim"
    feature_labels = _feature_names(
        x_train_raw.shape[1] // len(LAGS),
        prefix=feature_prefix,
    )

    x_standardizer = MatrixStandardizer.fit(x_train_raw)
    y_standardizer = MatrixStandardizer.fit(y_train_raw)
    retained_parcels = _parcel_subset(selected_parcels, y_standardizer.keep_indices)

    x_train = x_standardizer.transform(x_train_raw)
    x_val = x_standardizer.transform(x_val_raw)
    x_test = x_standardizer.transform(x_test_raw)
    y_train = y_standardizer.transform(y_train_raw)
    y_val = y_standardizer.transform(y_val_raw)

    best_alpha, alpha_rows = select_global_alpha(
        x_train=x_train,
        y_train=y_train,
        x_val=x_val,
        y_val=y_val,
        alphas=ALPHAS,
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
        parcel_metrics=parcel_metrics,
        selected_parcels=selected_parcels,
    )

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    comparison_mean = comparison_summary["mean_test_pearson"]
    command_parts = [
        "uv run python scripts/run_tribe_encoding_baseline.py",
        f"--aggregation {cfg.aggregation}",
        f"--baseline-dir {_repo_relative(cfg.baseline_dir)}",
        f"--output-dir {_repo_relative(cfg.output_dir)}",
        f"--train-episodes {','.join(cfg.train_episodes)}",
        f"--val-episodes {','.join(cfg.val_episodes)}",
        f"--test-episodes {','.join(cfg.test_episodes)}",
    ]
    if cfg.pca_components is not None:
        command_parts.extend([
            f"--pca-components {cfg.pca_components}",
            f"--pca-random-state {cfg.pca_random_state}",
        ])
    feature_set_name = f"tribe_llama3p2_agg_word_{cfg.aggregation}"
    if cfg.pca_components is not None:
        feature_set_name = f"{feature_set_name}_pca{cfg.pca_components}"
    subject_summary = {
        "subject_id": SUBJECT_ID,
        "best_alpha": best_alpha,
        "primary_metric": "mean_test_pearson",
        "mean_test_pearson": mean_finite(pearsons),
        "median_test_pearson": median_finite(pearsons),
        "n_total_selected_parcels": len(selected_parcels),
        "n_retained_parcels": len(retained_parcels),
        "n_dropped_constant_y_parcels": int(y_standardizer.dropped_indices.size),
        "n_train_trs": int(y_train.shape[0]),
        "n_val_trs": int(y_val.shape[0]),
        "n_test_trs": int(x_test.shape[0]),
        "roi_summaries": roi_summaries,
        "dropped_x_columns_count": int(x_standardizer.dropped_indices.size),
        "dropped_x_columns_preview": _index_metadata(
            x_standardizer.dropped_indices[:50],
            feature_labels,
        ),
        "dropped_y_parcels": _parcel_subset(
            selected_parcels,
            y_standardizer.dropped_indices,
        ),
    }
    metrics = {
        "command": " ".join(command_parts),
        "feature_set_name": feature_set_name,
        "aggregation": cfg.aggregation,
        "feature_projection": projection.metadata,
        "tr_s": TR_SECONDS,
        "lags": list(LAGS),
        "alphas": list(ALPHAS),
        "alpha_selection": "global alpha by validation mean parcel Pearson",
        "normalization": (
            "Optional PCA input X, lagged X, and Y are z-scored with train split "
            "statistics; constants dropped at each standardization stage"
        ),
        "split": {
            "train": list(cfg.train_episodes),
            "val": list(cfg.val_episodes),
            "test": list(cfg.test_episodes),
        },
        "target": {
            "h5_file": str(H5_FILE.relative_to(REPO_ROOT)),
            "atlas": "BN246",
            "scope": "selected_parcels from baseline encoding metadata",
            "selected_parcels_source": _repo_relative(cfg.baseline_dir / "encoding_metadata.json"),
            "n_selected_parcels": len(selected_parcels),
        },
        "comparison": {
            "model_scoring_baseline_dir": _repo_relative(cfg.baseline_dir),
            "model_scoring_group_summary": comparison_summary["path"],
            "model_scoring_primary_metric": comparison_summary["primary_metric"],
            "model_scoring_mean_test_pearson": comparison_mean,
            "model_scoring_median_test_pearson": comparison_summary["median_test_pearson"],
            "tribe_minus_model_scoring_mean_test_pearson": (
                None
                if subject_summary["mean_test_pearson"] is None or comparison_mean is None
                else float(subject_summary["mean_test_pearson"] - comparison_mean)
            ),
        },
        "episodes": episodes_metadata,
        "subject": subject_summary,
    }

    write_json(cfg.output_dir / "metrics.json", metrics)
    write_json(cfg.output_dir / "alpha_search.json", {
        "subject_id": SUBJECT_ID,
        "selected_alpha": best_alpha,
        "selection_metric": "mean_val_pearson",
        "rows": alpha_rows,
    })
    write_json(cfg.output_dir / "roi_summaries.json", roi_summaries)
    write_jsonl(cfg.output_dir / "parcel_metrics.jsonl", parcel_metrics)
    np.savez_compressed(
        cfg.output_dir / "test_predictions.npz",
        y_true=y_true,
        y_pred=y_pred,
        parcel_indices=np.asarray(
            [int(parcel["idx_0based"]) for parcel in retained_parcels],
            dtype=np.int64,
        ),
        parcel_labels=np.asarray([str(parcel["label"]) for parcel in retained_parcels]),
        parcel_roi_memberships=np.asarray([
            "|".join(str(item) for item in parcel.get("roi_memberships", []))
            for parcel in retained_parcels
        ]),
    )
    _write_markdown_summary(cfg=cfg, metrics=metrics, roi_summaries=roi_summaries)
    print(json.dumps(metrics["subject"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
