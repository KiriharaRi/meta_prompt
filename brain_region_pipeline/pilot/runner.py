"""Stage orchestration for the Friends multi-ROI pilot workflow."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

import h5py

from ..atlas.roi_config import (
    RoiDefinition,
    load_roi_definitions,
    select_roi_definitions,
    validate_roi_definitions_against_atlas,
)
from ..core.config import (
    DEFAULT_GENERATION_MODEL,
    DEFAULT_GENERATION_PROVIDER,
    DomainPoolConfig,
    RegionSchemaConfig,
    RidgeEncodingConfig,
    ScoreDescriptionsConfig,
    SummaryDescriptionsConfig,
    normalize_generation_provider,
)
from ..core.dependencies import (
    PipelineDependencies,
    default_dependencies,
)
from ..core.io_utils import read_json
from ..encoding.runner import RoiEncodingInput, fit_roi_encoding_from_manifest
from ..schema_design.domain_pool import load_domain_pool, save_domain_pool
from ..schema_design.runner import (
    DomainPoolInput,
    RegionSchemaInput,
    make_domain_pool,
    make_region_schema,
)
from ..scoring.runner import (
    ScoreDescriptionsInput,
    score_descriptions_from_file,
)
from ..scoring.summary_generator import (
    SummaryDescriptionsInput,
    summarize_descriptions_from_file,
)
from .artifacts import PilotArtifacts


PILOT_STAGES = (
    "summaries",
    "domain-pools",
    "schemas",
    "scoring",
    "manifest",
    "encoding",
    "all",
)


@dataclass(frozen=True)
class PilotEpisode:
    """One episode sample used by the multi-ROI pilot."""

    episode_id: str
    split: str
    descriptions: Path
    h5_dataset: str


@dataclass(frozen=True)
class PilotEncodingTrim:
    """Encoding-time trim settings written into generated manifest rows."""

    fmri_trim_start_tr: int = 5
    fmri_trim_end_tr: int = 5


@dataclass(frozen=True)
class PilotConfig:
    """Validated run configuration for the multi-ROI pilot."""

    config_path: Path
    roi_definitions: Path
    atlas_labels: Path
    h5_file: Path
    output_root: Path
    subject_id: str
    rois: tuple[str, ...]
    episodes: tuple[PilotEpisode, ...]
    generation_provider: str
    generation_model: str
    proposal_runs: int
    tr_s: float
    scoring_batch_size: int
    local_buffer_size: int
    lags: tuple[int, ...]
    alphas: tuple[float, ...]
    encoding_trim: PilotEncodingTrim


def _log(message: str) -> None:
    print(f"[brain_region_pipeline] {message}", flush=True)


def _resolve_path(raw_path: str, config_dir: Path) -> Path:
    """Resolve paths relative to the pilot config file."""

    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (config_dir / path).resolve()


def _tuple_ints(values: Sequence[Any], field: str) -> tuple[int, ...]:
    """Normalize integer lists from run config."""

    parsed = tuple(int(value) for value in values)
    if not parsed:
        raise ValueError(f"Pilot config field {field!r} cannot be empty.")
    if any(value < 0 for value in parsed):
        raise ValueError(f"Pilot config field {field!r} cannot contain negative values.")
    return parsed


def _tuple_floats(values: Sequence[Any], field: str) -> tuple[float, ...]:
    """Normalize positive float lists from run config."""

    parsed = tuple(float(value) for value in values)
    if not parsed:
        raise ValueError(f"Pilot config field {field!r} cannot be empty.")
    if any(value <= 0 for value in parsed):
        raise ValueError(f"Pilot config field {field!r} must contain positive values.")
    return parsed


def _nonnegative_int(value: Any, field: str) -> int:
    """Parse a non-negative integer from the pilot config."""

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Pilot config field {field!r} must be an integer.") from exc
    if parsed < 0:
        raise ValueError(f"Pilot config field {field!r} cannot be negative.")
    return parsed


def _load_encoding_trim(payload: dict[str, Any]) -> PilotEncodingTrim:
    """Load encoding trim config, defaulting to notebook-compatible 5/5 fMRI trim."""

    raw_trim = payload.get("encoding_trim", {})
    if raw_trim is None:
        raw_trim = {}
    if not isinstance(raw_trim, dict):
        raise ValueError("Pilot config field 'encoding_trim' must be an object.")
    return PilotEncodingTrim(
        fmri_trim_start_tr=_nonnegative_int(
            raw_trim.get("fmri_trim_start_tr", 5),
            "encoding_trim.fmri_trim_start_tr",
        ),
        fmri_trim_end_tr=_nonnegative_int(
            raw_trim.get("fmri_trim_end_tr", 5),
            "encoding_trim.fmri_trim_end_tr",
        ),
    )


def load_pilot_config(path: str | Path) -> PilotConfig:
    """Load and validate a multi-ROI pilot JSON config."""

    config_path = Path(path)
    config_dir = config_path.parent
    payload = read_json(config_path)
    episodes_payload = payload.get("episodes")
    if not isinstance(episodes_payload, list) or not episodes_payload:
        raise ValueError("Pilot config must include a non-empty episodes list.")
    rois = tuple(str(roi_id).strip() for roi_id in payload.get("rois", []) if str(roi_id).strip())
    if not rois:
        raise ValueError("Pilot config must include a non-empty rois list.")
    episodes = tuple(
        PilotEpisode(
            episode_id=str(item["episode_id"]).strip(),
            split=str(item["split"]).strip(),
            descriptions=_resolve_path(str(item["descriptions"]), config_dir),
            h5_dataset=str(item["h5_dataset"]).strip(),
        )
        for item in episodes_payload
    )
    splits = {episode.split for episode in episodes}
    missing = {"train", "val", "test"} - splits
    if missing:
        raise ValueError("Pilot config episodes are missing split(s): " + ", ".join(sorted(missing)))
    return PilotConfig(
        config_path=config_path,
        roi_definitions=_resolve_path(str(payload["roi_definitions"]), config_dir),
        atlas_labels=_resolve_path(str(payload["atlas_labels"]), config_dir),
        h5_file=_resolve_path(str(payload["h5_file"]), config_dir),
        output_root=_resolve_path(str(payload["output_root"]), config_dir),
        subject_id=str(payload.get("subject_id", "sub-01")).strip(),
        rois=rois,
        episodes=episodes,
        generation_provider=normalize_generation_provider(
            str(payload.get("generation_provider", DEFAULT_GENERATION_PROVIDER)),
        ),
        generation_model=str(payload.get("generation_model", DEFAULT_GENERATION_MODEL)).strip(),
        proposal_runs=int(payload.get("proposal_runs", 5)),
        tr_s=float(payload.get("tr_s", 1.49)),
        scoring_batch_size=int(payload.get("scoring_batch_size", 40)),
        local_buffer_size=int(payload.get("local_buffer_size", 10)),
        lags=_tuple_ints(payload.get("lags", [2, 3, 4, 5, 6]), "lags"),
        alphas=_tuple_floats(
            payload.get(
                "alphas",
                [0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30, 100, 300, 1000, 3000, 10000],
            ),
            "alphas",
        ),
        encoding_trim=_load_encoding_trim(payload),
    )


def _episode_ids(config: PilotConfig) -> list[str]:
    """Return configured episode ids in run order."""

    return [episode.episode_id for episode in config.episodes]


# Transitional helpers keep existing script imports stable while the artifact
# graph becomes the public place for pilot paths.
def _summary_path(config: PilotConfig, episode: PilotEpisode) -> Path:
    return PilotArtifacts(config).summary_path(episode)


def _roi_dir(config: PilotConfig, roi_id: str) -> Path:
    return PilotArtifacts(config).roi_dir(roi_id)


def _domain_pool_draft_path(config: PilotConfig, roi_id: str) -> Path:
    return PilotArtifacts(config).domain_pool_draft_path(roi_id)


def _domain_pool_auto_confirmed_path(config: PilotConfig, roi_id: str) -> Path:
    return PilotArtifacts(config).domain_pool_auto_confirmed_path(roi_id)


def _domain_pool_confirmed_path(config: PilotConfig, roi_id: str) -> Path:
    return PilotArtifacts(config).domain_pool_confirmed_path(roi_id)


def _region_schema_path(config: PilotConfig, roi_id: str) -> Path:
    return PilotArtifacts(config).region_schema_path(roi_id)


def _scoring_dir(config: PilotConfig, roi_id: str, episode: PilotEpisode) -> Path:
    return PilotArtifacts(config).scoring_dir(roi_id, episode)


def _encoding_dir(config: PilotConfig) -> Path:
    return PilotArtifacts(config).encoding_dir()


def _manifest_path(config: PilotConfig) -> Path:
    return PilotArtifacts(config).manifest_path()


def _roi_schema_mapping_path(config: PilotConfig) -> Path:
    return PilotArtifacts(config).roi_schema_mapping_path()


def _relative_to(path: Path, base_dir: Path) -> str:
    """Return a portable relative path when possible."""

    return PilotArtifacts.relative_to(path, base_dir)


def _confirm_domain_pool_for_pilot(draft_path: Path, confirmed_path: Path) -> None:
    """Write an auto-confirmed copy of a draft domain pool for pilot use."""

    pool = load_domain_pool(draft_path)
    confirmed = replace(
        pool,
        curation_status="confirmed",
        metadata={
            **dict(pool.metadata),
            "confirmation_mode": "auto_pilot",
            "confirmed_by": "run-multi-roi-pilot",
            "manual_review_required_before_final_claims": True,
            "draft_source_path": str(draft_path),
        },
    )
    save_domain_pool(confirmed, confirmed_path)


def _domain_pool_for_schema(config: PilotConfig, roi_id: str) -> Path:
    """Return the confirmed pool path used for schema generation."""

    return PilotArtifacts(config).domain_pool_for_schema(roi_id)


def _dry_run(config: PilotConfig, rois: Sequence[RoiDefinition], stage: str) -> None:
    """Print the planned pilot run without calling the configured LLM."""

    _log("Dry-run multi-ROI pilot plan")
    _log(f"  Config: {config.config_path}")
    _log(f"  Stage: {stage}")
    _log(f"  Output root: {config.output_root}")
    _log(f"  Generation: {config.generation_provider} / {config.generation_model}")
    _log(f"  ROI count: {len(rois)} -> {', '.join(roi.roi_id for roi in rois)}")
    _log(f"  Episodes: {', '.join(_episode_ids(config))}")
    _log(
        "  Encoding trim: "
        f"fMRI start={config.encoding_trim.fmri_trim_start_tr}, "
        f"fMRI end={config.encoding_trim.fmri_trim_end_tr}",
    )
    _log(f"  Scoring jobs: {len(rois) * len(config.episodes)} ROI x episode runs")
    for episode in config.episodes:
        _log(
            "  "
            f"{episode.split}: {episode.episode_id} descriptions={episode.descriptions} "
            f"h5_dataset={episode.h5_dataset}",
        )


def _validate_episode_inputs(config: PilotConfig) -> None:
    """Validate episode description paths and H5 dataset bindings."""

    for episode in config.episodes:
        if not episode.descriptions.exists():
            raise ValueError(
                f"Episode {episode.episode_id!r} description file does not exist: "
                f"{episode.descriptions}",
            )
    if not config.h5_file.exists():
        raise ValueError(f"Pilot H5 file does not exist: {config.h5_file}")
    with h5py.File(config.h5_file, "r") as handle:
        missing = [
            episode.h5_dataset
            for episode in config.episodes
            if episode.h5_dataset not in handle
        ]
    if missing:
        raise ValueError("Pilot H5 file is missing dataset(s): " + ", ".join(missing))


def _run_summaries(config: PilotConfig) -> None:
    """Generate shared summaries for every configured episode."""

    artifacts = PilotArtifacts(config)
    cfg = SummaryDescriptionsConfig(
        generation_provider=config.generation_provider,
        generation_model=config.generation_model,
    )
    for episode in config.episodes:
        _log(f"Summary stage: {episode.episode_id}")
        summarize_descriptions_from_file(
            SummaryDescriptionsInput(
                descriptions=episode.descriptions,
                output_file=artifacts.summary_path(episode),
            ),
            cfg,
        )


def _run_domain_pools(
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    *,
    deps: PipelineDependencies,
    auto_confirm: bool,
) -> None:
    """Generate domain-pool drafts and optionally auto-confirm pilot copies."""

    artifacts = PilotArtifacts(config)
    for roi in rois:
        _log(f"Domain-pool stage: {roi.roi_id}")
        make_domain_pool(
            DomainPoolInput(
                atlas_labels=config.atlas_labels,
                output_file=artifacts.domain_pool_draft_path(roi.roi_id),
            ),
            DomainPoolConfig(
                generation_provider=config.generation_provider,
                generation_model=config.generation_model,
                target_region=roi.roi_id,
                proposal_runs=config.proposal_runs,
            ),
            deps=deps,
        )
        if auto_confirm:
            _confirm_domain_pool_for_pilot(
                artifacts.domain_pool_draft_path(roi.roi_id),
                artifacts.domain_pool_auto_confirmed_path(roi.roi_id),
            )
            _log(f"  Wrote auto-confirmed domain pool for {roi.roi_id}")


def _run_schemas(
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    *,
    deps: PipelineDependencies,
) -> None:
    """Generate active-dimension schemas using fixed ROI selection rules."""

    artifacts = PilotArtifacts(config)
    for roi in rois:
        _log(f"Schema stage: {roi.roi_id}")
        make_region_schema(
            RegionSchemaInput(
                atlas_labels=config.atlas_labels,
                domain_pool=artifacts.domain_pool_for_schema(roi.roi_id),
                output_file=artifacts.region_schema_path(roi.roi_id),
                roi_definitions=config.roi_definitions,
                roi_id=roi.roi_id,
            ),
            RegionSchemaConfig(
                generation_provider=config.generation_provider,
                generation_model=config.generation_model,
                target_region=roi.roi_id,
            ),
            deps=deps,
        )


def _run_scoring(
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    *,
    deps: PipelineDependencies,
    resume: bool,
    overwrite: bool,
) -> None:
    """Score every ROI and episode against the generated ROI schemas."""

    artifacts = PilotArtifacts(config)
    cfg = ScoreDescriptionsConfig(
        generation_provider=config.generation_provider,
        generation_model=config.generation_model,
        tr_s=config.tr_s,
        scoring_batch_size=config.scoring_batch_size,
        local_buffer_size=config.local_buffer_size,
    )
    for roi in rois:
        for episode in config.episodes:
            _log(f"Scoring stage: {roi.roi_id} / {episode.episode_id}")
            score_descriptions_from_file(
                ScoreDescriptionsInput(
                    descriptions=episode.descriptions,
                    region_schema=artifacts.region_schema_path(roi.roi_id),
                    output_dir=artifacts.scoring_dir(roi.roi_id, episode),
                    model=config.generation_model,
                    tr_s=config.tr_s,
                    total_trs=None,
                    resume=resume,
                    overwrite=overwrite,
                    summary_file=artifacts.summary_path(episode),
                    provider=config.generation_provider,
                    scoring_batch_size=config.scoring_batch_size,
                    local_buffer_size=config.local_buffer_size,
                    gt_dir=None,
                    gt_file_pattern="*.csv",
                    gt_time_column="视频时间(s)",
                    gt_emotion_column="情绪值",
                    alignment="overlap_weighted",
                ),
                cfg,
                deps=deps,
            )


def _write_manifest(config: PilotConfig, rois: Sequence[RoiDefinition]) -> None:
    """Write unified ROI encoding manifest and ROI schema mapping."""

    manifest_path = PilotArtifacts(config).write_encoding_inputs(rois)
    _log(f"Manifest stage complete: {manifest_path}")


def _run_encoding(config: PilotConfig) -> None:
    """Run the joint ROI Ridge encoding stage."""

    artifacts = PilotArtifacts(config)
    fit_roi_encoding_from_manifest(
        RoiEncodingInput(
            manifest=artifacts.manifest_path(),
            roi_schemas=artifacts.roi_schema_mapping_path(),
            atlas_labels=config.atlas_labels,
            output_dir=artifacts.encoding_dir(),
        ),
        RidgeEncodingConfig(
            lags=config.lags,
            alphas=config.alphas,
        ),
    )


def run_multi_roi_pilot(
    args,
    deps: PipelineDependencies | None = None,
) -> None:
    """Run or dry-run the configured multi-ROI pilot workflow."""

    deps = deps or default_dependencies()
    config = load_pilot_config(args.config)
    roi_definitions = load_roi_definitions(config.roi_definitions)
    rois = select_roi_definitions(roi_definitions, config.rois)
    counts = validate_roi_definitions_against_atlas(rois, config.atlas_labels)
    _validate_episode_inputs(config)
    if args.dry_run:
        _dry_run(config, rois, args.stage)
        _log(
            "  Parcel counts: "
            + ", ".join(f"{roi_id}={count}" for roi_id, count in counts.items()),
        )
        return

    config.output_root.mkdir(parents=True, exist_ok=True)
    stages = (
        ("summaries", "domain-pools", "schemas", "scoring", "manifest", "encoding")
        if args.stage == "all"
        else (args.stage,)
    )
    for stage in stages:
        if stage == "summaries":
            _run_summaries(config)
        elif stage == "domain-pools":
            _run_domain_pools(
                config,
                rois,
                deps=deps,
                auto_confirm=args.stage == "all" and not args.no_auto_confirm_domain_pools,
            )
        elif stage == "schemas":
            _run_schemas(config, rois, deps=deps)
        elif stage == "scoring":
            _run_scoring(
                config,
                rois,
                deps=deps,
                resume=args.resume_scoring,
                overwrite=args.overwrite_scoring,
            )
        elif stage == "manifest":
            _write_manifest(config, rois)
        elif stage == "encoding":
            _run_encoding(config)
        else:
            raise ValueError(f"Unsupported pilot stage: {stage!r}")
