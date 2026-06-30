"""Plot ROI-level encoding performance from an encoding summary JSON.

This is a lightweight analysis script for presentation-ready figures. It keeps
the 95-train Friends snapshot as the default input, but also accepts compact
baseline summaries that expose top-level ``mean_test_pearson`` and
``roi_summaries`` fields. It never reruns scoring or encoding.
"""

from __future__ import annotations

import csv
import json
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY = (
    REPO_ROOT
    / "friends"
    / "analysis"
    / "train_size_sweep_20260628_round6"
    / "encoding_95train_all_scored_snapshot"
    / "group_summary.json"
)
DEFAULT_OUTPUT_STEM = (
    REPO_ROOT
    / "friends"
    / "analysis"
    / "train_size_sweep_20260628_round6"
    / "roi_performance_95train_all_scored"
)


@dataclass(frozen=True)
class RoiPerformance:
    """One ROI's plotting and audit metrics from the encoding summary."""

    rank: int
    roi_id: str
    mean_test_pearson: float
    median_test_pearson: float
    retained_parcels: int
    total_selected_parcels: int


@dataclass(frozen=True)
class PerformanceSummary:
    """Presentation-facing summary values shared by the chart and CSV."""

    overall_mean_test_pearson: float
    overall_median_test_pearson: float
    best_alpha: float | None
    n_test_trs: int | None
    rows: tuple[RoiPerformance, ...]


def _resolve_repo_path(raw_path: str) -> Path:
    """Resolve CLI paths relative to the repository root."""

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _load_performance(summary_path: Path) -> PerformanceSummary:
    """Load ROI metrics and fail early if the expected contract is missing."""

    with summary_path.open(encoding="utf-8") as handle:
        summary = json.load(handle)

    roi_summaries = summary.get("roi_summaries")
    if not isinstance(roi_summaries, dict) or not roi_summaries:
        raise ValueError(f"{summary_path} does not contain non-empty roi_summaries.")

    subjects = summary.get("subjects") or []
    subject_roi_summaries = {}
    best_alpha = None
    n_test_trs = None
    if subjects:
        first_subject = subjects[0]
        subject_roi_summaries = first_subject.get("roi_summaries") or {}
        best_alpha = first_subject.get("best_alpha")
        n_test_trs = first_subject.get("n_test_trs")

    rows: list[RoiPerformance] = []
    metric_key = (
        "mean_subject_mean_test_pearson"
        if all("mean_subject_mean_test_pearson" in row for row in roi_summaries.values())
        else "mean_test_pearson"
    )
    sorted_items = sorted(
        roi_summaries.items(),
        key=lambda item: float(item[1][metric_key]),
        reverse=True,
    )
    for rank, (roi_id, group_row) in enumerate(sorted_items, start=1):
        subject_row = subject_roi_summaries.get(roi_id, {})
        median_value = subject_row.get(
            "median_test_pearson",
            group_row.get(
                "median_subject_mean_test_pearson",
                group_row.get("median_test_pearson"),
            ),
        )
        rows.append(
            RoiPerformance(
                rank=rank,
                roi_id=roi_id,
                mean_test_pearson=float(group_row[metric_key]),
                median_test_pearson=float(median_value),
                retained_parcels=int(
                    subject_row.get("n_retained_parcels", group_row.get("n_retained_parcels", 0))
                ),
                total_selected_parcels=int(
                    subject_row.get(
                        "n_total_selected_parcels",
                        group_row.get("n_total_selected_parcels", 0),
                    )
                ),
            )
        )

    overall_mean = summary.get("mean_subject_mean_test_pearson", summary.get("mean_test_pearson"))
    overall_median = summary.get(
        "mean_subject_median_test_pearson",
        summary.get("median_test_pearson", summary.get("median_subject_mean_test_pearson")),
    )
    if overall_mean is None or overall_median is None:
        raise ValueError(f"{summary_path} is missing overall mean/median Pearson metrics.")

    return PerformanceSummary(
        overall_mean_test_pearson=float(overall_mean),
        overall_median_test_pearson=float(overall_median),
        best_alpha=float(best_alpha) if best_alpha is not None else None,
        n_test_trs=int(n_test_trs) if n_test_trs is not None else None,
        rows=tuple(rows),
    )


def _write_csv(csv_path: Path, summary: PerformanceSummary) -> None:
    """Write the exact values used in the figure for traceability."""

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "rank",
                "roi_id",
                "mean_test_pearson",
                "median_test_pearson",
                "n_retained_parcels",
                "n_total_selected_parcels",
            ],
        )
        writer.writeheader()
        for row in summary.rows:
            writer.writerow(
                {
                    "rank": row.rank,
                    "roi_id": row.roi_id,
                    "mean_test_pearson": f"{row.mean_test_pearson:.12f}",
                    "median_test_pearson": f"{row.median_test_pearson:.12f}",
                    "n_retained_parcels": row.retained_parcels,
                    "n_total_selected_parcels": row.total_selected_parcels,
                }
            )


