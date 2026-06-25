from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import h5py
import numpy as np

from brain_region_pipeline.cli import main
from brain_region_pipeline.atlas.models import SelectionRule
from brain_region_pipeline.atlas.roi_config import load_roi_definitions, select_roi_definitions
from brain_region_pipeline.core.config import (
    AIHUBMIX_GENERATION_PROVIDER,
    DEFAULT_AIHUBMIX_MODEL,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_GENERATION_PROVIDER,
)
from brain_region_pipeline.encoding.manifest import load_roi_encoding_manifest
from brain_region_pipeline.encoding.runner import RoiEncodingInput
from brain_region_pipeline.pilot.artifacts import PilotArtifacts
from brain_region_pipeline.pilot.runner import (
    PilotConfig,
    PilotEncodingTrim,
    _run_domain_pools,
    _run_encoding,
    _run_schemas,
    load_pilot_config,
)
from brain_region_pipeline.schema_design.runner import DomainPoolInput, RegionSchemaInput
from brain_region_pipeline.schema_design.domain_models import CuratedDomain
from brain_region_pipeline.schema_design.schema_models import DimensionSpec, RegionFeatureSchema


def _domain() -> CuratedDomain:
    return CuratedDomain(
        domain_id="emotion_experience",
        definition="Viewer emotional experience.",
        region_relevance="Relevant to the target ROI.",
        scoreability_note="Use text evidence.",
        source_domain_ids=("required_emotion_experience",),
        source_runs=(0,),
        proposal_frequency=1,
        consolidation_rationale="Required anchor domain.",
    )


def _dimension(dimension_id: str) -> DimensionSpec:
    return DimensionSpec(
        dimension_id=dimension_id,
        definition=f"{dimension_id} intensity.",
        domain="emotion_experience",
        score_min=0.0,
        score_max=10.0,
        trigger_list=("cue A", "cue B", "cue C"),
        graded_anchors={str(score): "absent" if score == 0 else "present" for score in range(11)},
        calibration_examples=(
            {"scene": "No cue.", "score": 0},
            {"scene": "Strong cue.", "score": 8},
        ),
        scoreability_note="Use dense-description evidence.",
        exclusion_note="Exclude unrelated events.",
    )


def _schema(roi_id: str, rules: tuple[SelectionRule, ...], dimension_prefix: str) -> RegionFeatureSchema:
    return RegionFeatureSchema(
        target_region=roi_id,
        functional_hypothesis=f"{roi_id} tracks relevant movie features.",
        scoring_instruction="Score from dense descriptions.",
        selection_rules=rules,
        domains=(_domain(),),
        active_domain_ids=("emotion_experience",),
        dimensions=(
            _dimension(f"{dimension_prefix}_one"),
            _dimension(f"{dimension_prefix}_two"),
        ),
    )


def _write_labels(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "subregion_func_network_Yeo_updated",
                "Label,subregion_name,region,Yeo_7network,Yeo_17network,,,,,,,",
                "1,A8m,SFG_L_7_1,6,17,,,,,,Yeo  7 Network,",
                "2,A8m,SFG_R_7_1,4,8,,,,,,ID,Network name",
                "3,A8dl,SFG_L_7_2,7,16,,,,,,7,Default",
                "4,A8dl,SFG_R_7_2,6,13,,,,,,6,Frontoparietal",
            ],
        )
        + "\n",
        encoding="utf-8",
    )


def _features(n_trs: int, offset: float, scale: float) -> np.ndarray:
    time = np.arange(n_trs, dtype=np.float64) + offset
    return np.column_stack([time * scale, (time * time) / (scale + 1.0)])


def _write_features(path: Path, values: np.ndarray) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for idx, vector in enumerate(values):
            handle.write(
                json.dumps(
                    {
                        "tr_index": idx,
                        "tr_start_s": float(idx),
                        "tr_end_s": float(idx + 1),
                        "source_description": f"TR {idx}",
                        "feature_vector": [float(value) for value in vector],
                        "weights": {},
                    },
                )
                + "\n",
            )


