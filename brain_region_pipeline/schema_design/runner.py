"""Stage runners for domain-pool and region-schema generation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ..atlas.labels import build_region_index_map, parse_atlas_labels
from ..atlas.roi_config import load_roi_definitions
from ..core.config import DomainPoolConfig, RegionSchemaConfig
from ..core.dependencies import PipelineDependencies, default_dependencies
from .domain_models import DomainPool
from .domain_pool import (
    domain_pool_content_hash,
    load_confirmed_domain_pool,
    save_domain_pool,
)
from .region_schema import save_region_schema


def _log(message: str) -> None:
    print(f"[brain_region_pipeline] {message}", flush=True)


def make_domain_pool(
    args,
    cfg: DomainPoolConfig,
    deps: PipelineDependencies | None = None,
) -> None:
    """Run stage: atlas + target region -> draft coarse-domain pool."""

    deps = deps or default_dependencies()
    output_path = Path(args.output_file)
    parcels = parse_atlas_labels(args.atlas_labels)
    _log(f"Step 1/1: Build draft domain pool from {cfg.proposal_runs} proposal run(s)")
    pool = deps.build_domain_pool(parcels, cfg)
    save_domain_pool(pool, output_path)
    _log(
        f"  Saved draft domain pool with {len(pool.curated_domains)} curated domain(s) to {output_path}",
    )
    _log("Domain-pool stage complete. Review JSON and set curation_status='confirmed' before region-schema generation.")


def _domain_pool_metadata(path: str | Path, pool: DomainPool) -> dict:
    """Build region-schema provenance metadata for a confirmed domain pool."""

    return {
        "domain_pool": {
            "source_path": str(path),
            "content_sha256": domain_pool_content_hash(path),
            "version": pool.version,
            "target_region": pool.target_region,
            "curation_status": pool.curation_status,
            "proposal_runs": pool.proposal_runs,
            "curated_domain_ids": pool.curated_domain_ids(),
        },
    }


def make_region_schema(
    args,
    cfg: RegionSchemaConfig,
    deps: PipelineDependencies | None = None,
) -> None:
    """Run stage: atlas + target region + domain pool -> region feature schema."""

    deps = deps or default_dependencies()
    output_path = Path(args.output_file)
    parcels = parse_atlas_labels(args.atlas_labels)
    domain_pool_path = args.domain_pool
    if bool(getattr(args, "roi_definitions", None)) != bool(getattr(args, "roi_id", None)):
        raise ValueError("--roi-definitions and --roi-id must be provided together.")
    _log("Step 1/2: Load confirmed domain pool")
    domain_pool = load_confirmed_domain_pool(domain_pool_path)
    if domain_pool.target_region.lower() != cfg.target_region.lower():
        raise ValueError(
            "Domain pool target_region must match make-region-schema "
            f"target_region: {domain_pool.target_region!r} != {cfg.target_region!r}",
        )
    metadata = _domain_pool_metadata(domain_pool_path, domain_pool)
    _log(
        f"  Domain pool ready: {len(domain_pool.curated_domains)} curated domain(s) from {domain_pool_path}",
    )
    _log("Step 2/2: Build region feature schema")
    schema = deps.build_region_schema(parcels, cfg, domain_pool, metadata)
    if getattr(args, "roi_definitions", None) and getattr(args, "roi_id", None):
        roi_definitions = load_roi_definitions(args.roi_definitions)
        if args.roi_id not in roi_definitions:
            raise ValueError(f"ROI id {args.roi_id!r} not found in {args.roi_definitions}.")
        roi_definition = roi_definitions[args.roi_id]
        if roi_definition.roi_id != cfg.target_region:
            raise ValueError(
                "--roi-id must match --target-region when fixed ROI rules are used: "
                f"{roi_definition.roi_id!r} != {cfg.target_region!r}",
            )
        schema = replace(
            schema,
            selection_rules=roi_definition.selection_rules,
            metadata={
                **dict(schema.metadata),
                "fixed_roi_definition": {
                    "roi_id": roi_definition.roi_id,
                    "display_name": roi_definition.display_name,
                    "theoretical_role": roi_definition.theoretical_role,
                    "selection_rules": [
                        rule.to_dict() for rule in roi_definition.selection_rules
                    ],
                },
            },
        )
        _log(f"  Applied fixed selection rules for ROI {roi_definition.roi_id}")
    # Validate selection rules immediately so a bad schema fails before scoring.
    build_region_index_map(schema, parcels)
    save_region_schema(schema, output_path)
    _log(
        f"  Saved region schema with {len(schema.dimensions)} dimension(s) to {output_path}",
    )
    _log("Region-schema stage complete.")

