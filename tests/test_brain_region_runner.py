from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from brain_region_pipeline.cli import main


class RunnerSmokeTests(unittest.TestCase):
    """Smoke tests for the currently supported CLI stages."""

    def test_main_without_subcommand_prints_current_help(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            main([])
        help_text = stdout.getvalue()

        self.assertIn("make-domain-pool", help_text)
        self.assertIn("make-region-schema", help_text)
        self.assertIn("summarize-descriptions", help_text)
        self.assertIn("score-descriptions", help_text)
        self.assertIn("correlate-scores", help_text)
        self.assertIn("fit-roi-encoding", help_text)
        self.assertIn("run-multi-roi-pilot", help_text)
        self.assertNotIn("fit-ridge-encoding", help_text)
        self.assertNotIn("fit-multi-roi-encoding", help_text)
        self.assertNotIn("make-module-prompt", help_text)
        self.assertNotIn("encode", help_text)
        self.assertNotIn("make-module-pool", help_text)
        self.assertNotIn("build-features", help_text)

    def test_make_domain_pool_help_is_available(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as context:
            main(["make-domain-pool", "--help"])

        self.assertEqual(context.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("--proposal-runs", help_text)
        self.assertIn("--provider", help_text)
        self.assertIn("--model", help_text)

    def test_correlate_scores_help_is_available(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as context:
            main(["correlate-scores", "--help"])

        self.assertEqual(context.exception.code, 0)
        self.assertIn("--scores-jsonl", stdout.getvalue())
        self.assertIn("--lag-s", stdout.getvalue())

    def test_score_descriptions_help_exposes_resume_controls(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as context:
            main(["score-descriptions", "--help"])

        self.assertEqual(context.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("--resume", help_text)
        self.assertIn("--overwrite", help_text)
        self.assertIn("--provider", help_text)

    def test_summarize_descriptions_help_is_available(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as context:
            main(["summarize-descriptions", "--help"])

        self.assertEqual(context.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("--descriptions", help_text)
        self.assertIn("--output-file", help_text)
        self.assertIn("--provider", help_text)
        self.assertIn("--model", help_text)

    def test_fit_roi_encoding_help_is_available(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as context:
            main(["fit-roi-encoding", "--help"])

        self.assertEqual(context.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("--manifest", help_text)
        self.assertIn("--roi-schemas", help_text)
        self.assertIn("--atlas-labels", help_text)

    def test_multi_roi_pilot_help_is_available(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout), self.assertRaises(SystemExit) as context:
            main(["run-multi-roi-pilot", "--help"])

        self.assertEqual(context.exception.code, 0)
        self.assertIn("--dry-run", stdout.getvalue())
        self.assertIn("--stage", stdout.getvalue())

    def test_encode_subcommand_is_removed(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as context:
            main(["encode", "--help"])

        self.assertEqual(context.exception.code, 2)
        self.assertIn("invalid choice: 'encode'", stderr.getvalue())

    def test_old_encoding_subcommands_are_removed(self) -> None:
        for command in ("fit-ridge-encoding", "fit-multi-roi-encoding"):
            with self.subTest(command=command):
                stderr = io.StringIO()
                with redirect_stderr(stderr), self.assertRaises(SystemExit) as context:
                    main([command, "--help"])

                self.assertEqual(context.exception.code, 2)
                self.assertIn(f"invalid choice: '{command}'", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
