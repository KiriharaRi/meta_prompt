from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import h5py
import numpy as np

from brain_region_pipeline.cli import main
from brain_region_pipeline.atlas.models import SelectionRule
from brain_region_pipeline.encoding.features import align_feature_matrix_to_trimmed_fmri
from brain_region_pipeline.encoding.manifest import load_roi_encoding_manifest
from brain_region_pipeline.encoding.runner import _load_one_roi_feature_matrix
from brain_region_pipeline.schema_design.domain_models import CuratedDomain
from brain_region_pipeline.schema_design.schema_models import DimensionSpec, RegionFeatureSchema


def _domain() -> CuratedDomain:
    return CuratedDomain(
        domain_id="emotion_experience",
        definition="Viewer emotion experience.",
        vmpfc_relevance="Relevant to vmPFC affective meaning.",
        scoreability_note="Use dense-description affective evidence.",
        source_domain_ids=("required_emotion_experience",),
        source_runs=(0,),
        proposal_frequency=1,
        consolidation_rationale="Required validation anchor domain.",
    )


def _dimension(dimension_id: str) -> DimensionSpec:
    return DimensionSpec(
        dimension_id=dimension_id,
        definition=f"{dimension_id} intensity.",
        domain="emotion_experience",
        score_min=0.0,
        score_max=10.0,
        trigger_list=("danger", "uncertainty", "pressure"),
        graded_anchors={
            str(score): ("absent" if score == 0 else "present")
            for score in range(11)
        },
        calibration_examples=(
            {"scene": "A calm scene.", "score": 0},
            {"scene": "A tense scene.", "score": 8},
        ),
        scoreability_note="Use text evidence.",
        exclusion_note="Do not count unrelated affect.",
    )


