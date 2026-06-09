"""Domain-pool data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.contracts import DOMAIN_POOL_VERSION


def _normalize_strs(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    """Normalize a list of labels into a deduplicated tuple."""

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


def _normalize_ints(values: list[int] | tuple[int, ...] | None) -> tuple[int, ...]:
    """Normalize a list of integer ids into a deduplicated tuple."""

    if not values:
        return ()
    ordered: list[int] = []
    seen: set[int] = set()
    for value in values:
        item = int(value)
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return tuple(ordered)


def _domain_region_relevance(data: dict[str, Any], domain_id: str) -> str:
    """Read the generic region relevance field with vmPFC artifact fallback."""

    raw_value = data.get("region_relevance", data.get("vmpfc_relevance"))
    if raw_value is None:
        raise ValueError(
            f"Domain {domain_id!r} must include region_relevance.",
        )
    return str(raw_value).strip()


@dataclass(frozen=True, init=False)
class CandidateDomain:
    """One coarse-domain candidate proposed during a domain-pool run."""

    domain_id: str
    definition: str
    region_relevance: str
    scoreability_note: str
    source_run: int

    def __init__(
        self,
        *,
        domain_id: str,
        definition: str,
        scoreability_note: str,
        source_run: int,
        region_relevance: str | None = None,
        vmpfc_relevance: str | None = None,
    ) -> None:
        """Create a candidate domain while accepting legacy vmPFC keyword use."""

        relevance = region_relevance if region_relevance is not None else vmpfc_relevance
        if relevance is None:
            raise ValueError(
                f"Domain {domain_id!r} must include region_relevance.",
            )
        object.__setattr__(self, "domain_id", str(domain_id).strip())
        object.__setattr__(self, "definition", str(definition).strip())
        object.__setattr__(self, "region_relevance", str(relevance).strip())
        object.__setattr__(self, "scoreability_note", str(scoreability_note).strip())
        object.__setattr__(self, "source_run", int(source_run))

    @property
    def vmpfc_relevance(self) -> str:
        """Backward-compatible alias for older in-repo helpers and artifacts."""

        return self.region_relevance

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateDomain":
        """Build a candidate domain from serialized JSON data."""

        domain_id = str(data["domain_id"]).strip()
        return cls(
            domain_id=domain_id,
            definition=str(data["definition"]).strip(),
            region_relevance=_domain_region_relevance(data, domain_id),
            scoreability_note=str(data["scoreability_note"]).strip(),
            source_run=int(data["source_run"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON."""

        return {
            "domain_id": self.domain_id,
            "definition": self.definition,
            "region_relevance": self.region_relevance,
            "scoreability_note": self.scoreability_note,
            "source_run": self.source_run,
        }


