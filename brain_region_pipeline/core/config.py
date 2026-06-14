"""Stage-scoped configuration objects for the brain-region prompt pipeline."""

from __future__ import annotations

from dataclasses import dataclass

AIHUBMIX_GENERATION_PROVIDER = "aihubmix"
PACKYAPI_GENERATION_PROVIDER = "packyapi"
GEMINI_GENERATION_PROVIDER = "gemini"
GENERATION_PROVIDERS = (
    AIHUBMIX_GENERATION_PROVIDER,
    PACKYAPI_GENERATION_PROVIDER,
    GEMINI_GENERATION_PROVIDER,
)
DEFAULT_AIHUBMIX_BASE_URL = "https://aihubmix.com/gemini"
DEFAULT_PACKYAPI_BASE_URL = "https://www.packyapi.com/v1"
DEFAULT_AIHUBMIX_MODEL = "gemini-3.5-flash"
DEFAULT_PACKYAPI_MODEL = "mimo-v2.5-pro"
DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"
DEFAULT_GENERATION_PROVIDER = AIHUBMIX_GENERATION_PROVIDER
DEFAULT_GENERATION_MODEL = DEFAULT_AIHUBMIX_MODEL
DEFAULT_ENCODING_LAGS = (2, 3, 4, 5, 6)
DEFAULT_RIDGE_ALPHAS = (
    0.01,
    0.03,
    0.1,
    0.3,
    1.0,
    3.0,
    10.0,
    30.0,
    100.0,
    300.0,
    1000.0,
    3000.0,
    10000.0,
)


def normalize_generation_provider(raw_provider: str) -> str:
    """Validate and normalize a configured generation provider name."""

    provider = raw_provider.strip().lower()
    if provider not in GENERATION_PROVIDERS:
        raise ValueError(
            "Unsupported generation_provider "
            f"{raw_provider!r}; expected one of {', '.join(GENERATION_PROVIDERS)}.",
        )
    return provider


@dataclass(frozen=True)
class GenerationConfig:
    """Shared LLM generation settings used by prompt generation and scoring."""

    generation_provider: str = DEFAULT_GENERATION_PROVIDER
    generation_model: str = DEFAULT_GENERATION_MODEL
    temperature: float = 0.2


@dataclass(frozen=True)
class RegionSchemaConfig(GenerationConfig):
    """Configuration for region-specific feature schema generation."""

    target_region: str = "vmPFC"


@dataclass(frozen=True)
class DomainPoolConfig(GenerationConfig):
    """Configuration for target-region coarse-domain pool generation."""

    target_region: str = "vmPFC"
    proposal_runs: int = 5


@dataclass(frozen=True)
class ScoreDescriptionsConfig(GenerationConfig):
    """Configuration for scoring existing dense descriptions."""

    tr_s: float = 1.49
    alignment_strategy: str = "overlap_weighted"
    scoring_batch_size: int = 40
    local_buffer_size: int = 10


@dataclass(frozen=True)
class SummaryDescriptionsConfig(GenerationConfig):
    """Configuration for rolling narrative summary generation."""

    summary_batch_size: int = 40


@dataclass(frozen=True)
class RidgeEncodingConfig:
    """Configuration for H5 fMRI Ridge encoding runs."""

    lags: tuple[int, ...] = DEFAULT_ENCODING_LAGS
    alphas: tuple[float, ...] = DEFAULT_RIDGE_ALPHAS
