"""Rerun the Friends train-size curve with the expanded 10-test split.

The script reuses completed 14-ROI scoring features. It builds dedicated
manifests for every train-size prefix, runs Ridge encoding only, then updates
the existing Friends-vs-Tribe every-10 comparison CSV and figure. It removes
only prior ad-hoc curve outputs, leaving canonical round7/round8 snapshots
intact for provenance.
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from brain_region_pipeline.core.config import RidgeEncodingConfig
from brain_region_pipeline.encoding.runner import RoiEncodingInput, fit_roi_encoding_from_manifest


ROUND8_CONFIG = (
    REPO_ROOT
    / "configs"
    / "friends_train_size_sweep_20260629_round8"
    / "round8_next30_145train_10test_scoring_encoding.json"
)
CONFIG_OUTPUT_DIR = (
    REPO_ROOT
    / "configs"
    / "friends_train_size_sweep_20260629_round8"
    / "every10_10test"
)
ROUND8_ANALYSIS_DIR = (
    REPO_ROOT
    / "friends"
    / "analysis"
    / "train_size_sweep_20260629_round8"
)
RERUN_ANALYSIS_DIR = (
    REPO_ROOT
    / "friends"
    / "analysis"
    / "train_size_sweep_20260630_every10_10test_rerun"
)
COMPARISON_STEM = (
    REPO_ROOT
    / "friends"
    / "analysis"
    / "train_size_comparison_20260627"
    / "friends_vs_tribe_train_size_every10"
)
ALL_FRIENDS_TRAIN_SIZES = tuple(range(5, 146, 10))
PREVIOUS_CURVE_SNAPSHOT_DIRS = tuple(
    ROUND8_ANALYSIS_DIR / f"encoding_{train_size}train_10test_snapshot"
    for train_size in (105, 125, 135)
)
CSV_FIELDS = (
    "series",
    "train_size",
    "mean_test_pearson",
    "median_test_pearson",
    "best_alpha",
    "n_retained_parcels",
    "n_test_trs",
    "source",
    "source_note",
)


@dataclass(frozen=True)
class EncodingMetrics:
    """Subset of encoding outputs needed for the comparison table."""

    train_size: int
    mean_test_pearson: float
    median_test_pearson: float
    best_alpha: float
    n_retained_parcels: int
    n_test_trs: int
    source: Path
    source_note: str


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _ensure_repo_child(path: Path) -> Path:
    resolved = path.resolve()
    resolved.relative_to(REPO_ROOT)
    return resolved


def _clean_previous_curve_outputs() -> None:
    """Remove stale curve-only artifacts so rerun metrics are freshly derived."""

    for path in PREVIOUS_CURVE_SNAPSHOT_DIRS:
        resolved = _ensure_repo_child(path)
        if resolved.exists():
            shutil.rmtree(resolved)

    if CONFIG_OUTPUT_DIR.exists():
        for path in CONFIG_OUTPUT_DIR.glob("train_*_10test.json"):
            _ensure_repo_child(path).unlink()

    if RERUN_ANALYSIS_DIR.exists():
        for train_size in ALL_FRIENDS_TRAIN_SIZES:
            path = RERUN_ANALYSIS_DIR / f"encoding_{train_size}train_10test_snapshot"
            resolved = _ensure_repo_child(path)
            if resolved.exists():
                shutil.rmtree(resolved)


def _resolve_from_config(config_path: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = config_path.parent / path
    return path.resolve()


def _manifest_ref(path: Path, manifest_dir: Path) -> str:
    """Return a manifest-relative path, falling back to absolute if needed."""

    import os

    return os.path.relpath(Path(path).resolve(), manifest_dir.resolve())


def _repo_ref(path: Path) -> str:
    return Path(path).resolve().relative_to(REPO_ROOT).as_posix()


def _load_round8_config() -> tuple[dict[str, Any], Path, Path]:
    config = _read_json(ROUND8_CONFIG)
    output_root = _resolve_from_config(ROUND8_CONFIG, config["output_root"])
    h5_file = _resolve_from_config(ROUND8_CONFIG, config["h5_file"])
    return config, output_root, h5_file


def _subset_episodes(config: dict[str, Any], train_size: int) -> list[dict[str, Any]]:
    train = [episode for episode in config["episodes"] if episode["split"] == "train"]
    val = [episode for episode in config["episodes"] if episode["split"] == "val"]
    test = [episode for episode in config["episodes"] if episode["split"] == "test"]
    if len(train) < train_size:
        raise ValueError(f"Round8 config has only {len(train)} train episodes, need {train_size}.")
    if not val or not test:
        raise ValueError("Round8 config must contain non-empty val and test splits.")
    return [*train[:train_size], *val, *test]


def _write_subset_config(config: dict[str, Any], train_size: int, episodes: list[dict[str, Any]]) -> Path:
    subset = dict(config)
    subset["version"] = f"friends_round8_every10_{train_size}train_10test_encoding_20260630"
    subset["episodes"] = episodes
    path = CONFIG_OUTPUT_DIR / f"train_{train_size:03d}_10test.json"
    _write_json(path, subset)
    return path


def _write_encoding_inputs(
    *,
    config: dict[str, Any],
    output_root: Path,
    h5_file: Path,
    episodes: list[dict[str, Any]],
    snapshot_dir: Path,
) -> tuple[Path, Path]:
    manifest_path = snapshot_dir / "roi_encoding_manifest.jsonl"
    schema_path = snapshot_dir / "roi_schemas.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    rois = list(config["rois"])

    with manifest_path.open("w", encoding="utf-8") as handle:
        for episode in episodes:
            roi_features = {}
            for roi_id in rois:
                feature_path = (
                    output_root
                    / "rois"
                    / roi_id
                    / "scores"
                    / episode["episode_id"]
                    / "tr_features.jsonl"
                )
                if not feature_path.exists():
                    raise FileNotFoundError(f"Missing feature file: {feature_path}")
                roi_features[roi_id] = _manifest_ref(feature_path, manifest_path.parent)
            row = {
                "sample_id": f"{config['subject_id']}_{episode['episode_id']}",
                "subject_id": config["subject_id"],
                "feature_set_name": "roi_scores",
                "split": episode["split"],
                "roi_features": roi_features,
                "h5_file": _manifest_ref(h5_file, manifest_path.parent),
                "h5_dataset": episode["h5_dataset"],
                "feature_trim_start_tr": 0,
                "feature_trim_end_tr": 0,
                "fmri_trim_start_tr": config["encoding_trim"]["fmri_trim_start_tr"],
                "fmri_trim_end_tr": config["encoding_trim"]["fmri_trim_end_tr"],
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    schema_mapping = {
        "roi_schemas": {
            roi_id: _manifest_ref(output_root / "rois" / roi_id / "region_schema.json", schema_path.parent)
            for roi_id in rois
        },
    }
    _write_json(schema_path, schema_mapping)
    return manifest_path, schema_path


def _run_encoding(train_size: int) -> EncodingMetrics:
    config, output_root, h5_file = _load_round8_config()
    episodes = _subset_episodes(config, train_size)
    _write_subset_config(config, train_size, episodes)
    snapshot_dir = RERUN_ANALYSIS_DIR / f"encoding_{train_size}train_10test_snapshot"
    manifest_path, schema_path = _write_encoding_inputs(
        config=config,
        output_root=output_root,
        h5_file=h5_file,
        episodes=episodes,
        snapshot_dir=snapshot_dir,
    )
    fit_roi_encoding_from_manifest(
        RoiEncodingInput(
            manifest=manifest_path,
            roi_schemas=schema_path,
            atlas_labels=_resolve_from_config(ROUND8_CONFIG, config["atlas_labels"]),
            output_dir=snapshot_dir,
        ),
        RidgeEncodingConfig(
            lags=tuple(int(lag) for lag in config["lags"]),
            alphas=tuple(float(alpha) for alpha in config["alphas"]),
        ),
    )
    return _read_metrics(
        train_size=train_size,
        group_summary=snapshot_dir / "group_summary.json",
        note=f"round8 prefix/{train_size}train expanded 10-test rerun snapshot",
    )


def _read_metrics(*, train_size: int, group_summary: Path, note: str) -> EncodingMetrics:
    payload = _read_json(group_summary)
    subject = payload["subjects"][0]
    return EncodingMetrics(
        train_size=train_size,
        mean_test_pearson=float(payload["mean_subject_mean_test_pearson"]),
        median_test_pearson=float(payload["mean_subject_median_test_pearson"]),
        best_alpha=float(subject["best_alpha"]),
        n_retained_parcels=int(subject["n_retained_parcels"]),
        n_test_trs=int(subject["n_test_trs"]),
        source=group_summary,
        source_note=note,
    )


def _collect_friend_metrics() -> list[EncodingMetrics]:
    return [_run_encoding(train_size) for train_size in ALL_FRIENDS_TRAIN_SIZES]


def _format_metric(value: float) -> str:
    return repr(float(value))


def _update_comparison_csv(friend_metrics: list[EncodingMetrics]) -> list[dict[str, str]]:
    csv_path = COMPARISON_STEM.with_suffix(".csv")
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    replacement_sizes = {metric.train_size for metric in friend_metrics}
    preserved_rows = [
        row
        for row in rows
        if not (row["series"] == "Friends" and int(float(row["train_size"])) in replacement_sizes)
    ]
    new_rows = [
        {
            "series": "Friends",
            "train_size": str(metric.train_size),
            "mean_test_pearson": _format_metric(metric.mean_test_pearson),
            "median_test_pearson": _format_metric(metric.median_test_pearson),
            "best_alpha": _format_metric(metric.best_alpha),
            "n_retained_parcels": str(metric.n_retained_parcels),
            "n_test_trs": str(metric.n_test_trs),
            "source": _repo_ref(metric.source),
            "source_note": metric.source_note,
        }
        for metric in friend_metrics
    ]
    updated = [*preserved_rows, *new_rows]
    updated.sort(key=lambda row: (row["series"] != "Friends", float(row["train_size"])))

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(updated)
    return updated


def _series(rows: list[dict[str, str]], name: str) -> tuple[list[float], list[float]]:
    selected = [row for row in rows if row["series"] == name]
    selected.sort(key=lambda row: float(row["train_size"]))
    return (
        [float(row["train_size"]) for row in selected],
        [float(row["mean_test_pearson"]) for row in selected],
    )


def _plot(rows: list[dict[str, str]]) -> None:
    friends_x, friends_y = _series(rows, "Friends")
    tribe_x, tribe_y = _series(rows, "Tribe")

    fig, ax = plt.subplots(figsize=(10.2, 5.8))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(left=0.09, right=0.98, bottom=0.14, top=0.83)

    ax.plot(
        friends_x,
        friends_y,
        marker="o",
        linewidth=2.4,
        color="#2563eb",
        label="Friends ROI mean",
    )
    ax.plot(
        tribe_x,
        tribe_y,
        marker="s",
        linewidth=2.4,
        color="#dc2626",
        label="Tribe parcel mean",
    )
    fig.text(
        0.09,
        0.94,
        "Train Size Sweep: Friends vs Tribe",
        ha="left",
        va="top",
        fontsize=16,
        fontweight="bold",
        color="#020617",
    )
    fig.text(
        0.09,
        0.895,
        "Friends points are rerun with the same expanded 10-test S06 split; scoring features are reused.",
        ha="left",
        va="top",
        fontsize=9.5,
        color="#475569",
    )
    ax.set_xlabel("Train size (episodes)")
    ax.set_ylabel("Mean test Pearson r")
    ax.grid(True, axis="both", alpha=0.24)
    ax.legend(frameon=False, loc="lower right")
    ax.set_xlim(0, max(max(friends_x), max(tribe_x)) + 8)

    fig.savefig(COMPARISON_STEM.with_suffix(".png"), dpi=240)
    fig.savefig(COMPARISON_STEM.with_suffix(".pdf"))
    plt.close(fig)


def main() -> None:
    _clean_previous_curve_outputs()
    friend_metrics = _collect_friend_metrics()
    rows = _update_comparison_csv(friend_metrics)
    _plot(rows)
    print("Updated train-size comparison:")
    for metric in friend_metrics:
        print(
            f"  Friends {metric.train_size}: "
            f"mean={metric.mean_test_pearson:.12f}, "
            f"median={metric.median_test_pearson:.12f}, "
            f"alpha={metric.best_alpha:g}, test_trs={metric.n_test_trs}",
        )
    print(f"Wrote {_repo_ref(COMPARISON_STEM.with_suffix('.csv'))}")
    print(f"Wrote {_repo_ref(COMPARISON_STEM.with_suffix('.png'))}")
    print(f"Wrote {_repo_ref(COMPARISON_STEM.with_suffix('.pdf'))}")


if __name__ == "__main__":
    main()
