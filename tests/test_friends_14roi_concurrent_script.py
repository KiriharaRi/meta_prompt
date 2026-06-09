from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_friends_14roi_concurrent_pilot.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "run_friends_14roi_concurrent_pilot_test",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load script module: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_labels(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "subregion_func_network_Yeo_updated",
                "Label,subregion_name,region,Yeo_7network,Yeo_17network,,,,,,,",
                "1,A8m,SFG_L_7_1,6,17,,,,,,Yeo  7 Network,",
                "2,A8m,SFG_R_7_1,4,8,,,,,,ID,Network name",
            ],
        )
        + "\n",
        encoding="utf-8",
    )


def _write_minimal_pilot_config(
    root: Path,
    *,
    episodes: list[tuple[str, str]] | None = None,
) -> Path:
    """Create the smallest valid pilot config needed by script smoke tests."""

    episodes = episodes or [
        ("custom_train", "train"),
        ("custom_val", "val"),
        ("custom_test", "test"),
    ]
    labels = root / "brainnetome.csv"
    roi_file = root / "roi_defs.json"
    config_file = root / "pilot.json"
    h5_file = root / "bold.h5"
    _write_labels(labels)
    for episode_id, _ in episodes:
        (root / f"{episode_id}.md").write_text(
            "00:00 - 00:01  Test segment.",
            encoding="utf-8",
        )
    with h5py.File(h5_file, "w") as handle:
        for episode_id, _ in episodes:
            handle.create_dataset(episode_id, data=np.zeros((4, 2), dtype=np.float32))
    roi_file.write_text(
        json.dumps(
            {
                "rois": [
                    {
                        "roi_id": "VMPFC",
                        "display_name": "VMPFC",
                        "selection_rules": [
                            {
                                "label_ids": [1, 2],
                                "networks": [],
                                "sub_regions": [],
                                "hemispheres": [],
                            },
                        ],
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    config_file.write_text(
        json.dumps(
            {
                "roi_definitions": roi_file.name,
                "atlas_labels": labels.name,
                "h5_file": h5_file.name,
                "output_root": "pilot_out",
                "subject_id": "sub-01",
                "rois": ["VMPFC"],
                "episodes": [
                    {
                        "episode_id": episode_id,
                        "split": split,
                        "descriptions": f"{episode_id}.md",
                        "h5_dataset": episode_id,
                    }
                    for episode_id, split in episodes
                ],
            },
        ),
        encoding="utf-8",
    )
    return config_file


class Friends14RoiConcurrentScriptTests(unittest.TestCase):
    """Smoke tests for the config-driven concurrent Friends runner."""

    def test_dry_run_uses_config_episodes_and_workers(self) -> None:
        script = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            episodes = [
                ("custom_train", "train"),
                ("custom_val", "val"),
                ("custom_test", "test"),
            ]
            config_file = _write_minimal_pilot_config(root, episodes=episodes)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                script.main(
                    [
                        "--config",
                        str(config_file),
                        "--dry-run",
                        "--summary-workers",
                        "1",
                        "--domain-workers",
                        "1",
                        "--schema-workers",
                        "1",
                        "--scoring-workers",
                        "1",
                    ],
                )

        output = stdout.getvalue()
        self.assertIn("Dry-run multi-ROI pilot plan", output)
        self.assertIn("Stage: all", output)
        self.assertIn("custom_train, custom_val, custom_test", output)
        self.assertIn("Workers: summary=1, domain=1, schema=1, scoring=1", output)
        self.assertIn("VMPFC=2", output)

    def test_dry_run_reports_selected_stage(self) -> None:
        script = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = _write_minimal_pilot_config(Path(tmpdir))

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                script.main(["--config", str(config_file), "--stage", "scoring", "--dry-run"])

        self.assertIn("Stage: scoring", stdout.getvalue())

    def test_retry_failed_batches_rejects_non_all_stage(self) -> None:
        script = _load_script_module()

        with self.assertRaisesRegex(ValueError, "retry-failed-batches.*non-all --stage"):
            script.parse_args(["--stage", "scoring", "--retry-failed-batches"])

    def test_scoring_stage_dispatches_only_scoring_jobs(self) -> None:
        script = _load_script_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = _write_minimal_pilot_config(Path(tmpdir))
            calls: list[str] = []

            def fake_scoring_jobs(*_args, **_kwargs) -> None:
                calls.append("scoring")

            with (
                patch.object(script, "_run_scoring_jobs", side_effect=fake_scoring_jobs),
                patch.object(script, "_run_full") as run_full,
                patch.object(script, "_write_manifest") as write_manifest,
                patch.object(script, "_run_encoding") as run_encoding,
            ):
                with redirect_stdout(io.StringIO()):
                    script.main(["--config", str(config_file), "--stage", "scoring"])

        self.assertEqual(calls, ["scoring"])
        run_full.assert_not_called()
        write_manifest.assert_not_called()
        run_encoding.assert_not_called()


if __name__ == "__main__":
    unittest.main()
