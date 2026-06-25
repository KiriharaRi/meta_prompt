from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import h5py
import numpy as np

from brain_region_pipeline.atlas.roi_config import (
    RoiDefinition,
    load_roi_definitions,
    select_roi_definitions,
)
from brain_region_pipeline.core.dependencies import default_dependencies
from brain_region_pipeline.pilot.artifacts import PilotArtifacts
from brain_region_pipeline.pilot.concurrent import ConcurrentPilotStages
from brain_region_pipeline.pilot.runner import PilotConfig, load_pilot_config
from brain_region_pipeline.schema_design.runner import DomainPoolInput, RegionSchemaInput
from brain_region_pipeline.scoring.runner import ScoreDescriptionsInput
from brain_region_pipeline.scoring.summary_generator import SummaryDescriptionsInput


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


def _load_config_and_rois(config_file: Path) -> tuple[PilotConfig, list[RoiDefinition]]:
    config = load_pilot_config(config_file)
    roi_definitions = load_roi_definitions(config.roi_definitions)
    rois = select_roi_definitions(roi_definitions, config.rois)
    return config, rois


class Friends14RoiConcurrentScriptTests(unittest.TestCase):
    """Smoke tests for the config-driven concurrent Friends runner."""

    def test_script_does_not_import_7roi_private_helpers(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")

        self.assertNotIn("run_friends_7roi_vertex_pilot", source)

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
            stages = Mock()

            def fake_scoring_jobs(*_args, **_kwargs) -> None:
                calls.append("scoring")

            stages.run_scoring_jobs.side_effect = fake_scoring_jobs
            with (
                patch.object(script, "ConcurrentPilotStages", return_value=stages),
                patch.object(script, "_run_full") as run_full,
            ):
                with redirect_stdout(io.StringIO()):
                    script.main(["--config", str(config_file), "--stage", "scoring"])

        self.assertEqual(calls, ["scoring"])
        run_full.assert_not_called()
        stages.write_manifest.assert_not_called()
        stages.run_encoding.assert_not_called()
        stages.refresh_encoding.assert_not_called()

    def test_concurrent_stage_interface_runs_scoring_with_artifact_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = _write_minimal_pilot_config(Path(tmpdir))
            config, rois = _load_config_and_rois(config_file)
            artifacts = PilotArtifacts(config)
            stages = ConcurrentPilotStages(
                config=config,
                deps=default_dependencies(),
                log=lambda _message: None,
            )

            with patch(
                "brain_region_pipeline.pilot.concurrent.score_descriptions_from_file",
            ) as score:
                stages.run_scoring_jobs(
                    rois,
                    [config.episodes[0]],
                    workers=1,
                    overwrite_scoring=True,
                )

            score_input = score.call_args.args[0]

        self.assertIsInstance(score_input, ScoreDescriptionsInput)
        self.assertEqual(score_input.region_schema, artifacts.region_schema_path("VMPFC"))
        self.assertEqual(
            score_input.output_dir,
            artifacts.scoring_dir("VMPFC", config.episodes[0]),
        )
        self.assertEqual(score_input.summary_file, artifacts.summary_path(config.episodes[0]))
        self.assertFalse(score_input.resume)
        self.assertTrue(score_input.overwrite)

    def test_concurrent_stage_interface_runs_summary_with_typed_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = _write_minimal_pilot_config(Path(tmpdir))
            config, _rois = _load_config_and_rois(config_file)
            artifacts = PilotArtifacts(config)
            stages = ConcurrentPilotStages(
                config=config,
                deps=default_dependencies(),
                log=lambda _message: None,
            )

            with patch(
                "brain_region_pipeline.pilot.concurrent.summarize_descriptions_from_file",
            ) as summarize:
                stages.run_summary_jobs(workers=1, skip_existing=False)

            summary_input = summarize.call_args_list[0].args[0]

        self.assertIsInstance(summary_input, SummaryDescriptionsInput)
        self.assertEqual(summary_input.descriptions, config.episodes[0].descriptions)
        self.assertEqual(summary_input.output_file, artifacts.summary_path(config.episodes[0]))

    def test_concurrent_stage_interface_runs_domain_pool_with_typed_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = _write_minimal_pilot_config(Path(tmpdir))
            config, rois = _load_config_and_rois(config_file)
            artifacts = PilotArtifacts(config)
            stages = ConcurrentPilotStages(
                config=config,
                deps=default_dependencies(),
                log=lambda _message: None,
            )

            with (
                patch("brain_region_pipeline.pilot.concurrent.make_domain_pool") as make_pool,
                patch("brain_region_pipeline.pilot.concurrent.confirm_domain_pool_for_pilot"),
                patch.object(ConcurrentPilotStages, "validate_domain_pool"),
            ):
                stages.run_domain_pool_job(roi=rois[0])

            domain_input = make_pool.call_args.args[0]
            domain_config = make_pool.call_args.args[1]

        self.assertIsInstance(domain_input, DomainPoolInput)
        self.assertEqual(domain_input.atlas_labels, config.atlas_labels)
        self.assertEqual(domain_input.output_file, artifacts.domain_pool_draft_path("VMPFC"))
        self.assertEqual(domain_config.target_region, "VMPFC")

    def test_concurrent_stage_interface_runs_schema_with_typed_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = _write_minimal_pilot_config(Path(tmpdir))
            config, rois = _load_config_and_rois(config_file)
            artifacts = PilotArtifacts(config)
            artifacts.domain_pool_auto_confirmed_path("VMPFC").parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            artifacts.domain_pool_auto_confirmed_path("VMPFC").write_text(
                "{}",
                encoding="utf-8",
            )
            expected_domain_pool = artifacts.domain_pool_for_schema("VMPFC")
            stages = ConcurrentPilotStages(
                config=config,
                deps=default_dependencies(),
                log=lambda _message: None,
            )

            with patch("brain_region_pipeline.pilot.concurrent.make_region_schema") as make_schema:
                stages.run_schema_job(roi=rois[0])

            schema_input = make_schema.call_args.args[0]
            schema_config = make_schema.call_args.args[1]

        self.assertIsInstance(schema_input, RegionSchemaInput)
        self.assertEqual(schema_input.atlas_labels, config.atlas_labels)
        self.assertEqual(schema_input.domain_pool, expected_domain_pool)
        self.assertEqual(schema_input.output_file, artifacts.region_schema_path("VMPFC"))
        self.assertEqual(schema_input.roi_definitions, config.roi_definitions)
        self.assertEqual(schema_input.roi_id, "VMPFC")
        self.assertEqual(schema_config.target_region, "VMPFC")


if __name__ == "__main__":
    unittest.main()