@dataclass(frozen=True, init=False)
class CuratedDomain:
    """One retained coarse domain after proposal consolidation."""

    domain_id: str
    definition: str
    region_relevance: str
    scoreability_note: str
    source_domain_ids: tuple[str, ...] = ()
    source_runs: tuple[int, ...] = ()
    proposal_frequency: int = 0
    consolidation_rationale: str = ""

    def __init__(
        self,
        *,
        domain_id: str,
        definition: str,
        scoreability_note: str,
        source_domain_ids: list[str] | tuple[str, ...] | None = None,
        source_runs: list[int] | tuple[int, ...] | None = None,
        proposal_frequency: int = 0,
        consolidation_rationale: str = "",
        region_relevance: str | None = None,
        vmpfc_relevance: str | None = None,
    ) -> None:
        """Create a curated domain while accepting legacy vmPFC keyword use."""

        relevance = region_relevance if region_relevance is not None else vmpfc_relevance
        if relevance is None:
            raise ValueError(
                f"Curated domain {domain_id!r} must include region_relevance.",
            )
        object.__setattr__(self, "domain_id", str(domain_id).strip())
        object.__setattr__(self, "definition", str(definition).strip())
        object.__setattr__(self, "region_relevance", str(relevance).strip())
        object.__setattr__(self, "scoreability_note", str(scoreability_note).strip())
        object.__setattr__(self, "source_domain_ids", _normalize_strs(source_domain_ids))
        object.__setattr__(self, "source_runs", _normalize_ints(source_runs))
        object.__setattr__(self, "proposal_frequency", int(proposal_frequency))
        object.__setattr__(
            self,
            "consolidation_rationale",
            str(consolidation_rationale).strip(),
        )

    @property
    def vmpfc_relevance(self) -> str:
        """Backward-compatible alias for older in-repo helpers and artifacts."""

        return self.region_relevance

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CuratedDomain":
        """Build a curated domain from serialized JSON data."""

        domain_id = str(data["domain_id"]).strip()
        if "proposal_frequency" not in data:
            raise ValueError(
                f"Curated domain {domain_id!r} must include proposal_frequency.",
            )
        source_runs = _normalize_ints(data.get("source_runs"))
        return cls(
            domain_id=domain_id,
            definition=str(data["definition"]).strip(),
            region_relevance=_domain_region_relevance(data, domain_id),
            scoreability_note=str(data["scoreability_note"]).strip(),
            source_domain_ids=_normalize_strs(data.get("source_domain_ids")),
            source_runs=source_runs,
            proposal_frequency=int(data["proposal_frequency"]),
            consolidation_rationale=str(data["consolidation_rationale"]).strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON."""

        return {
            "domain_id": self.domain_id,
            "definition": self.definition,
            "region_relevance": self.region_relevance,
            "scoreability_note": self.scoreability_note,
            "source_domain_ids": list(self.source_domain_ids),
            "source_runs": list(self.source_runs),
            "proposal_frequency": self.proposal_frequency,
            "consolidation_rationale": self.consolidation_rationale,
        }


@dataclass(frozen=True)
class RejectedOrMergedDomain:
    """One proposed coarse domain removed or merged during consolidation."""

    domain_id: str
    decision: str
    reason: str
    source_domain_ids: tuple[str, ...] = ()
    source_runs: tuple[int, ...] = ()
    merged_into: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RejectedOrMergedDomain":
        """Build a rejected/merged domain record from serialized JSON data."""

        return cls(
            domain_id=str(data["domain_id"]).strip(),
            decision=str(data["decision"]).strip(),
            reason=str(data["reason"]).strip(),
            source_domain_ids=_normalize_strs(data.get("source_domain_ids")),
            source_runs=_normalize_ints(data.get("source_runs")),
            merged_into=str(data.get("merged_into", "")).strip(),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON."""

        data: dict[str, Any] = {
            "domain_id": self.domain_id,
            "decision": self.decision,
            "reason": self.reason,
            "source_domain_ids": list(self.source_domain_ids),
            "source_runs": list(self.source_runs),
        }
        if self.merged_into:
            data["merged_into"] = self.merged_into
        return data


@dataclass(frozen=True)
class DomainPool:
    """Auditable coarse-domain pool used before active-dimension generation."""

    target_region: str
    candidate_domains: tuple[CandidateDomain, ...]
    curated_domains: tuple[CuratedDomain, ...]
    rejected_or_merged_domains: tuple[RejectedOrMergedDomain, ...] = ()
    version: str = DOMAIN_POOL_VERSION
    curation_status: str = "draft"
    source_model: str = ""
    proposal_runs: int = 5
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        curated_ids = [domain.domain_id for domain in self.curated_domains]
        if self.version != DOMAIN_POOL_VERSION:
            raise ValueError(f"Unsupported domain-pool version: {self.version!r}")
        if self.curation_status not in {"draft", "confirmed"}:
            raise ValueError(f"Invalid domain-pool curation_status: {self.curation_status!r}")
        if not self.candidate_domains:
            raise ValueError("Domain pool cannot be empty: candidate_domains is required.")
        if not self.curated_domains:
            raise ValueError("Domain pool cannot be empty: curated_domains is required.")
        if len(curated_ids) != len(set(curated_ids)):
            raise ValueError(f"Duplicate curated domain_id in domain pool: {curated_ids}")
        for domain in self.curated_domains:
            if not domain.source_domain_ids:
                raise ValueError(
                    f"Curated domain {domain.domain_id!r} must preserve source_domain_ids.",
                )
            if not domain.source_runs:
                raise ValueError(
                    f"Curated domain {domain.domain_id!r} must preserve source_runs.",
                )
            if domain.proposal_frequency < 1:
                raise ValueError(
                    f"Curated domain {domain.domain_id!r} must have proposal_frequency >= 1.",
                )
            if domain.proposal_frequency != len(domain.source_runs):
                raise ValueError(
                    f"Curated domain {domain.domain_id!r} must have "
                    "proposal_frequency equal to len(source_runs).",
                )
            if not domain.consolidation_rationale:
                raise ValueError(
                    f"Curated domain {domain.domain_id!r} must include consolidation_rationale.",
                )
        for domain in self.rejected_or_merged_domains:
            if not domain.reason:
                raise ValueError(
                    f"Rejected or merged domain {domain.domain_id!r} must include a reason.",
                )
            if not domain.source_domain_ids:
                raise ValueError(
                    f"Rejected or merged domain {domain.domain_id!r} must preserve source_domain_ids.",
                )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DomainPool":
        """Build a domain pool from serialized JSON data."""

        return cls(
            version=str(data["version"]).strip(),
            target_region=str(data["target_region"]).strip(),
            curation_status=str(data["curation_status"]).strip(),
            source_model=str(data["source_model"]).strip(),
            proposal_runs=int(data["proposal_runs"]),
            candidate_domains=tuple(
                CandidateDomain.from_dict(item)
                for item in data.get("candidate_domains", [])
            ),
            curated_domains=tuple(
                CuratedDomain.from_dict(item)
                for item in data.get("curated_domains", [])
            ),
            rejected_or_merged_domains=tuple(
                RejectedOrMergedDomain.from_dict(item)
                for item in data.get("rejected_or_merged_domains", [])
            ),
            metadata=dict(data.get("metadata") or {}),
        )

    def curated_domain_ids(self) -> list[str]:
        """Return the retained coarse-domain IDs in curated order."""

        return [domain.domain_id for domain in self.curated_domains]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON."""

        return {
            "version": self.version,
            "target_region": self.target_region,
            "curation_status": self.curation_status,
            "source_model": self.source_model,
            "proposal_runs": self.proposal_runs,
            "metadata": dict(self.metadata),
            "candidate_domains": [
                domain.to_dict() for domain in self.candidate_domains
            ],
            "curated_domains": [
                domain.to_dict() for domain in self.curated_domains
            ],
            "rejected_or_merged_domains": [
                domain.to_dict() for domain in self.rejected_or_merged_domains
            ],
        }