def _plot_performance(
    *,
    output_stem: Path,
    summary: PerformanceSummary,
    title: str,
    subtitle: str,
) -> None:
    """Render a PPT-friendly horizontal bar chart."""

    rows_for_plot = tuple(reversed(summary.rows))
    labels = [row.roi_id.replace("_", " ") for row in rows_for_plot]
    values = [row.mean_test_pearson for row in rows_for_plot]
    parcel_labels = [
        f"{row.mean_test_pearson:.3f}  ({row.retained_parcels} parcels)"
        for row in rows_for_plot
    ]

    # Accent the four highest-performing ROIs, matching the PPT's "highlighted
    # higher-performing ROIs" reading pattern without changing the metric.
    top_roi_ids = {row.roi_id for row in summary.rows[:4]}
    colors = [
        "#0f766e" if row.roi_id in top_roi_ids else "#64748b"
        for row in rows_for_plot
    ]

    fig, ax = plt.subplots(figsize=(10.5, 6.4))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    fig.subplots_adjust(left=0.15, right=0.98, bottom=0.12, top=0.8)

    bars = ax.barh(labels, values, color=colors, edgecolor="none", height=0.68)
    ax.axvline(
        summary.overall_mean_test_pearson,
        color="#dc2626",
        linestyle="--",
        linewidth=1.4,
        alpha=0.85,
        label=f"Overall mean r = {summary.overall_mean_test_pearson:.3f}",
    )

    for bar, label in zip(bars, parcel_labels, strict=True):
        ax.text(
            bar.get_width() + 0.004,
            bar.get_y() + bar.get_height() / 2,
            label,
            va="center",
            ha="left",
            fontsize=9,
            color="#334155",
        )

    subtitle_parts = [subtitle]
    if summary.n_test_trs is not None:
        subtitle_parts.append(f"test TRs: {summary.n_test_trs}")
    if summary.best_alpha is not None:
        subtitle_parts.append(f"best alpha: {summary.best_alpha:g}")

    fig.text(
        0.15,
        0.955,
        title,
        ha="left",
        va="top",
        fontsize=17,
        fontweight="bold",
        color="#020617",
    )
    fig.text(
        0.15,
        0.905,
        " | ".join(subtitle_parts),
        ha="left",
        va="top",
        fontsize=10,
        color="#475569",
    )
    ax.set_xlabel("Mean test Pearson r")
    ax.set_ylabel("")
    ax.set_xlim(0, max(values) + 0.055)
    ax.grid(True, axis="x", alpha=0.22)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_color("#cbd5e1")
    ax.tick_params(axis="y", length=0)
    ax.legend(frameon=False, loc="lower right")

    output_stem.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_stem.with_suffix(".png"), dpi=240)
    fig.savefig(output_stem.with_suffix(".pdf"))
    plt.close(fig)


def _parse_args() -> Namespace:
    """Parse CLI paths for the one-off 95-train ROI plot."""

    parser = ArgumentParser(
        description="Plot ROI-level performance for the 95-train Friends snapshot.",
    )
    parser.add_argument(
        "--summary",
        default=str(DEFAULT_SUMMARY.relative_to(REPO_ROOT)),
        help="Path to the 95-train group_summary.json.",
    )
    parser.add_argument(
        "--output-stem",
        default=str(DEFAULT_OUTPUT_STEM.relative_to(REPO_ROOT)),
        help="Output path without extension; writes .csv, .png, and .pdf.",
    )
    parser.add_argument(
        "--title",
        default="ROI-Level Encoding Performance",
        help="Figure title.",
    )
    parser.add_argument(
        "--subtitle",
        default="95 train episodes | validation: 5 episodes | held-out test: 4 s06 episodes",
        help="Figure subtitle shown under the title.",
    )
    return parser.parse_args()


def main() -> None:
    """Write trace CSV and presentation-ready chart files."""

    args = _parse_args()
    summary_path = _resolve_repo_path(args.summary)
    output_stem = _resolve_repo_path(args.output_stem)

    summary = _load_performance(summary_path)
    _write_csv(output_stem.with_suffix(".csv"), summary)
    _plot_performance(
        output_stem=output_stem,
        summary=summary,
        title=args.title,
        subtitle=args.subtitle,
    )

    print(f"Wrote {output_stem.with_suffix('.csv')}")
    print(f"Wrote {output_stem.with_suffix('.png')}")
    print(f"Wrote {output_stem.with_suffix('.pdf')}")


if __name__ == "__main__":
    main()
