"""Atlas selection-rule contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _normalize_strs(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    """Normalize labels into a deduplicated tuple while preserving order."""

    if not values:
        return ()
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return tuple(ordered)


@dataclass(frozen=True)
class SelectionRule:
    """One whitelist rule used to expand a target region onto atlas parcels."""

    label_ids: tuple[int, ...] = ()
    networks: tuple[str, ...] = ()
    sub_regions: tuple[str, ...] = ()
    hemispheres: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SelectionRule":
        """Build a rule from serialized JSON data."""

        label_ids = tuple(int(value) for value in data.get("label_ids", []) or [])
        if any(label_id <= 0 for label_id in label_ids):
            raise ValueError("SelectionRule label_ids must be positive 1-based atlas labels.")
        return cls(
            label_ids=label_ids,
            networks=_normalize_strs(data.get("networks")),
            sub_regions=_normalize_strs(data.get("sub_regions")),
            hemispheres=_normalize_strs(data.get("hemispheres")),
        )

    def to_dict(self) -> dict[str, list[int] | list[str]]:
        """Serialize to JSON."""

        payload: dict[str, list[int] | list[str]] = {
            "networks": list(self.networks),
            "sub_regions": list(self.sub_regions),
            "hemispheres": list(self.hemispheres),
        }
        if self.label_ids:
            payload["label_ids"] = list(self.label_ids)
        return payload

