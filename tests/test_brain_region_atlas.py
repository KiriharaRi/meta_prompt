from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from brain_region_pipeline.atlas.labels import build_region_index_map, parse_atlas_labels
from brain_region_pipeline.atlas.models import SelectionRule
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


def _dimension() -> DimensionSpec:
    return DimensionSpec(
        dimension_id="emotion_agitation",
        definition="Typical viewer agitation intensity.",
        domain="emotion_experience",
        score_min=0.0,
        score_max=10.0,
        trigger_list=("danger", "uncertainty", "pressure"),
        graded_anchors={
            str(score): ("absent" if score == 0 else "strong")
            for score in range(11)
        },
        calibration_examples=(
            {"scene": "A calm view.", "score": 0},
            {"scene": "A dangerous fall risk.", "score": 8},
        ),
        scoreability_note="Use visible stakes and anxious behavior.",
        exclusion_note="Do not count generic negativity.",
    )


def _schema(selection_rules: tuple[SelectionRule, ...]) -> RegionFeatureSchema:
    return RegionFeatureSchema(
        target_region="vmPFC",
        functional_hypothesis="Tracks affective value.",
        scoring_instruction="Score region dimensions.",
        selection_rules=selection_rules,
        domains=(_domain(),),
        active_domain_ids=("emotion_experience",),
        dimensions=(_dimension(),),
    )


class AtlasPromptMappingTests(unittest.TestCase):
    """Validate atlas expansion for region-schema selection rules."""

    def test_build_region_index_map_expands_selection_rules(self) -> None:
        schema = _schema(
            (
                SelectionRule(label_ids=(1,)),
                SelectionRule(label_ids=(3,)),
            ),
        )
        parcels: list[dict[str, str | int]] = [
            {"idx_0based": 0, "idx_1based": 1, "network": "Yeo7_7_Default", "sub_region": "A8m", "hemisphere": "LH"},
            {"idx_0based": 1, "idx_1based": 2, "network": "Yeo7_4_Ventral_Attention", "sub_region": "A8m", "hemisphere": "RH"},
            {"idx_0based": 2, "idx_1based": 3, "network": "Yeo7_7_Default", "sub_region": "A8dl", "hemisphere": "LH"},
        ]

        mapping = build_region_index_map(schema, parcels)

        self.assertEqual(mapping["vmPFC"], [0, 2])

    def test_build_region_index_map_rejects_empty_selection(self) -> None:
        schema = _schema(
            (
                SelectionRule(label_ids=(2,)),
            ),
        )
        parcels: list[dict[str, str | int]] = [
            {"idx_0based": 0, "idx_1based": 1, "network": "Yeo7_7_Default", "sub_region": "A8m", "hemisphere": "LH"},
        ]

        with self.assertRaises(ValueError):
            build_region_index_map(schema, parcels)

    def test_brainnetome_yeo_csv_expands_label_id_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            labels = Path(tmpdir) / "brainnetome_yeo.csv"
            labels.write_text(
                "\n".join(
                    [
                        "subregion_func_network_Yeo_updated",
                        "Label,subregion_name,region,Yeo_7network,Yeo_17network,,,,,,,",
                        "1,A8m,SFG_L_7_1,6,17,,,,,,Yeo  7 Network,",
                        "2,A8m,SFG_R_7_1,4,8,,,,,,ID,Network name",
                        "3,A8dl,SFG_L_7_2,7,16,,,,,,7,Default",
                    ],
                )
                + "\n",
                encoding="utf-8",
            )
            parcels = parse_atlas_labels(labels)
            schema = _schema((SelectionRule(label_ids=(1, 3)),))

            mapping = build_region_index_map(schema, parcels)

        self.assertEqual(mapping["vmPFC"], [0, 2])
        self.assertEqual(parcels[0]["idx_1based"], 1)
        self.assertEqual(parcels[0]["hemisphere"], "LH")
        self.assertEqual(parcels[2]["sub_region"], "A8dl")


if __name__ == "__main__":
    unittest.main()
