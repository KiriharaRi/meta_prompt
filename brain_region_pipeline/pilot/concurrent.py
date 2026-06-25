"""Concurrent stage jobs for Friends pilot workflows."""

from __future__ import annotations

import json
from argparse import Namespace
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from ..atlas.roi_config import RoiDefinition
from ..core.config import (
    DomainPoolConfig,
    RegionSchemaConfig,
    RidgeEncodingConfig,
    ScoreDescriptionsConfig,
    SummaryDescriptionsConfig,
)
from ..core.dependencies import PipelineDependencies
from ..core.io_utils import read_jsonl, write_jsonl
from ..encoding.runner import fit_roi_encoding_from_manifest
from ..schema_design.domain_pool import load_domain_pool, save_domain_pool
from ..schema_design.region_schema import load_region_schema
from ..schema_design.runner import make_domain_pool, make_region_schema
from ..scoring.checkpoint import scoring_output_paths
from ..scoring.description_io import load_description_segments
from ..scoring.runner import (
    ScoreDescriptionsInput,
    _normalize_batch_score_metadata,
    score_descriptions_from_file,
)
from ..scoring.summary_generator import (
    SummaryDescriptionsInput,
    summarize_descriptions_from_file,
)
from .artifacts import PilotArtifacts

if TYPE_CHECKING:
    from .runner import PilotConfig, PilotEpisode


LogFn = Callable[[str], None]
Job = tuple[str, Callable[[], None]]


def _default_log(message: str) -> None:
    print(f"[brain_region_pipeline] {message}", flush=True)


def run_parallel(
    *,
    stage_name: str,
    workers: int,
    jobs: Sequence[Job],
    log: LogFn = _default_log,
) -> None:
    """Run independent jobs concurrently and report every failed job."""

    if not jobs:
        return
    max_workers = min(workers, len(jobs))
    log(f"{stage_name}: {len(jobs)} job(s), workers={max_workers}")
    failures: list[tuple[str, BaseException]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(job): label for label, job in jobs}
        for future in as_completed(futures):
            label = futures[future]
            try:
                future.result()
                log(f"{stage_name} complete: {label}")
            except BaseException as exc:  # noqa: BLE001 - aggregate and rethrow below.
                failures.append((label, exc))
                log(f"{stage_name} failed: {label}: {exc}")
    if failures:
        lines = "\n".join(f"- {label}: {exc}" for label, exc in failures)
        raise RuntimeError(
            f"{stage_name} failed for {len(failures)} job(s):\n{lines}",
        )


def confirm_domain_pool_for_pilot(draft_path: Path, confirmed_path: Path) -> None:
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


def require_paths(paths: Sequence[Path], *, context: str) -> None:
    """Fail when any expected artifact path is missing."""

    missing = [path for path in paths if not path.exists()]
    if missing:
        details = "\n".join(str(path) for path in missing)
        raise ValueError(f"{context} is missing expected output(s):\n{details}")


def validate_scoring_outputs(
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
    episodes: Sequence[PilotEpisode],
) -> None:
    """Validate scoring artifacts for each ROI/episode pair."""

    artifacts = PilotArtifacts(config)
    paths = []
    for roi in rois:
        for episode in episodes:
            score_dir = artifacts.scoring_dir(roi.roi_id, episode)
            paths.extend(
                [
                    score_dir / "segment_region_scores.jsonl",
                    score_dir / "tr_features.jsonl",
                    score_dir / "scoring_metadata.json",
                    score_dir / "scoring_progress.json",
                ],
            )
    require_paths(paths, context="Scoring validation")


def validate_full_outputs(
    config: PilotConfig,
    rois: Sequence[RoiDefinition],
) -> None:
    """Validate the expected full-run artifact set."""

    artifacts = PilotArtifacts(config)
    paths: list[Path] = []
    for roi in rois:
        paths.extend(
            [
                artifacts.domain_pool_draft_path(roi.roi_id),
                artifacts.domain_pool_auto_confirmed_path(roi.roi_id),
                artifacts.region_schema_path(roi.roi_id),
            ],
        )
    for episode in config.episodes:
        summary_path = artifacts.summary_path(episode)
        paths.extend(
            [
                summary_path,
                summary_path.with_name("summary_metadata.json"),
            ],
        )
    paths.extend(
        [
            artifacts.manifest_path(),
            artifacts.roi_schema_mapping_path(),
            artifacts.encoding_dir() / "group_summary.json",
            artifacts.encoding_dir() / "encoding_metadata.json",
        ],
    )
    require_paths(paths, context="Full-run validation")
    validate_scoring_outputs(config, rois, config.episodes)


