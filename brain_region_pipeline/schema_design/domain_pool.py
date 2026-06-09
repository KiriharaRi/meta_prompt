"""Coarse-domain pool generation for target-region schema design."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..atlas.labels import render_label_space_summary
from ..core.config import DomainPoolConfig
from ..core.contracts import (
    DOMAIN_POOL_VERSION,
    REQUIRED_SEED_SOURCE_RUN,
    required_domain_ids_for_region,
    required_domain_seeds_for_region,
)
from ..core.genai import generate_structured_json
from ..core.io_utils import read_json, write_json
from .domain_models import (
    CandidateDomain,
    CuratedDomain,
    DomainPool,
    RejectedOrMergedDomain,
)

DOMAIN_PROPOSAL_SYSTEM_INSTRUCTION = """\
You design auditable coarse-domain pools for viewer-centric movie-fMRI feature discovery.
Return structured JSON according to the provided schema.
"""

DOMAIN_CONSOLIDATION_SYSTEM_INSTRUCTION = """\
You consolidate coarse-domain proposal runs into one auditable viewer-centric draft domain pool.
Return structured JSON according to the provided schema.
"""


def required_domain_candidates(target_region: str) -> list[CandidateDomain]:
    """Return pre-registered coarse-domain seeds for one target region."""

    return [
        CandidateDomain.from_dict(seed)
        for seed in required_domain_seeds_for_region(target_region).values()
    ]


def _render_required_anchor_block(cfg: DomainPoolConfig) -> str:
    """Render ROI-specific required anchors as a readable prompt data block."""

    required_seeds = required_domain_seeds_for_region(cfg.target_region)
    if not required_seeds:
        return "\n".join(
            [
                "No required anchors are registered for this target region.",
                "Do not add emotion_experience just to satisfy a cross-ROI checklist.",
            ],
        )

    lines = [
        "The following anchors are mandatory for this target region.",
        "They are part of the contract, not optional suggestions.",
    ]
    for final_domain_id, seed in required_seeds.items():
        lines.extend(
            [
                f"- final domain_id: {final_domain_id}",
                f"  source candidate id: {seed['domain_id']}",
                f"  canonical definition: {seed['definition']}",
                f"  canonical target-region relevance: {seed['region_relevance']}",
                f"  canonical scoreability: {seed['scoreability_note']}",
                "  rule: In the final curated domain, keep this definition exactly unchanged.",
                "  evidence rule: character states, dialogue, actions, facial expressions,",
                "  outcomes, and scene atmosphere are evidence used by the viewer; they",
                "  are not the subject of the domain.",
            ],
        )
    return "\n".join(lines)


def _domain_candidate_schema() -> dict[str, Any]:
    """Build the JSON schema for one proposed coarse domain."""

    return {
        "type": "object",
        "required": [
            "domain_id",
            "definition",
            "region_relevance",
            "scoreability_note",
        ],
        "properties": {
            "domain_id": {"type": "string"},
            "definition": {"type": "string"},
            "region_relevance": {"type": "string"},
            "scoreability_note": {"type": "string"},
        },
    }


def _proposal_schema() -> dict[str, Any]:
    """Build the response schema for one domain proposal run."""

    return {
        "type": "object",
        "required": ["candidate_domains"],
        "properties": {
            "candidate_domains": {
                "type": "array",
                "minItems": 1,
                "items": _domain_candidate_schema(),
            },
        },
    }


def _curated_domain_schema() -> dict[str, Any]:
    """Build the JSON schema for one retained coarse domain."""

    return {
        "type": "object",
        "required": [
            "domain_id",
            "definition",
            "region_relevance",
            "scoreability_note",
            "source_domain_ids",
            "consolidation_rationale",
        ],
        "properties": {
            "domain_id": {"type": "string"},
            "definition": {"type": "string"},
            "region_relevance": {"type": "string"},
            "scoreability_note": {"type": "string"},
            "source_domain_ids": {"type": "array", "items": {"type": "string"}},
            "consolidation_rationale": {"type": "string"},
        },
    }


def _rejected_domain_schema() -> dict[str, Any]:
    """Build the JSON schema for one rejected or merged coarse domain."""

    return {
        "type": "object",
        "required": [
            "domain_id",
            "decision",
            "reason",
            "source_domain_ids",
        ],
        "properties": {
            "domain_id": {"type": "string"},
            "decision": {"type": "string"},
            "reason": {"type": "string"},
            "source_domain_ids": {"type": "array", "items": {"type": "string"}},
            "merged_into": {"type": "string"},
        },
    }


def _consolidation_schema() -> dict[str, Any]:
    """Build the response schema for LLM-assisted domain consolidation."""

    return {
        "type": "object",
        "required": ["curated_domains", "rejected_or_merged_domains"],
        "properties": {
            "curated_domains": {
                "type": "array",
                "minItems": 1,
                "items": _curated_domain_schema(),
            },
            "rejected_or_merged_domains": {
                "type": "array",
                "items": _rejected_domain_schema(),
            },
        },
    }


def _build_domain_proposal_prompt(
    parcels: list[dict[str, str | int]],
    cfg: DomainPoolConfig,
    run_index: int,
) -> str:
    """Build one discovery-driven domain proposal prompt."""

    return "\n".join(
        [
            "Role",
            "You are designing a coarse-domain pool for target-region movie-fMRI",
            "feature discovery.",
            "",
            "Task",
            f"Target brain region: {cfg.target_region}",
            f"Proposal run: {run_index} of {cfg.proposal_runs}",
            "Infer coarse domains from the atlas label space and relevant",
            "neuroscience knowledge. Treat this run as an independent",
            "omission-control pass over the same evidence.",
            "Do not generate detailed active dimensions, fixed feature lists,",
            "scoring scales, or feature columns.",
            "",
            "Viewer-Centric Perspective",
            "Define every domain from the perspective of a typical viewer",
            "watching the movie.",
            "Use the typical viewer watching the movie as the inference subject.",
            "The model is simulating what that viewer can",
            "infer, appraise, track, or integrate from the described segment.",
            "Character states, dialogue, actions, facial expressions, outcomes,",
            "and scene atmosphere are evidence available to the viewer. They are",
            "not the subject of the domain.",
            "For emotion-related domains, do not define the domain as the emotion",
            "a character experiences. Define it as the viewer's inferred",
            "emotional experience, affective appraisal, or emotion-relevant",
            "interpretation grounded in character and narrative evidence.",
            "",
            "Domain Construction Rules",
            "- Do not use a predefined checklist of functional lenses.",
            "- Do not deliberately invent exotic categories just to create",
            "  diversity across runs.",
            "- Each domain should be distinct, target-region relevant, and scoreable later",
            "  from text-only dense movie descriptions.",
            "- Each domain should be coarse enough to organize multiple later",
            "  active dimensions, but concrete enough for text-scoreable variables.",
            "- Use short, human-readable ASCII snake_case domain_id values that",
            "  are clear enough for review.",
            "",
            "Required Anchors",
            _render_required_anchor_block(cfg),
            "",
            "Output JSON Contract",
            "Return only a JSON object that matches the provided response schema.",
            "Do not wrap the response in markdown and do not add explanatory prose.",
            "The object contains candidate_domains. Each candidate domain must",
            "include domain_id, definition, region_relevance, and scoreability_note.",
            "",
            "Inputs",
            "Atlas label space summary:",
            render_label_space_summary(parcels),
        ],
    )


def _build_domain_consolidation_prompt(
    candidates: list[CandidateDomain],
    cfg: DomainPoolConfig,
) -> str:
    """Build the consolidation prompt over all proposal-run candidates."""

    candidate_payload = [candidate.to_dict() for candidate in candidates]
    return "\n".join(
        [
            "Role",
            "You consolidate proposal runs into an auditable coarse-domain pool",
            "for target-region movie-fMRI feature discovery.",
            "",
            "Task",
            f"Target brain region: {cfg.target_region}",
            "Consolidate the input candidate domains into one draft domain pool",
            "for later active-dimension generation. The result is still a draft:",
            "a human must confirm it before active dimensions are generated.",
            "",
            "Viewer-Centric Perspective",
            "Define every domain from the perspective of a typical viewer",
            "watching the movie.",
            "Use the typical viewer watching the movie as the inference subject.",
            "The model is simulating what that viewer can",
            "infer, appraise, track, or integrate from the described segment.",
            "Character states, dialogue, actions, facial expressions, outcomes,",
            "and scene atmosphere are evidence available to the viewer. They are",
            "not the subject of the domain.",
            "For emotion-related domains, do not define the domain as the emotion",
            "a character experiences. Define it as the viewer's inferred",
            "emotional experience, affective appraisal, or emotion-relevant",
            "interpretation grounded in character and narrative evidence.",
            "",
            "Domain Construction Rules",
            "- Retain recurring domains when their functional meaning is distinct.",
            "- Retain a single-run domain only when it is target-region relevant,",
            "  scoreable from dense descriptions, and non-redundant.",
            "- Merge domains with overlapping functional meaning or evidence",
            "  requirements.",
            "- Reject domains that are too expansive or underspecified, too",
            "  fine-grained, weakly relevant, poorly scoreable from text, or",
            "  redundant after merging.",
            "- Preserve source_domain_ids so recurrence and source-run evidence",
            "  remain auditable.",
            "- Every source_domain_ids value must be copied exactly from a",
            "  domain_id in Candidate domains JSON. Do not invent new",
            "  source_domain_ids for consolidated domains.",
            "- Keep only coarse domains; do not add detailed active",
            "  dimensions.",
            "",
            "Required Anchors",
            _render_required_anchor_block(cfg),
            "",
            "Output JSON Contract",
            "Return only a JSON object that matches the provided response schema.",
            "Do not wrap the response in markdown and do not add explanatory prose.",
            "The object contains curated_domains and rejected_or_merged_domains.",
            "Every curated or rejected/merged record must preserve source_domain_ids",
            "copied exactly from the input candidate domain_id values.",
            "",
            "Inputs",
            "Candidate domains are provided below as JSON.",
            "Use these records only as evidence for consolidation.",
            "Do not treat candidate definitions as automatically authoritative",
            "when they conflict with required anchors or the viewer-centric",
            "perspective.",
            "",
            "Candidate domains JSON:",
            json.dumps(candidate_payload, ensure_ascii=False, indent=2),
        ],
    )


def _candidate_id(raw_id: str, source_run: int) -> str:
    """Prefix candidate ids with run ids so cross-run references are unambiguous."""

    return f"run_{source_run}_{raw_id.strip()}"


def _candidate_domains_from_payload(
    payload: dict[str, Any],
    source_run: int,
) -> list[CandidateDomain]:
    """Convert one proposal response into stamped candidate-domain records."""

    candidates: list[CandidateDomain] = []
    candidate_items = payload.get("candidate_domains", [])
    if not candidate_items:
        raise ValueError(f"Proposal run {source_run} returned no candidate_domains.")
    for item in candidate_items:
        candidate = CandidateDomain.from_dict(
            {
                **item,
                "domain_id": _candidate_id(str(item["domain_id"]), source_run),
                "source_run": source_run,
            },
        )
        candidates.append(candidate)
    return candidates


def _generate_candidate_domains_for_run(
    parcels: list[dict[str, str | int]],
    cfg: DomainPoolConfig,
    run_index: int,
) -> list[CandidateDomain]:
    """Generate and validate one proposal run."""

    payload = generate_structured_json(
        model=cfg.generation_model,
        system_instruction=DOMAIN_PROPOSAL_SYSTEM_INSTRUCTION,
        contents=[_build_domain_proposal_prompt(parcels, cfg, run_index)],
        response_schema=_proposal_schema(),
        cfg=cfg,
    )
    try:
        return _candidate_domains_from_payload(payload, run_index)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Domain proposal run {run_index} returned malformed candidate_domains: {exc}",
        ) from exc


def _candidate_domains_with_required_seeds(
    candidates: list[CandidateDomain],
    target_region: str,
) -> list[CandidateDomain]:
    """Prepend required seeds unless a caller already supplied them."""

    required = required_domain_candidates(target_region)
    existing_ids = {candidate.domain_id for candidate in candidates}
    seeded = [
        candidate for candidate in required if candidate.domain_id not in existing_ids
    ]
    return [*seeded, *candidates]


def _candidate_source_runs(
    source_domain_ids: tuple[str, ...],
    candidates_by_id: dict[str, CandidateDomain],
    *,
    domain_id: str,
    record_type: str,
) -> tuple[int, ...]:
    """Return sorted source-run ids referenced by a consolidated domain."""

    if not source_domain_ids:
        raise ValueError(
            f"{record_type} {domain_id!r} must include source_domain_ids.",
        )
    missing_ids = [
        source_id for source_id in source_domain_ids if source_id not in candidates_by_id
    ]
    if missing_ids:
        preview_ids = ", ".join(list(candidates_by_id)[:10])
        raise ValueError(
            f"{record_type} {domain_id!r} references unknown source_domain_ids: "
            f"{', '.join(missing_ids)}. Use exact candidate domain_id values "
            f"such as: {preview_ids}.",
        )
    runs = {
        candidates_by_id[domain_id].source_run
        for domain_id in source_domain_ids
    }
    return tuple(sorted(runs))


def _curated_domains_from_payload(
    payload: dict[str, Any],
    candidates: list[CandidateDomain],
) -> list[CuratedDomain]:
    """Convert consolidation output into curated-domain records."""

    candidates_by_id = {candidate.domain_id: candidate for candidate in candidates}
    curated: list[CuratedDomain] = []
    for item in payload.get("curated_domains", []):
        source_domain_ids = tuple(str(value).strip() for value in item.get("source_domain_ids", []))
        source_runs = _candidate_source_runs(
            source_domain_ids,
            candidates_by_id,
            domain_id=str(item.get("domain_id", "")).strip(),
            record_type="Curated domain",
        )
        curated.append(
            CuratedDomain.from_dict(
                {
                    **item,
                    "source_domain_ids": list(source_domain_ids),
                    "source_runs": list(source_runs),
                    "proposal_frequency": len(source_runs),
                },
            ),
        )
    return curated


def validate_required_domains(pool: DomainPool) -> None:
    """Require ROI-specific pre-registered domains to survive consolidation."""

    required_ids = required_domain_ids_for_region(pool.target_region)
    if not required_ids:
        return
    required_seeds = required_domain_seeds_for_region(pool.target_region)
    curated_by_id = {
        domain.domain_id: domain for domain in pool.curated_domains
    }
    curated_ids = set(curated_by_id)
    missing = [
        domain_id for domain_id in required_ids if domain_id not in curated_ids
    ]
    if missing:
        raise ValueError(
            "Domain pool missing required domain(s): " + ", ".join(missing),
        )
    for domain_id in required_ids:
        domain = curated_by_id[domain_id]
        seed = required_seeds[domain_id]
        seed_source_id = str(seed["domain_id"])
        seed_source_run = int(seed["source_run"])
        if seed_source_id not in domain.source_domain_ids:
            raise ValueError(
                f"Required domain {domain_id!r} must preserve source_domain_ids "
                f"including {seed_source_id!r}.",
            )
        if seed_source_run not in domain.source_runs:
            raise ValueError(
                f"Required domain {domain_id!r} must preserve source_runs "
                f"including {seed_source_run}.",
            )
        canonical_definition = str(seed["definition"]).strip()
        if domain.definition != canonical_definition:
            raise ValueError(
                f"Required domain {domain_id!r} must preserve canonical "
                "definition exactly. Expected "
                f"{canonical_definition!r}; got {domain.definition!r}.",
            )


def _rejected_domains_from_payload(
    payload: dict[str, Any],
    candidates: list[CandidateDomain],
) -> list[RejectedOrMergedDomain]:
    """Convert consolidation output into rejected/merged-domain records."""

    candidates_by_id = {candidate.domain_id: candidate for candidate in candidates}
    rejected: list[RejectedOrMergedDomain] = []
    for item in payload.get("rejected_or_merged_domains", []):
        source_domain_ids = tuple(str(value).strip() for value in item.get("source_domain_ids", []))
        source_runs = _candidate_source_runs(
            source_domain_ids,
            candidates_by_id,
            domain_id=str(item.get("domain_id", "")).strip(),
            record_type="Rejected or merged domain",
        )
        rejected.append(
            RejectedOrMergedDomain.from_dict(
                {
                    **item,
                    "source_domain_ids": list(source_domain_ids),
                    "source_runs": list(source_runs),
                },
            ),
        )
    return rejected


def render_domain_pool_summary(pool: DomainPool) -> str:
    """Render confirmed coarse domains for region-schema conditioning."""

    lines: list[str] = [
        f"Domain pool version: {pool.version}",
        f"Domain pool target region: {pool.target_region}",
        f"Curation status: {pool.curation_status}",
        "Curated coarse domains:",
    ]
    for domain in pool.curated_domains:
        lines.extend(
            [
                f"- {domain.domain_id}",
                f"  definition: {domain.definition}",
                f"  target-region relevance: {domain.region_relevance}",
                f"  scoreability: {domain.scoreability_note}",
                f"  proposal_frequency: {domain.proposal_frequency}",
                f"  source_runs: {list(domain.source_runs)}",
            ],
        )
    return "\n".join(lines)


def build_domain_pool(
    parcels: list[dict[str, str | int]],
    cfg: DomainPoolConfig,
) -> DomainPool:
    """Generate a draft target-region coarse-domain pool with the configured LLM."""

    if cfg.proposal_runs < 1:
        raise ValueError("proposal_runs must be at least 1.")

    candidates: list[CandidateDomain] = []
    for run_index in range(1, cfg.proposal_runs + 1):
        candidates.extend(_generate_candidate_domains_for_run(parcels, cfg, run_index))
    candidates = _candidate_domains_with_required_seeds(candidates, cfg.target_region)

    consolidation_prompt = _build_domain_consolidation_prompt(candidates, cfg)
    consolidation_payload = generate_structured_json(
        model=cfg.generation_model,
        system_instruction=DOMAIN_CONSOLIDATION_SYSTEM_INSTRUCTION,
        contents=[consolidation_prompt],
        response_schema=_consolidation_schema(),
        cfg=cfg,
    )
    try:
        curated_domains = tuple(
            _curated_domains_from_payload(consolidation_payload, candidates),
        )
        rejected_or_merged_domains = tuple(
            _rejected_domains_from_payload(consolidation_payload, candidates),
        )
        validate_required_domains(
            DomainPool(
                version=DOMAIN_POOL_VERSION,
                target_region=cfg.target_region,
                curation_status="draft",
                source_model=cfg.generation_model,
                proposal_runs=cfg.proposal_runs,
                candidate_domains=tuple(candidates),
                curated_domains=curated_domains,
                rejected_or_merged_domains=rejected_or_merged_domains,
            ),
        )
    except ValueError as exc:
        raise RuntimeError(
            "Domain-pool consolidation returned invalid curated or rejected "
            f"records: {exc}",
        ) from exc

    required_ids = required_domain_ids_for_region(cfg.target_region)
    metadata = {
        "generation_parameters": {
            "provider": cfg.generation_provider,
            "temperature": cfg.temperature,
            "proposal_runs": cfg.proposal_runs,
        },
        "required_domain_ids": list(required_ids),
        "confirmation_instructions": (
            "Review curated_domains and rejected_or_merged_domains, then set "
            "curation_status to 'confirmed' before passing this pool to "
            "make-region-schema --domain-pool."
        ),
    }
    if required_ids:
        metadata["required_seed_source_run"] = REQUIRED_SEED_SOURCE_RUN

    pool = DomainPool(
        version=DOMAIN_POOL_VERSION,
        target_region=cfg.target_region,
        curation_status="draft",
        source_model=cfg.generation_model,
        proposal_runs=cfg.proposal_runs,
        candidate_domains=tuple(candidates),
        curated_domains=curated_domains,
        rejected_or_merged_domains=rejected_or_merged_domains,
        metadata=metadata,
    )
    validate_required_domains(pool)
    return pool


def save_domain_pool(pool: DomainPool, path: str | Path) -> None:
    """Persist a domain pool to disk."""

    write_json(path, pool.to_dict())


def load_domain_pool(path: str | Path) -> DomainPool:
    """Load a domain pool from disk."""

    pool = DomainPool.from_dict(read_json(path))
    validate_required_domains(pool)
    return pool


def load_confirmed_domain_pool(path: str | Path) -> DomainPool:
    """Load a domain pool and require human confirmation."""

    pool = load_domain_pool(path)
    if pool.curation_status != "confirmed":
        raise ValueError(
            "Domain pool must have curation_status='confirmed' before "
            "make-region-schema can use it.",
        )
    return pool


def domain_pool_content_hash(path: str | Path) -> str:
    """Return a stable SHA-256 content hash for a domain-pool artifact."""

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
