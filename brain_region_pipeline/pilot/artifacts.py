"""Artifact graph for the Friends multi-ROI pilot workflow."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

from ..core.io_utils import write_json, write_jsonl

if TYPE_CHECKING:
    from ..atlas.roi_config import RoiDefinition
    from .runner import PilotConfig, PilotEpisode


@dataclass(frozen=True)
class PilotArtifacts:
    """Resolve and write artifacts derived from a single pilot config."""

    config: PilotConfig

    def summary_path(self, episode: PilotEpisode) -> Path:
        return (
            self.config.output_root
            / "summaries"
            / episode.episode_id
            / "summary.json"
        )

    def roi_dir(self, roi_id: str) -> Path:
        return self.config.output_root / "rois" / roi_id

    def domain_pool_draft_path(self, roi_id: str) -> Path:
        return self.roi_dir(roi_id) / "domain_pool_draft.json"

    def domain_pool_auto_confirmed_path(self, roi_id: str) -> Path:
        return self.roi_dir(roi_id) / "domain_pool_auto_confirmed.json"

    def domain_pool_confirmed_path(self, roi_id: str) -> Path:
        return self.roi_dir(roi_id) / "domain_pool_confirmed.json"

    def domain_pool_for_schema(self, roi_id: str) -> Path:
        """Return the confirmed pool path preferred by schema generation."""

        auto_confirmed = self.domain_pool_auto_confirmed_path(roi_id)
        if auto_confirmed.exists():
            return auto_confirmed
        confirmed = self.domain_pool_confirmed_path(roi_id)
        if confirmed.exists():
            return confirmed
        raise ValueError(
            f"ROI {roi_id!r} has no confirmed domain pool. Expected "
            f"{auto_confirmed} or {confirmed}.",
        )

    def region_schema_path(self, roi_id: str) -> Path:
        return self.roi_dir(roi_id) / "region_schema.json"

    def scoring_dir(self, roi_id: str, episode: PilotEpisode) -> Path:
        return self.roi_dir(roi_id) / "scores" / episode.episode_id

    def encoding_dir(self) -> Path:
        return self.config.output_root / "encoding"

    def manifest_path(self) -> Path:
        return self.encoding_dir() / "roi_encoding_manifest.jsonl"

    def roi_schema_mapping_path(self) -> Path:
        return self.encoding_dir() / "roi_schemas.json"

    @staticmethod
    def relative_to(path: Path, base_dir: Path) -> str:
        """Return artifact references relative to the file that stores them."""

        return os.path.relpath(path, base_dir)

    def encoding_manifest_rows(
        self,
        rois: Sequence[RoiDefinition],
    ) -> list[dict[str, Any]]:
        """Build manifest rows after verifying every ROI/episode feature file exists."""

        encoding_dir = self.encoding_dir()
        rows: list[dict[str, Any]] = []
        for episode in self.config.episodes:
            roi_features: dict[str, str] = {}
            for roi in rois:
                feature_path = (
                    self.scoring_dir(roi.roi_id, episode) / "tr_features.jsonl"
                )
                if not feature_path.exists():
                    raise ValueError(
                        f"Cannot write manifest: missing TR features for {roi.roi_id} "
                        f"/ {episode.episode_id}: {feature_path}",
                    )
                roi_features[roi.roi_id] = self.relative_to(
                    feature_path,
                    encoding_dir,
                )
            rows.append(
                {
                    "sample_id": f"{self.config.subject_id}_{episode.episode_id}",
                    "subject_id": self.config.subject_id,
                    "feature_set_name": "roi_scores",
                    "split": episode.split,
                    "roi_features": roi_features,
                    "h5_file": self.relative_to(self.config.h5_file, encoding_dir),
                    "h5_dataset": episode.h5_dataset,
                    "feature_trim_start_tr": 0,
                    "feature_trim_end_tr": 0,
                    "fmri_trim_start_tr": self.config.encoding_trim.fmri_trim_start_tr,
                    "fmri_trim_end_tr": self.config.encoding_trim.fmri_trim_end_tr,
                },
            )
        return rows

    def roi_schema_mapping_payload(
        self,
        rois: Sequence[RoiDefinition],
    ) -> dict[str, dict[str, str]]:
        """Build the ROI-to-schema mapping consumed by joint encoding."""

        encoding_dir = self.encoding_dir()
        return {
            "roi_schemas": {
                roi.roi_id: self.relative_to(
                    self.region_schema_path(roi.roi_id),
                    encoding_dir,
                )
                for roi in rois
            },
        }

    def write_encoding_inputs(self, rois: Sequence[RoiDefinition]) -> Path:
        """Write the manifest and schema mapping required by the encoding stage."""

        manifest_path = self.manifest_path()
        write_jsonl(manifest_path, self.encoding_manifest_rows(rois))
        write_json(
            self.roi_schema_mapping_path(),
            self.roi_schema_mapping_payload(rois),
        )
        return manifest_path
