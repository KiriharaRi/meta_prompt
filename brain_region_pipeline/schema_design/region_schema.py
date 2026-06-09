"""Region feature schema generation and persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..atlas.labels import render_label_space_summary
from ..atlas.models import SelectionRule
from ..core.config import RegionSchemaConfig
from ..core.contracts import (
    ALLOWED_EMOTION_LABELS,
    CORE_EMOTION_DIMENSION_IDS,
    CORE_EMOTION_LABELS,
    EMOTION_DIMENSION_PREFIX,
    EMOTION_EXPERIENCE_DOMAIN_ID,
    MAX_EMOTION_DIMENSIONS,
    MIN_EMOTION_DIMENSIONS,
    REGION_SCHEMA_VERSION,
    required_domain_ids_for_region,
)
from ..core.genai import generate_structured_json
from ..core.io_utils import read_json, write_json
from .domain_models import DomainPool
from .domain_pool import render_domain_pool_summary, validate_required_domains
from .schema_models import DimensionSpec, RegionFeatureSchema

MIN_NON_EMOTION_DIMENSIONS_PER_DOMAIN = 3
MAX_NON_EMOTION_DIMENSIONS_PER_DOMAIN = 8
DIMENSION_SCORE_MIN = 0
DIMENSION_SCORE_MAX = 10
DIMENSION_ANCHOR_LABELS = tuple(
    str(score) for score in range(DIMENSION_SCORE_MIN, DIMENSION_SCORE_MAX + 1)
)
MIN_DIMENSION_TRIGGERS = 3
MAX_DIMENSION_TRIGGERS = 6
MIN_DIMENSION_CALIBRATION_EXAMPLES = 2
MAX_DIMENSION_CALIBRATION_EXAMPLES = 4
NON_EMOTION_MECHANISM_EXAMPLES = (
    "safety appraisal",
    "visceral tension",
    "affect regulation",
    "schema violation",
)

REGION_SCHEMA_SYSTEM_INSTRUCTION = """\
You are designing downstream annotation schemas for movie-fMRI brain-activity prediction.

Your task is not to score movie descriptions directly. Your task is to generate
one region-level feature schema that a later LLM will use to annotate existing
dense movie descriptions into numeric features for predicting activity in a
specified brain region.

