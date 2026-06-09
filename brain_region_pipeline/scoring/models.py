"""Scoring-stage data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DescriptionSegment:
    """One timestamped dense description segment from an external source."""

    start_s: float
    end_s: float
    description: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON."""

        return {
            "start_s": self.start_s,
            "end_s": self.end_s,
            "description": self.description,
        }


@dataclass(frozen=True)
class SegmentRegionScore:
    """Region-schema dimension scores inferred for one description segment."""

    start_s: float
    end_s: float
    description: str
    dimension_scores: dict[str, float]
    rationale: str = ""
    segment_id: int | None = None
    batch_idx: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SegmentRegionScore":
        """Build segment-level region scores from serialized JSON data."""

        return cls(
            start_s=float(data["start_s"]),
            end_s=float(data["end_s"]),
            description=str(data["description"]).strip(),
            dimension_scores={
                str(dimension_id): float(score)
                for dimension_id, score in data.get("dimension_scores", {}).items()
            },
            rationale=str(data.get("rationale", "")).strip(),
            segment_id=(
                int(data["segment_id"])
                if data.get("segment_id") is not None
                else None
            ),
            batch_idx=(
                int(data["batch_idx"])
                if data.get("batch_idx") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON."""

        payload = {
            "start_s": self.start_s,
            "end_s": self.end_s,
            "description": self.description,
            "dimension_scores": dict(self.dimension_scores),
            "rationale": self.rationale,
        }
        if self.segment_id is not None:
            payload["segment_id"] = self.segment_id
        if self.batch_idx is not None:
            payload["batch_idx"] = self.batch_idx
        return payload


@dataclass(frozen=True)
class TRFeatureRow:
    """One TR-aligned feature row with provenance text for inspection."""

    tr_index: int
    tr_start_s: float
    tr_end_s: float
    source_description: str
    feature_vector: list[float] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON."""

        return {
            "tr_index": self.tr_index,
            "tr_start_s": self.tr_start_s,
            "tr_end_s": self.tr_end_s,
            "source_description": self.source_description,
            "feature_vector": self.feature_vector,
            "weights": self.weights,
        }