def _targets(roi_a: np.ndarray, roi_b: np.ndarray) -> np.ndarray:
    y = np.zeros((roi_a.shape[0], 4), dtype=np.float32)
    y[1:, 0] = roi_a[:-1, 0]
    y[1:, 1] = roi_a[:-1, 0] + roi_b[:-1, 0]
    y[1:, 2] = roi_b[:-1, 0]
    y[:, 3] = np.linspace(0, 1, roi_a.shape[0], dtype=np.float32)
    return y


class MultiRoiEncodingTests(unittest.TestCase):
    """Validate the joint multi-ROI encoding contract."""

    def test_pilot_config_defaults_to_aihubmix_gemini_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_file = root / "pilot.json"
            config_file.write_text(
                json.dumps(
                    {
                        "roi_definitions": "roi_defs.json",
                        "atlas_labels": "brainnetome.csv",
                        "h5_file": "bold.h5",
                        "output_root": "pilot_out",
                        "subject_id": "sub-01",
                        "rois": ["ROI_A"],
                        "episodes": [
                            {
                                "episode_id": "train_ep",
                                "split": "train",
                                "descriptions": "train.md",
                                "h5_dataset": "train",
                            },
                            {
                                "episode_id": "val_ep",
                                "split": "val",
                                "descriptions": "val.md",
                                "h5_dataset": "val",
                            },
                            {
                                "episode_id": "test_ep",
                                "split": "test",
                                "descriptions": "test.md",
                                "h5_dataset": "test",
                            },
                        ],
                    },
                ),
                encoding="utf-8",
            )

            config = load_pilot_config(config_file)

        self.assertEqual(config.generation_provider, DEFAULT_GENERATION_PROVIDER)
        self.assertEqual(config.generation_model, DEFAULT_GENERATION_MODEL)
        self.assertEqual(config.generation_provider, AIHUBMIX_GENERATION_PROVIDER)
        self.assertEqual(config.generation_model, DEFAULT_AIHUBMIX_MODEL)
        self.assertEqual(config.encoding_trim.fmri_trim_start_tr, 5)
        self.assertEqual(config.encoding_trim.fmri_trim_end_tr, 5)

    def test_multi_roi_pilot_dry_run_validates_roi_config_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            labels = root / "brainnetome.csv"
            roi_file = root / "roi_defs.json"
            config_file = root / "pilot.json"
            h5_file = root / "bold.h5"
            _write_labels(labels)
            for name in ("train.md", "val.md", "test.md"):
                (root / name).write_text("00:00 - 00:01  Test segment.", encoding="utf-8")
            with h5py.File(h5_file, "w") as handle:
                handle.create_dataset("train", data=np.zeros((4, 4), dtype=np.float32))
                handle.create_dataset("val", data=np.zeros((4, 4), dtype=np.float32))
                handle.create_dataset("test", data=np.zeros((4, 4), dtype=np.float32))
            roi_file.write_text(
                json.dumps(
                    {
                        "rois": [
                            {
                                "roi_id": "ROI_A",
                                "display_name": "ROI A",
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
                        "rois": ["ROI_A"],
                        "episodes": [
                            {
                                "episode_id": "train_ep",
                                "split": "train",
                                "descriptions": "train.md",
                                "h5_dataset": "train",
                            },
                            {
                                "episode_id": "val_ep",
                                "split": "val",
                                "descriptions": "val.md",
                                "h5_dataset": "val",
                            },
                            {
                                "episode_id": "test_ep",
                                "split": "test",
                                "descriptions": "test.md",
                                "h5_dataset": "test",
                            },
                        ],
                    },
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                main(
                    [
                        "run-multi-roi-pilot",
                        "--config",
                        str(config_file),
                        "--stage",
                        "all",
                        "--dry-run",
                    ],
                )

        self.assertIn("Dry-run multi-ROI pilot plan", stdout.getvalue())
        self.assertIn("ROI_A=2", stdout.getvalue())

    def test_multi_roi_pilot_dry_run_accepts_brainnetome_label_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            labels = root / "brainnetome.csv"
            roi_file = root / "roi_defs.json"
            config_file = root / "pilot.json"
            h5_file = root / "bold.h5"
            _write_labels(labels)
            for name in ("train.md", "val.md", "test.md"):
                (root / name).write_text("00:00 - 00:01  Test segment.", encoding="utf-8")
            with h5py.File(h5_file, "w") as handle:
                handle.create_dataset("train", data=np.zeros((4, 3), dtype=np.float32))
                handle.create_dataset("val", data=np.zeros((4, 3), dtype=np.float32))
                handle.create_dataset("test", data=np.zeros((4, 3), dtype=np.float32))
            roi_file.write_text(
                json.dumps(
                    {
                        "rois": [
                            {
                                "roi_id": "DLPFC",
                                "display_name": "DLPFC",
                                "selection_rules": [
                                    {
                                        "label_ids": [1, 3],
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
                        "rois": ["DLPFC"],
                        "episodes": [
                            {
                                "episode_id": "train_ep",
                                "split": "train",
                                "descriptions": "train.md",
                                "h5_dataset": "train",
                            },
                            {
                                "episode_id": "val_ep",
                                "split": "val",
                                "descriptions": "val.md",
                                "h5_dataset": "val",
                            },
                            {
                                "episode_id": "test_ep",
                                "split": "test",
                                "descriptions": "test.md",
                                "h5_dataset": "test",
                            },
                        ],
                    },
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                main(
                    [
                        "run-multi-roi-pilot",
                        "--config",
                        str(config_file),
                        "--stage",
                        "all",
                        "--dry-run",
                    ],
                )

        self.assertIn("Dry-run multi-ROI pilot plan", stdout.getvalue())
        self.assertIn("DLPFC=2", stdout.getvalue())

    def test_staged_pilot_runs_schema_design_with_typed_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            labels = root / "brainnetome.csv"
            roi_file = root / "roi_defs.json"
            config_file = root / "pilot.json"
            h5_file = root / "bold.h5"
            _write_labels(labels)
            for name in ("train.md", "val.md", "test.md"):
                (root / name).write_text("00:00 - 00:01  Test segment.", encoding="utf-8")
            with h5py.File(h5_file, "w") as handle:
                handle.create_dataset("train", data=np.zeros((4, 4), dtype=np.float32))
                handle.create_dataset("val", data=np.zeros((4, 4), dtype=np.float32))
                handle.create_dataset("test", data=np.zeros((4, 4), dtype=np.float32))
            roi_file.write_text(
                json.dumps(
                    {
                        "rois": [
                            {
                                "roi_id": "ROI_A",
                                "display_name": "ROI A",
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
                        "rois": ["ROI_A"],
                        "episodes": [
                            {
                                "episode_id": "train_ep",
                                "split": "train",
                                "descriptions": "train.md",
                                "h5_dataset": "train",
                            },
                            {
                                "episode_id": "val_ep",
                                "split": "val",
                                "descriptions": "val.md",
                                "h5_dataset": "val",
                            },
                            {
                                "episode_id": "test_ep",
                                "split": "test",
                                "descriptions": "test.md",
                                "h5_dataset": "test",
                            },
                        ],
                    },
                ),
                encoding="utf-8",
            )

            config = load_pilot_config(config_file)
            rois = select_roi_definitions(
                load_roi_definitions(config.roi_definitions),
                config.rois,
            )
            artifacts = PilotArtifacts(config)
            artifacts.domain_pool_auto_confirmed_path("ROI_A").parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            artifacts.domain_pool_auto_confirmed_path("ROI_A").write_text(
                "{}",
                encoding="utf-8",
            )
            expected_domain_pool = artifacts.domain_pool_for_schema("ROI_A")

            with patch("brain_region_pipeline.pilot.runner.make_domain_pool") as make_pool:
                _run_domain_pools(
                    config,
                    rois,
                    deps=object(),
                    auto_confirm=False,
                )
            domain_input = make_pool.call_args.args[0]
            domain_config = make_pool.call_args.args[1]

            with patch("brain_region_pipeline.pilot.runner.make_region_schema") as make_schema:
                _run_schemas(config, rois, deps=object())
            schema_input = make_schema.call_args.args[0]
            schema_config = make_schema.call_args.args[1]

        self.assertIsInstance(domain_input, DomainPoolInput)
        self.assertEqual(domain_input.atlas_labels, config.atlas_labels)
        self.assertEqual(domain_input.output_file, artifacts.domain_pool_draft_path("ROI_A"))
        self.assertEqual(domain_config.target_region, "ROI_A")
        self.assertIsInstance(schema_input, RegionSchemaInput)
        self.assertEqual(schema_input.atlas_labels, config.atlas_labels)
        self.assertEqual(schema_input.domain_pool, expected_domain_pool)
        self.assertEqual(schema_input.output_file, artifacts.region_schema_path("ROI_A"))
        self.assertEqual(schema_input.roi_definitions, config.roi_definitions)
        self.assertEqual(schema_input.roi_id, "ROI_A")
        self.assertEqual(schema_config.target_region, "ROI_A")

    def test_staged_pilot_runs_encoding_with_typed_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = PilotConfig(
                config_path=root / "pilot.json",
                roi_definitions=root / "roi_defs.json",
                atlas_labels=root / "brainnetome.csv",
                h5_file=root / "bold.h5",
                output_root=root / "pilot_out",
                subject_id="sub-01",
                rois=("ROI_A",),
                episodes=(),
                generation_provider=DEFAULT_GENERATION_PROVIDER,
                generation_model=DEFAULT_GENERATION_MODEL,
                proposal_runs=5,
                tr_s=1.49,
                scoring_batch_size=40,
                local_buffer_size=10,
                lags=(1, 3),
                alphas=(0.1, 1.0),
                encoding_trim=PilotEncodingTrim(),
            )
            artifacts = PilotArtifacts(config)

            with patch(
                "brain_region_pipeline.pilot.runner.fit_roi_encoding_from_manifest",
            ) as fit:
                _run_encoding(config)

            encoding_input = fit.call_args.args[0]
            encoding_config = fit.call_args.args[1]

        self.assertIsInstance(encoding_input, RoiEncodingInput)
        self.assertEqual(encoding_input.manifest, artifacts.manifest_path())
        self.assertEqual(
            encoding_input.roi_schemas,
            artifacts.roi_schema_mapping_path(),
        )
        self.assertEqual(encoding_input.atlas_labels, config.atlas_labels)
        self.assertEqual(encoding_input.output_dir, artifacts.encoding_dir())
        self.assertEqual(encoding_config.lags, config.lags)
        self.assertEqual(encoding_config.alphas, config.alphas)

    def test_multi_roi_pilot_manifest_writes_encoding_trim_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            labels = root / "brainnetome.csv"
            roi_file = root / "roi_defs.json"
            config_file = root / "pilot.json"
            h5_file = root / "bold.h5"
            output_root = root / "pilot_out"
            _write_labels(labels)
            for name in ("train.md", "val.md", "test.md"):
                (root / name).write_text("00:00 - 00:01  Test segment.", encoding="utf-8")
            with h5py.File(h5_file, "w") as handle:
                handle.create_dataset("train", data=np.zeros((12, 4), dtype=np.float32))
                handle.create_dataset("val", data=np.zeros((12, 4), dtype=np.float32))
                handle.create_dataset("test", data=np.zeros((12, 4), dtype=np.float32))
            roi_file.write_text(
                json.dumps(
                    {
                        "rois": [
                            {
                                "roi_id": "ROI_A",
                                "display_name": "ROI A",
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
            episodes = [
                {
                    "episode_id": "train_ep",
                    "split": "train",
                    "descriptions": "train.md",
                    "h5_dataset": "train",
                },
                {
                    "episode_id": "val_ep",
                    "split": "val",
                    "descriptions": "val.md",
                    "h5_dataset": "val",
                },
                {
                    "episode_id": "test_ep",
                    "split": "test",
                    "descriptions": "test.md",
                    "h5_dataset": "test",
                },
            ]
            config_file.write_text(
                json.dumps(
                    {
                        "roi_definitions": roi_file.name,
                        "atlas_labels": labels.name,
                        "h5_file": h5_file.name,
                        "output_root": output_root.name,
                        "subject_id": "sub-01",
                        "rois": ["ROI_A"],
                        "episodes": episodes,
                        "encoding_trim": {
                            "fmri_trim_start_tr": 5,
                            "fmri_trim_end_tr": 5,
                        },
                    },
                ),
                encoding="utf-8",
            )
            for episode in episodes:
                feature_path = (
                    output_root
                    / "rois"
                    / "ROI_A"
                    / "scores"
                    / episode["episode_id"]
                    / "tr_features.jsonl"
                )
                feature_path.parent.mkdir(parents=True, exist_ok=True)
                _write_features(feature_path, _features(12, 0.0, 1.0))

            config = load_pilot_config(config_file)
            rois = select_roi_definitions(
                load_roi_definitions(config.roi_definitions),
                config.rois,
            )
            artifacts = PilotArtifacts(config)
            expected_output_root = output_root.resolve()
            self.assertEqual(
                artifacts.summary_path(config.episodes[0]),
                expected_output_root / "summaries" / "train_ep" / "summary.json",
            )
            self.assertEqual(
                artifacts.scoring_dir("ROI_A", config.episodes[0]),
                expected_output_root / "rois" / "ROI_A" / "scores" / "train_ep",
            )
            self.assertEqual(
                artifacts.manifest_path(),
                expected_output_root / "encoding" / "roi_encoding_manifest.jsonl",
            )
            self.assertEqual(
                artifacts.write_encoding_inputs(rois),
                artifacts.manifest_path(),
            )
            schema_mapping = json.loads(
                artifacts.roi_schema_mapping_path().read_text(encoding="utf-8"),
            )
            self.assertEqual(
                schema_mapping,
                {"roi_schemas": {"ROI_A": "../rois/ROI_A/region_schema.json"}},
            )

            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "run-multi-roi-pilot",
                        "--config",
                        str(config_file),
                        "--stage",
                        "manifest",
                    ],
                )

            manifest = output_root / "encoding" / "roi_encoding_manifest.jsonl"
            rows = [
                json.loads(line)
                for line in manifest.read_text(encoding="utf-8").splitlines()
                if line
            ]

        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row["feature_trim_start_tr"], 0)
            self.assertEqual(row["feature_trim_end_tr"], 0)
            self.assertEqual(row["fmri_trim_start_tr"], 5)
            self.assertEqual(row["fmri_trim_end_tr"], 5)

    def test_manifest_requires_consistent_roi_sets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "manifest.jsonl"
            rows = [
                {
                    "sample_id": "sample_train",
                    "subject_id": "sub-01",
                    "feature_set_name": "roi_scores",
                    "split": "train",
                    "roi_features": {"ROI_A": "a.jsonl", "ROI_B": "b.jsonl"},
                    "h5_file": "bold.h5",
                    "h5_dataset": "train",
                },
                {
                    "sample_id": "sample_val",
                    "subject_id": "sub-01",
                    "feature_set_name": "roi_scores",
                    "split": "val",
                    "roi_features": {"ROI_A": "a.jsonl"},
                    "h5_file": "bold.h5",
                    "h5_dataset": "val",
                },
            ]
            manifest.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "same ROI ids"):
                load_roi_encoding_manifest(manifest)

    def test_fit_roi_encoding_deduplicates_targets_and_reports_memberships(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            labels = root / "brainnetome.csv"
            h5_file = root / "bold.h5"
            schema_a = root / "roi_a_schema.json"
            schema_b = root / "roi_b_schema.json"
            schema_mapping = root / "roi_schemas.json"
            manifest = root / "manifest.jsonl"
            output_dir = root / "encoding_out"
            _write_labels(labels)
            schema_a.write_text(
                json.dumps(
                    _schema(
                        "ROI_A",
                        (SelectionRule(label_ids=(1, 2)),),
                        "roi_a",
                    ).to_dict(),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            schema_b.write_text(
                json.dumps(
                    _schema(
                        "ROI_B",
                        (
                            SelectionRule(label_ids=(2, 3)),
                        ),
                        "roi_b",
                    ).to_dict(),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            schema_mapping.write_text(
                json.dumps(
                    {
                        "roi_schemas": {
                            "ROI_A": schema_a.name,
                            "ROI_B": schema_b.name,
                        },
                    },
                ),
                encoding="utf-8",
            )

            samples = [
                ("sample_train", "train", 0.0, "train"),
                ("sample_val", "val", 20.0, "val"),
                ("sample_test", "test", 40.0, "test"),
            ]
            manifest_rows = []
            with h5py.File(h5_file, "w") as handle:
                for sample_id, split, offset, dataset in samples:
                    roi_a = _features(12, offset, 1.0)
                    roi_b = _features(12, offset, 2.0)
                    feature_a = root / f"{sample_id}_roi_a.jsonl"
                    feature_b = root / f"{sample_id}_roi_b.jsonl"
                    _write_features(feature_a, roi_a)
                    _write_features(feature_b, roi_b)
                    handle.create_dataset(dataset, data=_targets(roi_a, roi_b))
                    manifest_rows.append(
                        {
                            "sample_id": sample_id,
                            "subject_id": "sub-01",
                            "feature_set_name": "roi_scores",
                            "split": split,
                            "roi_features": {
                                "ROI_A": feature_a.name,
                                "ROI_B": feature_b.name,
                            },
                            "h5_file": h5_file.name,
                            "h5_dataset": dataset,
                        },
                    )
            manifest.write_text(
                "\n".join(json.dumps(row) for row in manifest_rows) + "\n",
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                main(
                    [
                        "fit-roi-encoding",
                        "--manifest",
                        str(manifest),
                        "--roi-schemas",
                        str(schema_mapping),
                        "--atlas-labels",
                        str(labels),
                        "--output-dir",
                        str(output_dir),
                        "--lags",
                        "1",
                        "--alphas",
                        "0.01,1",
                    ],
                )

            metadata = json.loads((output_dir / "encoding_metadata.json").read_text(encoding="utf-8"))
            parcel_rows = [
                json.loads(line)
                for line in (output_dir / "sub-01" / "parcel_metrics.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            roi_summaries = json.loads(
                (output_dir / "sub-01" / "roi_summaries.json").read_text(encoding="utf-8"),
            )
            group_summary = json.loads((output_dir / "group_summary.json").read_text(encoding="utf-8"))
            predictions = np.load(output_dir / "sub-01" / "test_predictions.npz")

        self.assertEqual(metadata["command"], "fit-roi-encoding")
        self.assertEqual(len(metadata["selected_parcels"]), 3)
        by_index = {row["parcel_index"]: row for row in parcel_rows}
        self.assertEqual(by_index[1]["roi_memberships"], ["ROI_A", "ROI_B"])
        self.assertEqual(roi_summaries["ROI_A"]["n_total_selected_parcels"], 2)
        self.assertEqual(roi_summaries["ROI_B"]["n_total_selected_parcels"], 2)
        self.assertEqual(
            group_summary["primary_metric"],
            "mean_subject_mean_test_pearson",
        )
        self.assertEqual(predictions["y_true"].shape, predictions["y_pred"].shape)
        self.assertEqual(predictions["parcel_indices"].tolist(), [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
