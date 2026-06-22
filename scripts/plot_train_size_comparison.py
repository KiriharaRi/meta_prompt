"""Plot Friends and Tribe train-size sweep results on one axis.

This is a lightweight analysis script, not a maintained pipeline command. It
keeps the source-specific ``train_size`` values as episode counts and plots raw
mean Pearson values without uncertainty bands.
"""

from __future__ import annotations

import csv
from argparse import ArgumentParser, Namespace
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ANALYSIS_CSV = (
    REPO_ROOT / "friends" / "analysis" / "train_size_sweep_20260622_fresh" / "summary.csv"
)
DEFAULT_TRIBE_CSV = REPO_ROOT / "friends" / "tribe" / "tribe_train_size_test_performance.csv"
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "friends"
    / "analysis"
    / "train_size_sweep_20260622_fresh"
    / "train_size_comparison_friends_vs_tribe.png"
)


@dataclass(frozen=True)
class PlotSeries:
    """Numeric x/y values for one train-size result source."""

    label: str
    train_sizes: tuple[float, ...]
    pearsons: tuple[float, ...]


def _resolve_repo_path(raw_path: str) -> Path:
    """Resolve CLI paths relative to the repository root for repeatable runs."""

    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _read_series(
    *,
    csv_path: Path,
    label: str,
    pearson_column: str,
) -> PlotSeries:
    """Read and validate one train-size CSV.

    Missing required columns fail early so the plot cannot silently mix the
    wrong metric or an unrelated result file.
    """

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required_columns = {"train_size", pearson_column}
        missing_columns = required_columns.difference(reader.fieldnames or ())
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"{csv_path} is missing required column(s): {missing}")

        rows = []
        for row_number, row in enumerate(reader, start=2):
            try:
                train_size = float(row["train_size"])
                pearson = float(row[pearson_column])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid numeric value in {csv_path} row {row_number}") from exc
            rows.append((train_size, pearson))

    if not rows:
        raise ValueError(f"{csv_path} has no data rows.")

    rows.sort(key=lambda item: item[0])
    return PlotSeries(
        label=label,
        train_sizes=tuple(item[0] for item in rows),
        pearsons=tuple(item[1] for item in rows),
    )


def _plot_comparison(*, analysis: PlotSeries, tribe: PlotSeries, output_path: Path) -> None:
    """Render both train-size sweeps on one shared set of axes."""

    fig, ax = plt.subplots(figsize=(9.5, 5.5), constrained_layout=True)

    ax.plot(
        analysis.train_sizes,
        analysis.pearsons,
        marker="o",
        linewidth=2.4,
        color="#2563eb",
        label=analysis.label,
    )
    ax.plot(
        tribe.train_sizes,
        tribe.pearsons,
        marker="s",
        linewidth=2.4,
        color="#dc2626",
        label=tribe.label,
    )
    ax.set_title("Train Size Sweep: Friends vs Tribe")
    ax.set_xlabel("Train size (episodes)")
    ax.set_ylabel("Mean test Pearson r")
    ax.grid(True, axis="both", alpha=0.25)
    ax.legend(frameon=False)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220)
    plt.close(fig)


def _parse_args() -> Namespace:
    """Parse paths for the one-off plotting script."""

    parser = ArgumentParser(
        description="Plot Friends analysis and Tribe train-size results on one axis.",
    )
    parser.add_argument(
        "--analysis-csv",
        default=str(DEFAULT_ANALYSIS_CSV.relative_to(REPO_ROOT)),
        help="Friends analysis train-size summary CSV.",
    )
    parser.add_argument(
        "--tribe-csv",
        default=str(DEFAULT_TRIBE_CSV.relative_to(REPO_ROOT)),
        help="Tribe train-size performance CSV.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT.relative_to(REPO_ROOT)),
        help="PNG output path.",
    )
    return parser.parse_args()


def main() -> None:
    """Load both CSVs and write the comparison figure."""

    args = _parse_args()
    analysis = _read_series(
        csv_path=_resolve_repo_path(args.analysis_csv),
        label="Friends ROI mean",
        pearson_column="mean_subject_mean_test_pearson",
    )
    tribe = _read_series(
        csv_path=_resolve_repo_path(args.tribe_csv),
        label="Tribe parcel mean",
        pearson_column="mean_test_pearson",
    )
    _plot_comparison(
        analysis=analysis,
        tribe=tribe,
        output_path=_resolve_repo_path(args.output),
    )


if __name__ == "__main__":
    main()