def _schema() -> RegionFeatureSchema:
    return RegionFeatureSchema(
        target_region="vmPFC",
        functional_hypothesis="Tracks affective value.",
        scoring_instruction="Score dimensions.",
        selection_rules=(
            SelectionRule(label_ids=(1, 2)),
        ),
        domains=(_domain(),),
        active_domain_ids=("emotion_experience",),
        dimensions=(
            _dimension("emotion_agitation"),
            _dimension("emotion_fear"),
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


def _feature_values(n_trs: int, offset: float) -> np.ndarray:
    time = np.arange(n_trs, dtype=np.float64)
    return np.column_stack(
        [
            offset + time,
            offset * 0.5 + time * time,
        ],
    )


def _write_features(path: Path, values: np.ndarray) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for idx, vector in enumerate(values):
            handle.write(
                json.dumps(
                    {
                        "tr_index": idx,
                        "tr_start_s": float(idx),
                        "tr_end_s": float(idx + 1),
                        "source_description": f"segment {idx}",
                        "feature_vector": [float(value) for value in vector],
                        "weights": {},
                    },
                )
                + "\n",
            )


def _target_values(features: np.ndarray) -> np.ndarray:
    targets = np.zeros((features.shape[0], 4), dtype=np.float32)
    targets[1:, 0] = features[:-1, 0]
    targets[1:, 1] = features[:-1, 1] * 2
    targets[:, 2] = np.linspace(0, 1, features.shape[0], dtype=np.float32)
    targets[:, 3] = np.linspace(1, 2, features.shape[0], dtype=np.float32)
    return targets


class BrainRegionEncodingTests(unittest.TestCase):
    """Validate the H5 Ridge encoding stage contract."""

    def test_raw_tr_alignment_allows_longer_features(self) -> None:
        x_raw = np.arange(24, dtype=np.float64).reshape(12, 2)
        y_raw = np.arange(50, dtype=np.float64).reshape(10, 5)

        aligned = align_feature_matrix_to_trimmed_fmri(
            sample_id="sample_long",
            x_raw=x_raw,
            y_raw=y_raw,
            feature_trim_start_tr=0,
            feature_trim_end_tr=0,
            fmri_trim_start_tr=2,
            fmri_trim_end_tr=3,
        )

        np.testing.assert_array_equal(aligned.x, x_raw[2:7])
        np.testing.assert_array_equal(aligned.y, y_raw[2:7])
        self.assertEqual(aligned.feature_start_tr, 2)
        self.assertEqual(aligned.fmri_start_tr, 2)

    def test_raw_tr_alignment_rejects_short_feature_tail(self) -> None:
        x_raw = np.zeros((6, 2), dtype=np.float64)
        y_raw = np.zeros((10, 3), dtype=np.float64)

        with self.assertRaisesRegex(
            ValueError,
            r"sample_short.*feature rows cover raw TR \[0, 6\).*"
            r"trimmed fMRI requires \[2, 8\).*fmri_trim_end_tr to at least 4",
        ):
            align_feature_matrix_to_trimmed_fmri(
                sample_id="sample_short",
                x_raw=x_raw,
                y_raw=y_raw,
                feature_trim_start_tr=0,
                feature_trim_end_tr=0,
                fmri_trim_start_tr=2,
                fmri_trim_end_tr=2,
            )

    def test_tr_feature_loader_requires_continuous_raw_tr_indices(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            feature_file = Path(tmpdir) / "features.jsonl"
            rows = [
                {
                    "tr_index": 0,
                    "tr_start_s": 0.0,
                    "tr_end_s": 1.0,
                    "feature_vector": [1.0, 2.0],
                },
                {
                    "tr_index": 2,
                    "tr_start_s": 1.0,
                    "tr_end_s": 2.0,
                    "feature_vector": [3.0, 4.0],
                },
            ]
            feature_file.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "tr_index must be 1"):
                _load_one_roi_feature_matrix(feature_file, ["a", "b"])

    def test_manifest_loader_reports_line_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "manifest.jsonl"
            manifest.write_text('{"sample_id": "s1"}\n', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Manifest line 1"):
                load_roi_encoding_manifest(manifest)

    def test_fit_roi_encoding_cli_writes_subject_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            labels = root / "brainnetome.csv"
            schema_file = root / "schema.json"
            schema_mapping = root / "roi_schemas.json"
            h5_file = root / "bold.h5"
            manifest = root / "manifest.jsonl"
            output_dir = root / "encoding_out"
            _write_labels(labels)
            schema_file.write_text(
                json.dumps(_schema().to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            schema_mapping.write_text(
                json.dumps({"roi_schemas": {"vmPFC": schema_file.name}}),
                encoding="utf-8",
            )
            samples = [
                ("sample_train", "train", "train_features.jsonl", "ses-001_task-train", 0.0),
                ("sample_val", "val", "val_features.jsonl", "ses-002_task-val", 20.0),
                ("sample_test", "test", "test_features.jsonl", "ses-003_task-test", 40.0),
            ]
            with h5py.File(h5_file, "w") as handle:
                manifest_rows = []
                for sample_id, split, feature_name, h5_dataset, offset in samples:
                    features = _feature_values(14, offset)
                    _write_features(root / feature_name, features)
                    handle.create_dataset(h5_dataset, data=_target_values(features[:12]))
                    manifest_rows.append(
                        {
                            "sample_id": sample_id,
                            "subject_id": "sub-01",
                            "feature_set_name": "llm_region_scores",
                            "split": split,
                            "roi_features": {"vmPFC": feature_name},
                            "h5_file": h5_file.name,
                            "h5_dataset": h5_dataset,
                            "feature_trim_start_tr": 0,
                            "feature_trim_end_tr": 0,
                            "fmri_trim_start_tr": 2,
                            "fmri_trim_end_tr": 2,
                        },
                    )
            manifest.write_text(
                "\n".join(json.dumps(row) for row in manifest_rows) + "\n",
                encoding="utf-8",
            )

            with redirect_stdout(StringIO()):
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

            group_summary = json.loads(
                (output_dir / "group_summary.json").read_text(encoding="utf-8"),
            )
            roi_summaries = json.loads(
                (output_dir / "sub-01" / "roi_summaries.json").read_text(encoding="utf-8"),
            )
            parcel_rows = [
                json.loads(line)
                for line in (output_dir / "sub-01" / "parcel_metrics.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line
            ]
            predictions = np.load(output_dir / "sub-01" / "test_predictions.npz")
            coefficients = np.load(output_dir / "sub-01" / "ridge_coefficients.npz")

        self.assertEqual(group_summary["n_subjects"], 1)
        self.assertIn("vmPFC", group_summary["roi_summaries"])
        self.assertGreater(roi_summaries["vmPFC"]["mean_test_pearson"], 0.99)
        self.assertEqual([row["parcel_index"] for row in parcel_rows], [0, 1])
        self.assertEqual([row["roi_memberships"] for row in parcel_rows], [["vmPFC"], ["vmPFC"]])
        self.assertEqual(predictions["y_true"].shape, predictions["y_pred"].shape)
        np.testing.assert_array_equal(predictions["feature_tr_indices"], np.arange(3, 10))
        np.testing.assert_array_equal(predictions["fmri_tr_indices"], np.arange(3, 10))
        self.assertEqual(coefficients["coef"].shape[0], 2)
        self.assertEqual(
            coefficients["expanded_feature_names"].tolist(),
            ["vmPFC::emotion_agitation_lag1", "vmPFC::emotion_fear_lag1"],
        )


if __name__ == "__main__":
    unittest.main()