Given an atlas label space, a target brain region, and a confirmed coarse-domain
pool, infer a region-level feature schema for that region. Represent the
region's functional profile as active scored dimensions that each belong to one
confirmed coarse domain.
"""


def _dimension_schema() -> dict[str, Any]:
    """Build the JSON schema for one active scoring dimension."""

    graded_anchor_schema = {
        "type": "object",
        "required": list(DIMENSION_ANCHOR_LABELS),
        "properties": {
            score: {"type": "string"}
            for score in DIMENSION_ANCHOR_LABELS
        },
    }
    calibration_example_schema = {
        "type": "object",
        "required": ["scene", "score"],
        "properties": {
            "scene": {"type": "string"},
            "score": {"type": "number"},
        },
    }
    return {
        "type": "object",
        "required": [
            "dimension_id",
            "definition",
            "domain",
            "score_min",
            "score_max",
            "trigger_list",
            "graded_anchors",
            "calibration_examples",
            "scoreability_note",
            "exclusion_note",
        ],
        "properties": {
            "dimension_id": {"type": "string"},
            "definition": {"type": "string"},
            "domain": {"type": "string"},
            "score_min": {"type": "number"},
            "score_max": {"type": "number"},
            "trigger_list": {
                "type": "array",
                "minItems": MIN_DIMENSION_TRIGGERS,
                "maxItems": MAX_DIMENSION_TRIGGERS,
                "items": {"type": "string"},
            },
            "graded_anchors": graded_anchor_schema,
            "calibration_examples": {
                "type": "array",
                "minItems": MIN_DIMENSION_CALIBRATION_EXAMPLES,
                "maxItems": MAX_DIMENSION_CALIBRATION_EXAMPLES,
                "items": calibration_example_schema,
            },
            "scoreability_note": {"type": "string"},
            "exclusion_note": {"type": "string"},
        },
    }


def _selection_rule_schema() -> dict[str, Any]:
    """Build the JSON schema for one atlas selection rule."""

    return {
        "type": "object",
        "required": ["networks", "sub_regions", "hemispheres"],
        "properties": {
            "label_ids": {"type": "array", "items": {"type": "integer"}},
            "networks": {"type": "array", "items": {"type": "string"}},
            "sub_regions": {"type": "array", "items": {"type": "string"}},
            "hemispheres": {"type": "array", "items": {"type": "string"}},
        },
    }


def _region_schema_response_schema() -> dict[str, Any]:
    """Build the structured response schema for region-schema generation."""

    return {
        "type": "object",
        "required": [
            "functional_hypothesis",
            "scoring_instruction",
            "selection_rules",
            "dimensions",
        ],
        "properties": {
            "functional_hypothesis": {"type": "string"},
            "scoring_instruction": {"type": "string"},
            "selection_rules": {
                "type": "array",
                "minItems": 1,
                "items": _selection_rule_schema(),
            },
            "dimensions": {
                "type": "array",
                "minItems": 1,
                "items": _dimension_schema(),
            },
        },
    }


def _emotion_experience_is_required(target_region: str) -> bool:
    """Return whether this ROI requires the vmPFC emotion-experience panel."""

    return EMOTION_EXPERIENCE_DOMAIN_ID in required_domain_ids_for_region(target_region)


def _domain_pool_has_emotion_experience(domain_pool: DomainPool) -> bool:
    """Return whether the confirmed pool exposes an emotion-experience domain."""

    return EMOTION_EXPERIENCE_DOMAIN_ID in domain_pool.curated_domain_ids()


def _emotion_granularity_prompt_lines(
    cfg: RegionSchemaConfig,
    domain_pool: DomainPool,
) -> list[str]:
    """Return dimension-design prompt lines for optional/required emotion domains."""

    if _emotion_experience_is_required(cfg.target_region):
        return [
            "- Avoid letting any non-emotion domain dominate the schema, but",
            "  allocate dimensions by target-region relevance, scoreability from",
            "  text, and non-redundancy rather than equal quotas.",
            "- Use emotion_experience as the reference granularity: when a",
            "  non-emotion domain is too broad, split it into a small number of",
            "  discrete, text-scoreable, non-redundant numeric dimensions that",
            "  capture distinct target-region variables. Do not force the same",
            "  label count as emotion_experience.",
        ]
    if _domain_pool_has_emotion_experience(domain_pool):
        return [
            "- Treat emotion_experience as an optional discovered domain for",
            "  this target region. Allocate emotion dimensions only when they",
            "  are target-region relevant, scoreable from text, and",
            "  non-redundant with other confirmed domains.",
        ]
    return [
        "- Allocate dimensions by target-region relevance, scoreability from",
        "  text, and non-redundancy rather than equal quotas.",
    ]


def _emotion_dimension_rule_lines() -> list[str]:
    """Return shared prompt rules for dimensions under emotion_experience."""

    mechanism_examples = ", ".join(NON_EMOTION_MECHANISM_EXAMPLES[:-1])
    return [
        f"- It may contain at most {MAX_EMOTION_DIMENSIONS} total emotion",
        "  dimensions.",
        "- Any dimension in emotion_experience must use dimension_id",
        "  emotion_<label>, where <label> is one of: "
        + ", ".join(ALLOWED_EMOTION_LABELS)
        + ".",
        f"- Do not place non-emotion mechanisms such as {mechanism_examples},",
        f"  or {NON_EMOTION_MECHANISM_EXAMPLES[-1]} inside emotion_experience.",
    ]


def _emotion_requirement_prompt_lines(
    cfg: RegionSchemaConfig,
    domain_pool: DomainPool,
) -> list[str]:
    """Return schema-generation requirements for emotion domains when relevant."""

    if _emotion_experience_is_required(cfg.target_region):
        return [
            "",
            "Emotion-experience requirements:",
            f"- The required domain {EMOTION_EXPERIENCE_DOMAIN_ID!r} is reserved",
            "  for discrete inferred emotional experiences of a typical viewer.",
            "- It must contain the core labels: "
            + ", ".join(CORE_EMOTION_LABELS)
            + ".",
            *_emotion_dimension_rule_lines(),
        ]
    if _domain_pool_has_emotion_experience(domain_pool):
        return [
            "",
            "Optional emotion-experience requirements:",
            f"- The domain {EMOTION_EXPERIENCE_DOMAIN_ID!r} was discovered for",
            "  this target region, but no core emotion panel is required.",
            *_emotion_dimension_rule_lines(),
        ]
    return []


def _schema_content_prompt_lines(cfg: RegionSchemaConfig) -> list[str]:
    """Return the high-level region-schema payload requirements."""

    return [
        f"Target brain region: {cfg.target_region}",
        "Generate one region-level feature schema for predicting activity",
        "in the target brain region from dense movie descriptions.",
        "",
        "The generated schema content should include:",
        "1. A functional_hypothesis explaining why the selected functional",
        "   variables should help predict this region's activity.",
        "2. A scoring_instruction that gives common scoring rules for the",
        "   later description scorer.",
        "3. Region-level atlas selection_rules.",
        "4. Active scored annotation dimensions. Output only active",
        "   dimensions that should become independent numeric feature columns.",
    ]


def _coarse_domain_dimension_prompt_lines(
    cfg: RegionSchemaConfig,
    domain_pool: DomainPool,
) -> list[str]:
    """Return prompt rules that keep active dimensions aligned with validators."""

    # Keep numeric ranges centralized here and in validate_region_schema_quality:
    # PackyAPI receives JSON-object instructions, so Python validation remains
    # the final enforcement layer for every generated schema.
    return [
        "Coarse-domain and dimension design requirements:",
        "- Every active dimension must use one of the confirmed domain_id",
        "  values. Do not invent new domain ids.",
        "- Confirmed domain ids are grouping labels only, not score",
        "  columns. Do not score a domain directly.",
        "- Do not copy a domain_id into dimension_id. Each dimension_id",
        "  must name a finer-grained, text-scoreable variable within its",
        "  confirmed domain.",
        f"- For each retained non-emotion domain, infer "
        f"{MIN_NON_EMOTION_DIMENSIONS_PER_DOMAIN} to "
        f"{MAX_NON_EMOTION_DIMENSIONS_PER_DOMAIN} concrete scoring dimensions",
        "  that capture distinct evidence patterns.",
        "- Different domains may contribute different numbers of dimensions",
        f"  within the per-domain "
        f"{MIN_NON_EMOTION_DIMENSIONS_PER_DOMAIN} to "
        f"{MAX_NON_EMOTION_DIMENSIONS_PER_DOMAIN} range.",
        "- Before answering, count dimensions per confirmed non-emotion",
        "  domain. The local quality gate rejects the schema if any such",
        f"  domain has fewer than "
        f"{MIN_NON_EMOTION_DIMENSIONS_PER_DOMAIN} or more than "
        f"{MAX_NON_EMOTION_DIMENSIONS_PER_DOMAIN} active dimensions.",
        "- Do not leave any confirmed non-emotion domain with only 1 or 2",
        "  dimensions. If a domain is narrow, split it into exactly "
        f"{MIN_NON_EMOTION_DIMENSIONS_PER_DOMAIN} non-overlapping, scoreable",
        "  evidence variables.",
        *_emotion_granularity_prompt_lines(cfg, domain_pool),
        f"- Use a unified {DIMENSION_SCORE_MIN} to {DIMENSION_SCORE_MAX} "
        "intensity scale for every active dimension.",
        f"  score_min must be {DIMENSION_SCORE_MIN} and score_max must be "
        f"{DIMENSION_SCORE_MAX}.",
        f"  A score of {DIMENSION_SCORE_MIN} means the component is absent or",
        f"  cannot be judged from the text; {DIMENSION_SCORE_MAX} means it is",
        "  strongly present.",
        "- Calibrate intensity from the perspective of a typical viewer",
        "  watching the movie, while still scoring the specified",
        "  brain-region narrative/appraisal dimension.",
        "- Each active dimension must include scoreability_note explaining",
        "  what text-only evidence should drive the score.",
        "- Each active dimension must include exclusion_note explaining",
        "  nearby concepts that should not be counted.",
        "- Each active dimension must include trigger_list with "
        f"{MIN_DIMENSION_TRIGGERS} to {MAX_DIMENSION_TRIGGERS} concise event",
        "  or appraisal patterns that should raise the score.",
        "- Each active dimension must include graded_anchors with exactly",
        f"  {len(DIMENSION_ANCHOR_LABELS)} short anchor descriptions keyed as",
        f"  '{DIMENSION_ANCHOR_LABELS[0]}' through '{DIMENSION_ANCHOR_LABELS[-1]}'.",
        "- Each active dimension must include "
        f"{MIN_DIMENSION_CALIBRATION_EXAMPLES} to "
        f"{MAX_DIMENSION_CALIBRATION_EXAMPLES} calibration_examples.",
        "  The local quality gate rejects any active dimension outside this",
        "  calibration_examples range.",
        *_emotion_requirement_prompt_lines(cfg, domain_pool),
    ]


def _selection_rule_prompt_lines() -> list[str]:
    """Return atlas selection-rule semantics for schema generation."""

    return [
        "Selection rule semantics:",
        "- Within one rule, a parcel must satisfy every non-empty field.",
        "- Across multiple rules, the final region selects the union.",
    ]


def _build_prompt(
    parcels: list[dict[str, str | int]],
    cfg: RegionSchemaConfig,
    domain_pool: DomainPool,
) -> str:
    """Build the meta prompt for target-region schema generation."""

    return "\n".join(
        [
            *_schema_content_prompt_lines(cfg),
            "",
            "Confirmed coarse-domain pool:",
            render_domain_pool_summary(domain_pool),
            "",
            *_coarse_domain_dimension_prompt_lines(cfg, domain_pool),
            "",
            *_selection_rule_prompt_lines(),
            "",
            "Atlas label space summary:",
            render_label_space_summary(parcels),
        ],
    )


def _active_domain_ids(
    domains: tuple[Any, ...],
    dimensions: tuple[DimensionSpec, ...],
) -> tuple[str, ...]:
    """Return active domain ids in the original domain order."""

    active_domains = {dimension.domain for dimension in dimensions}
    return tuple(
        domain.domain_id for domain in domains if domain.domain_id in active_domains
    )


def normalize_schema_dimension_order(
    schema: RegionFeatureSchema,
) -> RegionFeatureSchema:
    """Return a schema with deterministic output dimension order."""

    by_domain: dict[str, list[DimensionSpec]] = {
        domain.domain_id: [] for domain in schema.domains
    }
    for dimension in schema.dimensions:
        by_domain.setdefault(dimension.domain, []).append(dimension)

    ordered: list[DimensionSpec] = []
    for domain in schema.domains:
        dimensions = by_domain.get(domain.domain_id, [])
        if domain.domain_id == EMOTION_EXPERIENCE_DOMAIN_ID:
            by_id = {dimension.dimension_id: dimension for dimension in dimensions}
            ordered.extend(
                by_id[dimension_id]
                for dimension_id in CORE_EMOTION_DIMENSION_IDS
                if dimension_id in by_id
            )
            ordered.extend(
                dimension
                for dimension in dimensions
                if dimension.dimension_id not in CORE_EMOTION_DIMENSION_IDS
            )
            continue
        ordered.extend(dimensions)

    return RegionFeatureSchema(
        version=schema.version,
        target_region=schema.target_region,
        functional_hypothesis=schema.functional_hypothesis,
        scoring_instruction=schema.scoring_instruction,
        selection_rules=schema.selection_rules,
        domains=schema.domains,
        active_domain_ids=_active_domain_ids(schema.domains, tuple(ordered)),
        dimensions=tuple(ordered),
        metadata=dict(schema.metadata),
    )


def validate_region_schema_quality(
    schema: RegionFeatureSchema,
    domain_pool: DomainPool,
) -> None:
    """Validate generated active dimensions before saving them for scoring."""

    validate_required_domains(domain_pool)
    errors: list[str] = []
    allowed_domain_ids = set(domain_pool.curated_domain_ids())
    dimensions_by_domain = {domain_id: 0 for domain_id in allowed_domain_ids}
    emotion_required = _emotion_experience_is_required(schema.target_region)
    emotion_dimensions: list[DimensionSpec] = []
    emotion_dimension_ids: set[str] = set()

    if tuple(domain_pool.curated_domains) != schema.domains:
        errors.append("schema domains must snapshot all confirmed domain-pool domains")

    for dimension in schema.dimensions:
        if (
            dimension.score_min != DIMENSION_SCORE_MIN
            or dimension.score_max != DIMENSION_SCORE_MAX
        ):
            errors.append(
                f"{dimension.dimension_id}: score range must be "
                f"{DIMENSION_SCORE_MIN} to {DIMENSION_SCORE_MAX}",
            )
        if dimension.domain not in allowed_domain_ids:
            errors.append(
                f"{dimension.dimension_id}: domain {dimension.domain!r} is not "
                "in the confirmed domain pool",
            )
        else:
            dimensions_by_domain[dimension.domain] += 1
        if dimension.dimension_id == dimension.domain:
            errors.append(
                f"{dimension.dimension_id}: dimension_id must name a scoreable "
                "variable under the domain, not repeat the domain_id",
            )
        elif dimension.dimension_id in allowed_domain_ids:
            errors.append(
                f"{dimension.dimension_id}: dimension_id must not reuse a "
                "confirmed domain_id",
            )
        if not dimension.scoreability_note:
            errors.append(f"{dimension.dimension_id}: scoreability_note is required")
        if not dimension.exclusion_note:
            errors.append(f"{dimension.dimension_id}: exclusion_note is required")
        if not MIN_DIMENSION_TRIGGERS <= len(dimension.trigger_list) <= MAX_DIMENSION_TRIGGERS:
            errors.append(
                f"{dimension.dimension_id}: trigger_list must include "
                f"{MIN_DIMENSION_TRIGGERS} to {MAX_DIMENSION_TRIGGERS} items",
            )
        missing_anchors = [
            score
            for score in DIMENSION_ANCHOR_LABELS
            if not dimension.graded_anchors.get(score)
        ]
        if missing_anchors:
            errors.append(
                f"{dimension.dimension_id}: graded_anchors missing {missing_anchors}",
            )
        if (
            not MIN_DIMENSION_CALIBRATION_EXAMPLES
            <= len(dimension.calibration_examples)
            <= MAX_DIMENSION_CALIBRATION_EXAMPLES
        ):
            errors.append(
                f"{dimension.dimension_id}: calibration_examples must include "
                f"{MIN_DIMENSION_CALIBRATION_EXAMPLES} to "
                f"{MAX_DIMENSION_CALIBRATION_EXAMPLES} items",
            )
        for example in dimension.calibration_examples:
            score = float(example.get("score", -1))
            if score < dimension.score_min or score > dimension.score_max:
                errors.append(
                    f"{dimension.dimension_id}: calibration example score {score:g} "
                    "is outside the dimension score range",
                )

        if dimension.domain == EMOTION_EXPERIENCE_DOMAIN_ID:
            emotion_dimensions.append(dimension)
            emotion_dimension_ids.add(dimension.dimension_id)
            if emotion_required and not dimension.dimension_id.startswith(EMOTION_DIMENSION_PREFIX):
                errors.append(
                    f"{dimension.dimension_id}: emotion_experience dimensions "
                    "must use emotion_<label> ids",
                )
            elif emotion_required:
                label = dimension.dimension_id.removeprefix(EMOTION_DIMENSION_PREFIX)
                if label not in ALLOWED_EMOTION_LABELS:
                    errors.append(
                        f"{dimension.dimension_id}: emotion label {label!r} is not allowed",
                    )
        elif emotion_required and dimension.dimension_id.startswith(EMOTION_DIMENSION_PREFIX):
            errors.append(
                f"{dimension.dimension_id}: emotion_* dimensions must use "
                f"domain {EMOTION_EXPERIENCE_DOMAIN_ID!r}",
            )

    if emotion_required and not MIN_EMOTION_DIMENSIONS <= len(emotion_dimensions) <= MAX_EMOTION_DIMENSIONS:
        errors.append(
            f"{EMOTION_EXPERIENCE_DOMAIN_ID} must contain "
            f"{MIN_EMOTION_DIMENSIONS} to {MAX_EMOTION_DIMENSIONS} emotion dimensions",
        )
    elif emotion_dimensions and len(emotion_dimensions) > MAX_EMOTION_DIMENSIONS:
        errors.append(
            f"{EMOTION_EXPERIENCE_DOMAIN_ID} may contain at most "
            f"{MAX_EMOTION_DIMENSIONS} emotion dimensions",
        )

    if emotion_required:
        missing_core = [
            dimension_id
            for dimension_id in CORE_EMOTION_DIMENSION_IDS
            if dimension_id not in emotion_dimension_ids
        ]
        if missing_core:
            errors.append("missing core emotion dimension(s): " + ", ".join(missing_core))

    for domain_id, dimension_count in sorted(dimensions_by_domain.items()):
        if domain_id == EMOTION_EXPERIENCE_DOMAIN_ID:
            continue
        if not MIN_NON_EMOTION_DIMENSIONS_PER_DOMAIN <= dimension_count <= MAX_NON_EMOTION_DIMENSIONS_PER_DOMAIN:
            errors.append(
                f"{domain_id}: non-emotion domains must contain "
                f"{MIN_NON_EMOTION_DIMENSIONS_PER_DOMAIN} to "
                f"{MAX_NON_EMOTION_DIMENSIONS_PER_DOMAIN} active dimensions; "
                f"got {dimension_count}",
            )

    if errors:
        raise ValueError(
            "Generated region schema failed quality screen: " + "; ".join(errors),
        )


def _schema_from_payload(
    payload: dict[str, Any],
    cfg: RegionSchemaConfig,
    domain_pool: DomainPool,
    metadata: dict[str, Any] | None,
) -> RegionFeatureSchema:
    """Convert structured generation output into a complete region schema."""

    dimensions = tuple(
        DimensionSpec.from_dict(item)
        for item in payload.get("dimensions", [])
    )
    domains = tuple(domain_pool.curated_domains)
    schema = RegionFeatureSchema(
        version=REGION_SCHEMA_VERSION,
        target_region=cfg.target_region,
        functional_hypothesis=str(payload["functional_hypothesis"]).strip(),
        scoring_instruction=str(payload["scoring_instruction"]).strip(),
        selection_rules=tuple(
            SelectionRule.from_dict(rule)
            for rule in payload.get("selection_rules", [])
        ),
        domains=domains,
        active_domain_ids=_active_domain_ids(domains, dimensions),
        dimensions=dimensions,
        metadata={
            **dict(metadata or {}),
            "source_provider": cfg.generation_provider,
            "source_model": cfg.generation_model,
        },
    )
    return normalize_schema_dimension_order(schema)


def build_region_schema(
    parcels: list[dict[str, str | int]],
    cfg: RegionSchemaConfig,
    domain_pool: DomainPool,
    metadata: dict[str, Any] | None = None,
) -> RegionFeatureSchema:
    """Generate a region-specific feature schema with the configured LLM."""

    validate_required_domains(domain_pool)
    payload = generate_structured_json(
        model=cfg.generation_model,
        system_instruction=REGION_SCHEMA_SYSTEM_INSTRUCTION,
        contents=[_build_prompt(parcels, cfg, domain_pool=domain_pool)],
        response_schema=_region_schema_response_schema(),
        cfg=cfg,
    )
    schema = _schema_from_payload(payload, cfg, domain_pool, metadata)
    validate_region_schema_quality(schema, domain_pool=domain_pool)
    return schema


def save_region_schema(schema: RegionFeatureSchema, path: str | Path) -> None:
    """Persist a region feature schema to disk."""

    write_json(path, schema.to_dict())


def load_region_schema(path: str | Path) -> RegionFeatureSchema:
    """Load a region feature schema from disk."""

    return RegionFeatureSchema.from_dict(read_json(path))
