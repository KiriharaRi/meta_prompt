# Run Friends PackyAPI Schemas

## Goal

Continue the Friends Brainnetome multi-ROI pipeline at the active-dimension
schema generation stage. Reuse the existing auto-confirmed domain pools, even
though they were generated before the PackyAPI migration, and generate PackyAPI
`region_schema_v1` artifacts for all configured ROIs.

## What I Already Know

* User confirmed: reuse existing `aihubmix`-generated
  `domain_pool_auto_confirmed.json` files.
* User confirmed: run the schemas stage directly with PackyAPI.
* Current config is `configs/friends_multi_roi_pilot.json`.
* Current config uses `generation_provider = "packyapi"` and
  `generation_model = "deepseek-v4-pro"`.
* Dry-run validation succeeds for 14 Brainnetome-derived ROIs and 5 Friends
  episodes.
* Existing outputs include shared summaries and per-ROI auto-confirmed domain
  pools under `friends/demo/multi_roi_pilot`.
* No `region_schema.json` files are present yet under the ROI output dirs.

## Assumptions

* It is acceptable for provenance to be mixed: domain-pool artifacts were
  generated with the previous OpenAI-compatible provider, while schemas will be
  generated with PackyAPI.
* This task should not modify business source code.
* This task should not rerun summaries or domain-pools.

## Requirements

* Use UV for Python execution.
* Run:
  `uv run python -m brain_region_pipeline run-multi-roi-pilot --config configs/friends_multi_roi_pilot.json --stage schemas`
* Reuse existing `friends/demo/multi_roi_pilot/rois/<ROI>/domain_pool_auto_confirmed.json`.
* Do not use `--stage all`.
* Do not use `--overwrite` semantics or delete existing run artifacts.
* Stop and report the exact failure point if PackyAPI, schema validation, or
  output writing fails.

## Acceptance Criteria

* [ ] 14 ROI `region_schema.json` files exist under
      `friends/demo/multi_roi_pilot/rois/<ROI>/`.
* [ ] Each schema reports `version = region_schema_v1`.
* [ ] Each schema metadata/source provider reflects the current PackyAPI schema
      generation run.
* [ ] Final report names generated schema count and any failed ROI.

## Definition of Done

* Command execution status is reported.
* Output files are checked after the run.
* No source-code changes are made.
* If the run fails, the resume command and failure context are reported.

## Out of Scope

* Rerunning summaries.
* Rerunning domain-pools.
* Running scoring, manifest, or encoding stages.
* Changing provider code, prompt contracts, ROI definitions, or atlas labels.
* Scientifically interpreting the generated dimensions beyond a basic sanity
  count.

## Technical Notes

* Schema stage implementation:
  `brain_region_pipeline/pilot_runner.py::_run_schemas`.
* Output root from config:
  `friends/demo/multi_roi_pilot`.
* Existing dry-run command already validated:
  `uv run python -m brain_region_pipeline run-multi-roi-pilot --config configs/friends_multi_roi_pilot.json --stage schemas --dry-run`.
