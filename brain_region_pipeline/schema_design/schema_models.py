"""Region-schema data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..atlas.models import SelectionRule
from ..core.contracts import REGION_SCHEMA_VERSION
from .domain_models import CuratedDomain, _normalize_strs


def _normalize_graded_anchors(values: dict[str, Any] | None) -> dict[str, str]:
    """Normalize score anchors keyed by score label."""

    if not values:
        return {}
    normalized: dict[str, str] = {}
    for key, value in values.items():
        label = str(key).strip()
        text = str(value).strip()
        if label and text:
            normalized[label] = text
    return normalized


def _normalize_calibration_examples(
    values: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> tuple[dict[str, Any], ...]:
    """Normalize examples used to calibrate dimension scores."""

    if not values:
        return ()
    examples: list[dict[str, Any]] = []
    for value in values:
        scene = str(value.get("scene", "")).strip()
        if not scene:
            continue
        example: dict[str, Any] = {"scene": scene}
        if "score" in value:
            score = float(value["score"])
            example["score"] = int(score) if score.is_integer() else score
        examples.append(example)
    return tuple(examples)


@dataclass(frozen=True)
class DimensionSpec:
    """One interpretable active feature dimension in a region schema."""

    dimension_id: str
    definition: str
    domain: str
    score_min: float = 0.0
    score_max: float = 10.0
    trigger_list: tuple[str, ...] = ()
    graded_anchors: dict[str, str] = field(default_factory=dict)
    calibration_examples: tuple[dict[str, Any], ...] = ()
    scoreability_note: str = ""
    exclusion_note: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DimensionSpec":
        """Build a dimension spec from serialized JSON data."""

        return cls(
            dimension_id=str(data["dimension_id"]).strip(),
            definition=str(data["definition"]).strip(),
            domain=str(data["domain"]).strip(),
            score_min=float(data.get("score_min", 0.0)),
            score_max=float(data.get("score_max", 10.0)),
            trigger_list=_normalize_strs(data["trigger_list"]),
            graded_anchors=_normalize_graded_anchors(data["graded_anchors"]),
            calibration_examples=_normalize_calibration_examples(
                data["calibration_examples"],
            ),
            scoreability_note=str(data["scoreability_note"]).strip(),
            exclusion_note=str(data["exclusion_note"]).strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON."""

        return {
            "dimension_id": self.dimension_id,
            "definition": self.definition,
            "domain": self.domain,
            "score_min": self.score_min,
            "score_max": self.score_max,
            "trigger_list": list(self.trigger_list),
            "graded_anchors": dict(self.graded_anchors),
            "calibration_examples": [
                dict(example)
                for example in self.calibration_examples
            ],
            "scoreability_note": self.scoreability_note,
            "exclusion_note": self.exclusion_note,
        }


@dataclass(frozen=True)
class RegionFeatureSchema:
    """Executable active-dimension schema for one target brain region."""

    target_region: str
    functional_hypothesis: str
    scoring_instruction: str
    selection_rules: tuple[SelectionRule, ...]
    domains: tuple[CuratedDomain, ...]
    active_domain_ids: tuple[str, ...]
    dimensions: tuple[DimensionSpec, ...]
    version: str = REGION_SCHEMA_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.version != REGION_SCHEMA_VERSION:
            raise ValueError(f"Unsupported region-schema version: {self.version!r}")
        if not self.target_region:
            raise ValueError("Region schema target_region is required.")
        if not self.functional_hypothesis:
            raise ValueError("Region schema functional_hypothesis is required.")
        if not self.scoring_instruction:
            raise ValueError("Region schema scoring_instruction is required.")
        if not self.selection_rules:
            raise ValueError("Region schema selection_rules cannot be empty.")
        if not self.domains:
            raise ValueError("Region schema domains cannot be empty.")
        if not self.dimensions:
            raise ValueError("Region schema dimensions cannot be empty.")

        domain_ids = [domain.domain_id for domain in self.domains]
        if len(domain_ids) != len(set(domain_ids)):
            raise ValueError(f"Duplicate domain_id in region schema: {domain_ids}")

        dimension_ids = [dimension.dimension_id for dimension in self.dimensions]
        if len(dimension_ids) != len(set(dimension_ids)):
            raise ValueError(f"Duplicate dimension_id in region schema: {dimension_ids}")

        domain_id_set = set(domain_ids)
        for dimension in self.dimensions:
            if dimension.domain not in domain_id_set:
                raise ValueError(
                    f"Dimension {dimension.dimension_id!r} references unknown domain "
                    f"{dimension.domain!r}.",
                )

        active_domains = {
            dimension.domain for dimension in self.dimensions
        }
        expected_active_domain_ids = tuple(
            domain_id for domain_id in domain_ids if domain_id in active_domains
        )
        if self.active_domain_ids != expected_active_domain_ids:
            raise ValueError(
                "active_domain_ids must match active dimensions in domain order: "
                f"{self.active_domain_ids!r} != {expected_active_domain_ids!r}",
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegionFeatureSchema":
        """Build a region feature schema from serialized JSON data."""

        return cls(
            version=str(data["version"]).strip(),
            target_region=str(data["target_region"]).strip(),
            functional_hypothesis=str(data["functional_hypothesis"]).strip(),
            scoring_instruction=str(data["scoring_instruction"]).strip(),
            selection_rules=tuple(
                SelectionRule.from_dict(rule)
                for rule in data.get("selection_rules", [])
            ),
            domains=tuple(
                CuratedDomain.from_dict(item)
                for item in data.get("domains", [])
            ),
            active_domain_ids=_normalize_strs(data.get("active_domain_ids")),
            dimensions=tuple(
                DimensionSpec.from_dict(item)
                for item in data.get("dimensions", [])
            ),
            metadata=dict(data.get("metadata") or {}),
        )

    def ordered_dimension_ids(self) -> list[str]:
        """Return feature dimension IDs in output-vector order."""

        return [dimension.dimension_id for dimension in self.dimensions]

    def dimension_domain_map(self) -> dict[str, str]:
        """Return dimension_id -> domain_id for feature metadata."""

        return {
            dimension.dimension_id: dimension.domain
            for dimension in self.dimensions
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON."""

        return {
            "version": self.version,
            "target_region": self.target_region,
            "functional_hypothesis": self.functional_hypothesis,
            "scoring_instruction": self.scoring_instruction,
            "selection_rules": [rule.to_dict() for rule in self.selection_rules],
            "domains": [domain.to_dict() for domain in self.domains],
            "active_domain_ids": list(self.active_domain_ids),
            "dimensions": [dimension.to_dict() for dimension in self.dimensions],
            "metadata": dict(self.metadata),
        }

