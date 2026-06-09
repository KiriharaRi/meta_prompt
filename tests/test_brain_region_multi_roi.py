from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import h5py
import numpy as np

from brain_region_pipeline.cli import main
from brain_region_pipeline.core.config import (
    AIHUBMIX_GENERATION_PROVIDER,
    DEFAULT_AIHUBMIX_MODEL,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_GENERATION_PROVIDER,
)
from brain_region_pipeline.atlas.models import SelectionRule
from brain_region_pipeline.encoding.manifest import load_roi_encoding_manifest
from brain_region_pipeline.schema_design.domain_models import CuratedDomain
from brain_region_pipeline.schema_design.schema_models import DimensionSpec, RegionFeatureSchema
from brain_region_pipeline.pilot.runner import load_pilot_config


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
