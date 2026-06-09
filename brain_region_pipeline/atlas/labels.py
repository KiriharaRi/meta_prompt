"""Atlas helpers for brain-region selection and label-space summaries."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from ..schema_design.schema_models import RegionFeatureSchema
from .models import SelectionRule


def _safe_network_name(raw_name: str) -> str:
    """Normalize Yeo network names for exact selection-rule matching."""

    return "_".join(raw_name.strip().split())


def _hemisphere_from_region(region: str) -> str:
    """Infer hemisphere from Brainnetome region labels such as ``MFG_L_7_1``."""

    parts = region.split("_")
    if len(parts) >= 2 and parts[1] in {"L", "R"}:
        return f"{parts[1]}H"
    return ""


def _yeo_network_names(rows: list[list[str]]) -> tuple[dict[str, str], dict[str, str]]:
    """Extract side-table Yeo 7/17 network labels from the Brainnetome CSV."""

    names_7: dict[str, str] = {}
    names_17: dict[str, str] = {}
    active: dict[str, str] | None = None
    for row in rows:
        if len(row) <= 11:
            continue
        marker = row[10].strip()
        name = row[11].strip()
        if marker.startswith("Yeo") and "7" in marker:
            active = names_7
            continue
        if marker.startswith("Yeo") and "17" in marker:
            active = names_17
            continue
        if active is not None and marker.isdigit() and name:
            active[marker] = name
    return names_7, names_17


def parse_brainnetome_yeo_csv(
    label_path: str | Path,
) -> list[dict[str, str | int]]:
    """Parse Brainnetome 246 rows from the updated Yeo-network CSV."""

    path = Path(label_path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if len(rows) < 3:
        raise ValueError(f"Brainnetome label CSV is too short: {path}")
    header = rows[1]
    required = ["Label", "subregion_name", "region", "Yeo_7network", "Yeo_17network"]
    missing = [column for column in required if column not in header]
    if missing:
        raise ValueError(
            f"Brainnetome label CSV is missing required column(s): {', '.join(missing)}",
        )
    col = {name: header.index(name) for name in required}
    yeo7_names, yeo17_names = _yeo_network_names(rows)
    parcels: list[dict[str, str | int]] = []
    for row in rows[2:]:
        if len(row) <= col["Label"] or not row[col["Label"]].strip().isdigit():
            continue
        label_id = int(row[col["Label"]].strip())
        subregion_name = row[col["subregion_name"]].strip()
        region = row[col["region"]].strip()
        yeo7 = row[col["Yeo_7network"]].strip()
        yeo17 = row[col["Yeo_17network"]].strip()
        yeo7_name = yeo7_names.get(yeo7, "Unknown")
        yeo17_name = yeo17_names.get(yeo17, "Unknown")
        parcels.append(
            {
                "idx_0based": label_id - 1,
                "idx_1based": label_id,
                "label": region,
                "hemisphere": _hemisphere_from_region(region),
                "network": f"Yeo7_{yeo7}_{_safe_network_name(yeo7_name)}",
                "sub_region": subregion_name,
                "region": region,
                "yeo_7network": yeo7,
                "yeo_7network_name": yeo7_name,
                "yeo_17network": yeo17,
                "yeo_17network_name": yeo17_name,
            },
        )
    if not parcels:
        raise ValueError(f"Brainnetome label CSV contains no data rows: {path}")
    return parcels


def parse_atlas_labels(label_path: str | Path) -> list[dict[str, str | int]]:
    """Parse the Brainnetome/Yeo atlas label table."""

    path = Path(label_path)
    if path.suffix.lower() != ".csv":
        raise ValueError(
            "Brainnetome-only atlas parsing requires "
            "atlas/subregion_func_network_Yeo_updated.csv.",
        )
    return parse_brainnetome_yeo_csv(path)


def summarize_label_space(
    parcels: list[dict[str, str | int]],
) -> list[dict[str, int | str]]:
    """Summarize atlas labels by network and sub-region."""

    counts: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"LH": 0, "RH": 0, "total": 0},
    )
    for parcel in parcels:
        key = (str(parcel["network"]), str(parcel["sub_region"]))
        hemi = str(parcel["hemisphere"])
        counts[key][hemi] += 1
        counts[key]["total"] += 1

    rows: list[dict[str, int | str]] = []
    for (network, sub_region), stat in sorted(counts.items()):
        rows.append(
            {
                "network": network,
                "sub_region": sub_region,
                "total": stat["total"],
                "LH": stat["LH"],
                "RH": stat["RH"],
            }
        )
    return rows


def render_label_space_summary(parcels: list[dict[str, str | int]]) -> str:
    """Render a compact atlas summary for the meta prompt."""

    lines = []
    for row in summarize_label_space(parcels):
        lines.append(
            "- {network}/{sub_region}: total={total}, LH={LH}, RH={RH}".format(
                **row,
            )
        )
    return "\n".join(lines)


def _matches_rule(parcel: dict[str, str | int], rule: SelectionRule) -> bool:
    """Check whether one parcel matches a selection rule."""

    if rule.label_ids:
        idx_1based = int(parcel.get("idx_1based", int(parcel["idx_0based"]) + 1))
        if idx_1based not in rule.label_ids:
            return False
    if rule.networks and str(parcel["network"]) not in rule.networks:
        return False
    if rule.sub_regions and str(parcel["sub_region"]) not in rule.sub_regions:
        return False
    if rule.hemispheres and str(parcel["hemisphere"]) not in rule.hemispheres:
        return False
    return True


def expand_selection_rule(
    rule: SelectionRule,
    parcels: list[dict[str, str | int]],
) -> list[int]:
    """Expand one selection rule into 0-based parcel indices."""

    return [
        int(parcel["idx_0based"])
        for parcel in parcels
        if _matches_rule(parcel, rule)
    ]


def expand_region_indices(
    schema: RegionFeatureSchema,
    parcels: list[dict[str, str | int]],
) -> list[int]:
    """Expand all selection rules of a region schema into unique parcel indices."""

    all_indices: set[int] = set()
    for rule in schema.selection_rules:
        all_indices.update(expand_selection_rule(rule, parcels))
    return sorted(all_indices)


def build_region_index_map(
    schema: RegionFeatureSchema,
    parcels: list[dict[str, str | int]],
) -> dict[str, list[int]]:
    """Build target_region -> parcel index mapping for selection-rule validation."""

    indices = expand_region_indices(schema, parcels)
    if len(indices) == 0:
        raise ValueError(
            f"Region schema {schema.target_region!r} selects no parcels from atlas.",
        )
    return {schema.target_region: indices}


def selected_parcel_metadata(
    schema: RegionFeatureSchema,
    parcels: list[dict[str, str | int]],
) -> list[dict[str, str | int]]:
    """Return parcel metadata selected by a region schema's selection rules."""

    by_index = {int(parcel["idx_0based"]): parcel for parcel in parcels}
    rows: list[dict[str, str | int]] = []
    for parcel_idx in expand_region_indices(schema, parcels):
        if parcel_idx not in by_index:
            raise ValueError(
                f"Selection rule produced parcel index {parcel_idx}, "
                "but that index is absent from atlas labels.",
            )
        parcel = by_index[parcel_idx]
        rows.append(
            {
                "idx_0based": parcel_idx,
                "label": str(parcel["label"]),
                "network": str(parcel["network"]),
                "sub_region": str(parcel["sub_region"]),
                "hemisphere": str(parcel["hemisphere"]),
            },
        )
    if not rows:
        raise ValueError(
            f"Region schema {schema.target_region!r} selects no parcels from atlas.",
        )
    return rows
