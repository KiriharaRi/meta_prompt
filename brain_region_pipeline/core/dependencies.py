"""Dependency injection surface for pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .config import DomainPoolConfig, RegionSchemaConfig, ScoreDescriptionsConfig
from ..schema_design.domain_models import DomainPool
from ..schema_design.domain_pool import build_domain_pool
from ..schema_design.region_schema import build_region_schema
from ..schema_design.schema_models import RegionFeatureSchema
from ..scoring.models import DescriptionSegment, SegmentRegionScore
from ..scoring.region_schema_scorer import score_description_segment_batch


@dataclass(frozen=True)
class PipelineDependencies:
    """Dependency injection surface for external calls used by the pipeline."""

    build_domain_pool: Callable[
        [list[dict[str, str | int]], DomainPoolConfig],
        DomainPool,
    ]
    build_region_schema: Callable[
        [list[dict[str, str | int]], RegionSchemaConfig, DomainPool, dict | None],
        RegionFeatureSchema,
    ]
    score_description_segment_batch: Callable[
        [
            int,
            int,
            list[DescriptionSegment],
            RegionFeatureSchema,
            ScoreDescriptionsConfig,
            list[dict[str, Any]] | None,
            list[dict[str, Any]] | None,
        ],
        list[SegmentRegionScore],
    ]


def default_dependencies() -> PipelineDependencies:
    """Return the default dependency set."""

    return PipelineDependencies(
        build_domain_pool=build_domain_pool,
        build_region_schema=build_region_schema,
        score_description_segment_batch=score_description_segment_batch,
    )

