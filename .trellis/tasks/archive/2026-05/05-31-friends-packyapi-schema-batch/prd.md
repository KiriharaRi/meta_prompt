# Run Friends PackyAPI Schema Batch

## Goal

Run the Friends Brainnetome multi-ROI schema generation in a small parallel
batch using PackyAPI. This task only runs the first 3-ROI batch so runtime,
provider behavior, and output validity can be checked before launching all
remaining ROIs.

## What I Already Know

* User confirmed reusing existing `aihubmix`-generated
  `domain_pool_auto_confirmed.json` files.
* User asked to start a parallel batch.
* A full DLPFC streaming diagnostic completed successfully in 444.35 seconds.
* DLPFC streaming output produced valid JSON and passed region-schema quality
  validation with 30 dimensions.
* Current repo config uses PackyAPI with `deepseek-v4-pro`.

## Requirements

* Use UV for Python execution.
* Do not modify source code.
* Run three independent `make-region-schema` commands in parallel:
  `DLPFC`, `VMPFC`, and `OFC`.
* Use the existing output root:
  `friends/demo/multi_roi_pilot`.
* Reuse each ROI's `domain_pool_auto_confirmed.json`.
* Use fixed ROI selection rules from
  `configs/roi_definitions_brainnetome246_yeo.json`.
* Stop after this first batch and report timing/status before launching the
  next batch.

## Acceptance Criteria

* [ ] `friends/demo/multi_roi_pilot/rois/DLPFC/region_schema.json` exists.
* [ ] `friends/demo/multi_roi_pilot/rois/VMPFC/region_schema.json` exists.
* [ ] `friends/demo/multi_roi_pilot/rois/OFC/region_schema.json` exists.
* [ ] The generated schema files can be loaded through `load_region_schema`.
* [ ] Final report includes per-ROI completion or failure status.

## Out of Scope

* Running all 14 ROIs in one batch.
* Running scoring, manifest, or encoding stages.
* Changing schema prompts, provider code, or pipeline source.
* Interpreting generated dimensions scientifically.

## Technical Notes

* Per-ROI command:
  `uv run python -m brain_region_pipeline make-region-schema ...`
* Use `--provider packyapi --model deepseek-v4-pro`.
