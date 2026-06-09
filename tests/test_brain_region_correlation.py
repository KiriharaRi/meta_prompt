from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from brain_region_pipeline.cli import main
from brain_region_pipeline.scoring.correlation import compute_score_correlations


def _score_row(start_s: float, end_s: float, linear: float, inverse: float, constant: float) -> dict:
    return {
        "start_s": start_s,
        "end_s": end_s,
        "description": f"Segment {start_s:g}-{end_s:g}.",
        "dimension_scores": {
            "linear": linear,
            "inverse": inverse,
            "constant": constant,
        },
    }


def _gt_row(start_s: float, end_s: float, agitation: float) -> dict:
    return {
        "start_seconds": start_s,
        "end_seconds": end_s,
        "gt_emotions": {"agitation": agitation},
    }


class ScoreCorrelationTests(unittest.TestCase):
    """Tests for Pearson correlation between segment scores and GT rows."""

    def test_compute_score_correlations_handles_lag_and_constant_dimensions(self) -> None:
        score_rows = [
            _score_row(0.0, 1.0, 1.0, 4.0, 0.0),
            _score_row(1.0, 2.0, 2.0, 3.0, 0.0),
            _score_row(2.0, 3.0, 3.0, 2.0, 0.0),
            _score_row(3.0, 4.0, 4.0, 1.0, 0.0),
        ]
        gt_rows = [
            _gt_row(0.0, 1.0, 10.0),
            _gt_row(1.0, 2.0, 20.0),
            _gt_row(2.0, 3.0, 30.0),
            _gt_row(3.0, 4.0, 40.0),
        ]

        rows = compute_score_correlations(
            score_rows=score_rows,
            gt_rows=gt_rows,
            target_emotion="agitation",
            lag_s=1.0,
        )
        by_dimension = {row["dimension"]: row for row in rows}

        self.assertAlmostEqual(by_dimension["linear"]["pearson"], 1.0)
        self.assertAlmostEqual(by_dimension["inverse"]["pearson"], -1.0)
        self.assertIsNone(by_dimension["constant"]["pearson"])
        self.assertEqual(by_dimension["linear"]["n"], 3)
        self.assertEqual(by_dimension["constant"]["nonzero"], 0)

    def test_cli_writes_pearson_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            scores_path = root / "scores.jsonl"
            gt_path = root / "gt.jsonl"
            output_path = root / "pearson.json"
            scores = [
                _score_row(0.0, 1.0, 1.0, 3.0, 0.0),
                _score_row(1.0, 2.0, 2.0, 2.0, 0.0),
                _score_row(2.0, 3.0, 3.0, 1.0, 0.0),
            ]
            gt_rows = [
                _gt_row(0.0, 1.0, 2.0),
                _gt_row(1.0, 2.0, 4.0),
                _gt_row(2.0, 3.0, 6.0),
            ]
            scores_path.write_text(
                "".join(json.dumps(row) + "\n" for row in scores),
                encoding="utf-8",
            )
            gt_path.write_text(
                "".join(json.dumps(row) + "\n" for row in gt_rows),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                main(
                    [
                        "correlate-scores",
                        "--scores-jsonl",
                        str(scores_path),
                        "--gt-jsonl",
                        str(gt_path),
                        "--lag-s",
                        "0",
                        "--output-file",
                        str(output_path),
                    ],
                )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertIn("Wrote Pearson correlations", stdout.getvalue())
        self.assertEqual(payload["target"], "agitation")
        self.assertEqual(payload["lag_s"], 0.0)
        self.assertEqual(payload["rows"][0]["dimension"], "linear")
        self.assertAlmostEqual(payload["rows"][0]["pearson"], 1.0)


if __name__ == "__main__":
    unittest.main()