@dataclass(frozen=True)
class ConcurrentPilotStages:
    """Run reusable concurrent pilot stages behind one maintained interface."""

    config: PilotConfig
    deps: PipelineDependencies
    log: LogFn = _default_log

    @property
    def artifacts(self) -> PilotArtifacts:
        return PilotArtifacts(self.config)

    def summary_exists(self, episode: PilotEpisode) -> bool:
        summary = self.artifacts.summary_path(episode)
        return summary.exists() and summary.with_name("summary_metadata.json").exists()

    def run_summary_job(
        self,
        *,
        episode: PilotEpisode,
        skip_existing: bool,
    ) -> None:
        """Generate one episode summary unless an existing complete one is reused."""

        summary = self.artifacts.summary_path(episode)
        metadata = summary.with_name("summary_metadata.json")
        if summary.exists() or metadata.exists():
            if skip_existing and summary.exists() and metadata.exists():
                self.log(f"Summary already complete: {episode.episode_id}")
                return
            raise ValueError(
                f"Summary output already exists for {episode.episode_id}; "
                "pass --skip-existing-summaries to reuse complete summary outputs.",
            )
        summarize_descriptions_from_file(
            SummaryDescriptionsInput(
                descriptions=episode.descriptions,
                output_file=summary,
            ),
            SummaryDescriptionsConfig(
                generation_provider=self.config.generation_provider,
                generation_model=self.config.generation_model,
            ),
        )

    def run_summary_jobs(
        self,
        *,
        workers: int,
        skip_existing: bool,
    ) -> None:
        """Generate shared summaries for all configured episodes."""

        jobs: list[Job] = []
        for episode in self.config.episodes:
            if skip_existing and self.summary_exists(episode):
                self.log(f"Summary already complete: {episode.episode_id}")
                continue
            jobs.append(
                (
                    episode.episode_id,
                    lambda episode=episode: self.run_summary_job(
                        episode=episode,
                        skip_existing=skip_existing,
                    ),
                ),
            )
        run_parallel(stage_name="summaries", workers=workers, jobs=jobs, log=self.log)

    def validate_domain_pool(
        self,
        path: Path,
        *,
        roi_id: str,
        expected_status: str | None = None,
    ) -> None:
        pool = load_domain_pool(path)
        if pool.target_region != roi_id:
            raise ValueError(
                f"{path} target_region {pool.target_region!r} != {roi_id!r}.",
            )
        if expected_status and pool.curation_status != expected_status:
            raise ValueError(
                f"{path} curation_status {pool.curation_status!r} != {expected_status!r}.",
            )

    def run_domain_pool_job(self, *, roi: RoiDefinition) -> None:
        """Generate and auto-confirm one ROI domain pool, resuming complete outputs."""

        artifacts = self.artifacts
        draft_path = artifacts.domain_pool_draft_path(roi.roi_id)
        confirmed_path = artifacts.domain_pool_auto_confirmed_path(roi.roi_id)
        if confirmed_path.exists() and not draft_path.exists():
            raise ValueError(
                f"Cannot resume {roi.roi_id}: missing draft domain pool {draft_path}.",
            )
        if draft_path.exists() and confirmed_path.exists():
            self.validate_domain_pool(draft_path, roi_id=roi.roi_id)
            self.validate_domain_pool(
                confirmed_path,
                roi_id=roi.roi_id,
                expected_status="confirmed",
            )
            self.log(f"Domain pool already complete: {roi.roi_id}")
            return
        if not draft_path.exists():
            make_domain_pool(
                Namespace(
                    atlas_labels=str(self.config.atlas_labels),
                    target_region=roi.roi_id,
                    output_file=str(draft_path),
                    model=self.config.generation_model,
                    provider=self.config.generation_provider,
                    proposal_runs=self.config.proposal_runs,
                ),
                DomainPoolConfig(
                    generation_provider=self.config.generation_provider,
                    generation_model=self.config.generation_model,
                    target_region=roi.roi_id,
                    proposal_runs=self.config.proposal_runs,
                ),
                deps=self.deps,
            )
        confirm_domain_pool_for_pilot(draft_path, confirmed_path)
        self.validate_domain_pool(
            confirmed_path,
            roi_id=roi.roi_id,
            expected_status="confirmed",
        )

    def run_domain_pool_jobs(
        self,
        rois: Sequence[RoiDefinition],
        *,
        workers: int,
    ) -> None:
        jobs = [
            (
                roi.roi_id,
                lambda roi=roi: self.run_domain_pool_job(roi=roi),
            )
            for roi in rois
        ]
        run_parallel(stage_name="domain-pools", workers=workers, jobs=jobs, log=self.log)

    def run_schema_job(self, *, roi: RoiDefinition) -> None:
        """Generate one ROI schema, validating existing complete outputs."""

        artifacts = self.artifacts
        schema_path = artifacts.region_schema_path(roi.roi_id)
        if schema_path.exists():
            schema = load_region_schema(schema_path)
            if schema.target_region != roi.roi_id:
                raise ValueError(
                    f"{schema_path} target_region "
                    f"{schema.target_region!r} != {roi.roi_id!r}.",
                )
            self.log(f"Schema already complete: {roi.roi_id}")
            return
        make_region_schema(
            Namespace(
                atlas_labels=str(self.config.atlas_labels),
                target_region=roi.roi_id,
                output_file=str(schema_path),
                model=self.config.generation_model,
                provider=self.config.generation_provider,
                domain_pool=str(artifacts.domain_pool_for_schema(roi.roi_id)),
                roi_definitions=str(self.config.roi_definitions),
                roi_id=roi.roi_id,
            ),
            RegionSchemaConfig(
                generation_provider=self.config.generation_provider,
                generation_model=self.config.generation_model,
                target_region=roi.roi_id,
            ),
            deps=self.deps,
        )

    def run_schema_jobs(
        self,
        rois: Sequence[RoiDefinition],
        *,
        workers: int,
    ) -> None:
        jobs = [
            (
                roi.roi_id,
                lambda roi=roi: self.run_schema_job(roi=roi),
            )
            for roi in rois
        ]
        run_parallel(stage_name="schemas", workers=workers, jobs=jobs, log=self.log)

    def scoring_input(
        self,
        *,
        roi: RoiDefinition,
        episode: PilotEpisode,
        resume: bool,
        overwrite: bool,
    ) -> ScoreDescriptionsInput:
        """Build score-descriptions input for one ROI/episode job."""

        artifacts = self.artifacts
        return ScoreDescriptionsInput(
            descriptions=episode.descriptions,
            region_schema=artifacts.region_schema_path(roi.roi_id),
            output_dir=artifacts.scoring_dir(roi.roi_id, episode),
            model=self.config.generation_model,
            tr_s=self.config.tr_s,
            total_trs=None,
            resume=resume,
            overwrite=overwrite,
            summary_file=artifacts.summary_path(episode),
            provider=self.config.generation_provider,
            scoring_batch_size=self.config.scoring_batch_size,
            local_buffer_size=self.config.local_buffer_size,
            gt_dir=None,
            gt_file_pattern="*.csv",
            gt_time_column="视频时间(s)",
            gt_emotion_column="情绪值",
            alignment="overlap_weighted",
        )

    def score_config(self) -> ScoreDescriptionsConfig:
        """Build the scoring config shared by normal scoring and batch retries."""

        return ScoreDescriptionsConfig(
            generation_provider=self.config.generation_provider,
            generation_model=self.config.generation_model,
            tr_s=self.config.tr_s,
            scoring_batch_size=self.config.scoring_batch_size,
            local_buffer_size=self.config.local_buffer_size,
        )

    def run_scoring_job(
        self,
        *,
        roi: RoiDefinition,
        episode: PilotEpisode,
        overwrite_scoring: bool,
    ) -> None:
        score_descriptions_from_file(
            self.scoring_input(
                roi=roi,
                episode=episode,
                resume=not overwrite_scoring,
                overwrite=overwrite_scoring,
            ),
            self.score_config(),
            deps=self.deps,
        )

    def run_scoring_jobs(
        self,
        rois: Sequence[RoiDefinition],
        episodes: Sequence[PilotEpisode],
        *,
        workers: int,
        overwrite_scoring: bool,
    ) -> None:
        jobs: list[Job] = []
        for roi in rois:
            for episode in episodes:
                jobs.append(
                    (
                        f"{roi.roi_id}/{episode.episode_id}",
                        lambda roi=roi, episode=episode: self.run_scoring_job(
                            roi=roi,
                            episode=episode,
                            overwrite_scoring=overwrite_scoring,
                        ),
                    ),
                )
        run_parallel(stage_name="scoring", workers=workers, jobs=jobs, log=self.log)

    def failed_batch_indices(self, output_dir: Path) -> list[int]:
        """Return sorted failed batch indexes recorded for one scoring output dir."""

        warning_path = scoring_output_paths(output_dir)["warnings"]
        if not warning_path.exists():
            return []
        rows = read_jsonl(warning_path)
        failed = {
            int(row["batch_idx"])
            for row in rows
            if row.get("reason") == "batch_generation_failed_zero_filled"
            and row.get("batch_idx") is not None
        }
        return sorted(failed)

    def replace_score_rows(
        self,
        *,
        output_dir: Path,
        replacement_rows: Sequence,
        batch_idx: int,
    ) -> None:
        """Replace serialized score rows for one batch with retry results."""

        score_path = scoring_output_paths(output_dir)["scores"]
        rows = read_jsonl(score_path)
        replacements = [row.to_dict() for row in replacement_rows]
        replacement_ids = {int(row["segment_id"]) for row in replacements}
        if not replacement_ids:
            raise ValueError(f"Retry for batch {batch_idx} produced no replacement rows.")
        filtered = [
            row
            for row in rows
            if int(row.get("segment_id", -1)) not in replacement_ids
        ]
        combined = sorted(
            [*filtered, *replacements],
            key=lambda row: int(row["segment_id"]),
        )
        if len(combined) != len(rows):
            raise ValueError(
                f"Retry replacement row count mismatch for {output_dir}: "
                f"{len(combined)} != {len(rows)}.",
            )
        write_jsonl(score_path, combined)

    def rewrite_warning_rows(
        self,
        *,
        output_dir: Path,
        retried_batch_idx: int,
        new_warnings: Sequence[dict],
    ) -> None:
        """Drop the old failed-batch warning and keep any new retry warnings."""

        warning_path = scoring_output_paths(output_dir)["warnings"]
        existing = read_jsonl(warning_path) if warning_path.exists() else []
        filtered = [
            row
            for row in existing
            if not (
                row.get("reason") == "batch_generation_failed_zero_filled"
                and int(row.get("batch_idx", -1)) == retried_batch_idx
            )
        ]
        rows = [*filtered, *[dict(row) for row in new_warnings]]
        if rows:
            write_jsonl(warning_path, rows)
        elif warning_path.exists():
            warning_path.unlink()

    def retry_failed_batch_job(
        self,
        *,
        roi: RoiDefinition,
        episode: PilotEpisode,
        batch_idx: int,
        mutation_lock: Lock,
    ) -> tuple[str, bool]:
        """Retry one failed score batch and refresh that episode's derived outputs."""

        label = f"{roi.roi_id}/{episode.episode_id}/batch{batch_idx}"
        inputs = self.scoring_input(
            roi=roi,
            episode=episode,
            resume=True,
            overwrite=False,
        )
        cfg = self.score_config()
        output_dir = inputs.output_dir
        schema = load_region_schema(inputs.region_schema)
        segments = load_description_segments(inputs.descriptions)
        if inputs.summary_file is None:
            raise ValueError(f"{label}: scoring retry requires a summary file.")
        with inputs.summary_file.open("r", encoding="utf-8") as handle:
            summaries = json.load(handle)
        batch_start = batch_idx * cfg.scoring_batch_size
        if batch_start >= len(segments):
            raise ValueError(f"{label}: batch_start {batch_start} exceeds segment count.")
        retry_warnings: list[dict] = []
        rows = self.deps.score_description_segment_batch(
            batch_idx,
            batch_start,
            segments,
            schema,
            cfg,
            summaries,
            retry_warnings,
        )
        rows = _normalize_batch_score_metadata(
            batch_scores=rows,
            batch_start=batch_start,
            batch_idx=batch_idx,
            total_segments=len(segments),
            cfg=cfg,
        )
        with mutation_lock:
            self.replace_score_rows(
                output_dir=output_dir,
                replacement_rows=rows,
                batch_idx=batch_idx,
            )
            self.rewrite_warning_rows(
                output_dir=output_dir,
                retried_batch_idx=batch_idx,
                new_warnings=retry_warnings,
            )
            # Regenerate TR features, readable rows, metadata, and progress from
            # the updated complete score rows after each serialized mutation.
            score_descriptions_from_file(inputs, cfg, deps=self.deps)
        still_failed = any(
            row.get("reason") == "batch_generation_failed_zero_filled"
            and int(row.get("batch_idx", -1)) == batch_idx
            for row in retry_warnings
        )
        return label, not still_failed

    def retry_failed_batches(
        self,
        rois: Sequence[RoiDefinition],
        *,
        workers: int,
    ) -> None:
        """Retry only previously zero-filled failed scoring batches."""

        jobs: list[Job] = []
        retry_labels: list[str] = []
        mutation_locks: dict[Path, Lock] = {}
        for roi in rois:
            for episode in self.config.episodes:
                output_dir = self.artifacts.scoring_dir(roi.roi_id, episode)
                lock = mutation_locks.setdefault(output_dir, Lock())
                for batch_idx in self.failed_batch_indices(output_dir):
                    label = f"{roi.roi_id}/{episode.episode_id}/batch{batch_idx}"
                    retry_labels.append(label)
                    jobs.append(
                        (
                            label,
                            lambda roi=roi, episode=episode, batch_idx=batch_idx, lock=lock: (
                                self.retry_failed_batch_job(
                                    roi=roi,
                                    episode=episode,
                                    batch_idx=batch_idx,
                                    mutation_lock=lock,
                                )
                            ),
                        ),
                    )
        if not jobs:
            self.log("No failed scoring batches found.")
            return
        self.log("Retry failed batches: " + ", ".join(retry_labels))
        run_parallel(
            stage_name="retry-failed-batches",
            workers=workers,
            jobs=jobs,
            log=self.log,
        )
        self.log("Retry complete: refresh manifest and encoding")
        self.refresh_encoding(rois)
        self.validate_full_outputs(rois)

    def write_manifest(self, rois: Sequence[RoiDefinition]) -> Path:
        """Write unified ROI encoding inputs and return the manifest path."""

        manifest_path = self.artifacts.write_encoding_inputs(rois)
        self.log(f"Manifest stage complete: {manifest_path}")
        return manifest_path

    def run_encoding(self) -> None:
        """Run the joint ROI Ridge encoding stage."""

        fit_roi_encoding_from_manifest(
            Namespace(
                manifest=str(self.artifacts.manifest_path()),
                roi_schemas=str(self.artifacts.roi_schema_mapping_path()),
                atlas_labels=str(self.config.atlas_labels),
                output_dir=str(self.artifacts.encoding_dir()),
                lags=",".join(str(lag) for lag in self.config.lags),
                alphas=",".join(f"{alpha:g}" for alpha in self.config.alphas),
            ),
            RidgeEncodingConfig(
                lags=self.config.lags,
                alphas=self.config.alphas,
            ),
        )

    def refresh_encoding(self, rois: Sequence[RoiDefinition]) -> None:
        """Refresh encoding inputs, then rerun Ridge encoding."""

        self.write_manifest(rois)
        self.run_encoding()

    def validate_scoring_outputs(
        self,
        rois: Sequence[RoiDefinition],
        episodes: Sequence[PilotEpisode],
    ) -> None:
        validate_scoring_outputs(self.config, rois, episodes)

    def validate_full_outputs(self, rois: Sequence[RoiDefinition]) -> None:
        validate_full_outputs(self.config, rois)
