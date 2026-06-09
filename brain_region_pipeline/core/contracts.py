"""Shared serialized-contract constants for region feature schemas."""

from __future__ import annotations

DOMAIN_POOL_VERSION = "domain_pool_v2"
REGION_SCHEMA_VERSION = "region_schema_v1"

EMOTION_EXPERIENCE_DOMAIN_ID = "emotion_experience"
REQUIRED_EMOTION_EXPERIENCE_SOURCE_ID = "required_emotion_experience"
VMPFC_REQUIRED_DOMAIN_IDS = (EMOTION_EXPERIENCE_DOMAIN_ID,)
REQUIRED_SEED_SOURCE_RUN = 0

ALLOWED_EMOTION_LABELS = (
    "admiration",
    "amusement",
    "excitement",
    "joy",
    "amazement",
    "contentment",
    "relief",
    "tenderness",
    "compassion",
    "confusion",
    "surprise",
    "agitation",
    "anguish",
    "disappointment",
    "uneasiness",
    "disgust",
    "contempt",
    "fear",
    "anger",
    "sadness",
)

CORE_EMOTION_LABELS = (
    "admiration",
    "amusement",
    "joy",
    "tenderness",
    "confusion",
    "surprise",
    "agitation",
    "sadness",
)

CORE_EMOTION_DIMENSION_IDS = tuple(
    f"emotion_{label}" for label in CORE_EMOTION_LABELS
)

EMOTION_DIMENSION_PREFIX = "emotion_"
MIN_EMOTION_DIMENSIONS = len(CORE_EMOTION_LABELS)
MAX_EMOTION_DIMENSIONS = 12

REQUIRED_DOMAIN_SEEDS = {
    EMOTION_EXPERIENCE_DOMAIN_ID: {
        "domain_id": REQUIRED_EMOTION_EXPERIENCE_SOURCE_ID,
        "definition": (
            "The inferred emotional experience a typical viewer would have "
            "while watching a described movie segment, grounded in observable "
            "narrative evidence such as character states, dialogue, actions, "
            "consequences, situational stakes, and scene atmosphere."
        ),
        "region_relevance": (
            "Emotion experience is a required anchor domain for target-region "
            "feature discovery because naturalistic movie responses often "
            "depend on affective meaning, safety appraisal, and viewer-state "
            "inference."
        ),
        "scoreability_note": (
            "Score only from text evidence in dense descriptions; do not infer "
            "viewer emotion from genre labels or unstated audiovisual cues."
        ),
        "source_run": REQUIRED_SEED_SOURCE_RUN,
    },
}


def required_domain_ids_for_region(target_region: str) -> tuple[str, ...]:
    """Return ROI-specific required coarse-domain ids.

    `emotion_experience` is a vmPFC anchor, not a global multi-ROI contract.
    Other ROIs may still discover emotion-related domains from evidence, but
    the pipeline must not force that domain into their domain pools or schemas.
    """

    if target_region.strip().lower() == "vmpfc":
        return VMPFC_REQUIRED_DOMAIN_IDS
    return ()


def required_domain_seeds_for_region(target_region: str) -> dict[str, dict[str, object]]:
    """Return required seed payloads for the target region."""

    return {
        domain_id: REQUIRED_DOMAIN_SEEDS[domain_id]
        for domain_id in required_domain_ids_for_region(target_region)
    }
