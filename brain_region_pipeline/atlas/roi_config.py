"""ROI definition loading for fixed atlas selection rules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from ..core.io_utils import read_json
from .labels import expand_selection_rule, parse_atlas_labels
from .models import SelectionRule


@dataclass(frozen=True)
class RoiDefinition:
    """One reusable ROI definition backed by atlas selection rules."""

    roi_id: str
    display_name: str
    selection_rules: tuple[SelectionRule, ...]
    theoretical_role: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RoiDefinition":
        """Build an ROI definition from a JSON object."""

        roi_id = str(data["roi_id"]).strip()
        rules = tuple(
            SelectionRule.from_dict(rule)
            for rule in data.get("selection_rules", [])
        )
        if not roi_id:
            raise ValueError("ROI definition roi_id cannot be empty.")
        if not rules:
            raise ValueError(f"ROI {roi_id!r} must include selection_rules.")
        return cls(
            roi_id=roi_id,
            display_name=str(data.get("display_name", roi_id)).strip() or roi_id,
            theoretical_role=str(data.get("theoretical_role", "")).strip(),
            selection_rules=rules,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the ROI definition to JSON."""

        return {
            "roi_id": self.roi_id,
            "display_name": self.display_name,
            "theoretical_role": self.theoretical_role,
            "selection_rules": [
                rule.to_dict() for rule in self.selection_rules
            ],
        }


def load_roi_definitions(path: str | Path) -> dict[str, RoiDefinition]:
    """Load reusable ROI definitions keyed by ``roi_id``."""

    payload = read_json(path)
    rows = payload.get("rois")
    if not isinstance(rows, list) or not rows:
        raise ValueError("ROI definition file must include a non-empty 'rois' list.")
    definitions = [RoiDefinition.from_dict(row) for row in rows]
    by_id: dict[str, RoiDefinition] = {}
    for definition in definitions:
        if definition.roi_id in by_id:
            raise ValueError(f"Duplicate ROI definition: {definition.roi_id!r}.")
        by_id[definition.roi_id] = definition
    return by_id


def select_roi_definitions(
    definitions: dict[str, RoiDefinition],
    roi_ids: Sequence[str],
) -> list[RoiDefinition]:
    """Return ROI definitions in requested order, failing on unknown IDs."""

    selected: list[RoiDefinition] = []
    for roi_id in roi_ids:
        if roi_id not in definitions:
            raise ValueError(f"Unknown ROI id in run config: {roi_id!r}.")
        selected.append(definitions[roi_id])
    return selected


def validate_roi_definitions_against_atlas(
    definitions: Sequence[RoiDefinition],
    atlas_labels: str | Path,
) -> dict[str, int]:
    """Validate each ROI selects at least one parcel and return parcel counts."""

    parcels = parse_atlas_labels(atlas_labels)
    counts: dict[str, int] = {}
    for definition in definitions:
        selected_indices: set[int] = set()
        for rule in definition.selection_rules:
            selected_indices.update(expand_selection_rule(rule, parcels))
        if not selected_indices:
            raise ValueError(
                f"ROI {definition.roi_id!r} selects no parcels from atlas labels.",
            )
        counts[definition.roi_id] = len(selected_indices)
    return counts
