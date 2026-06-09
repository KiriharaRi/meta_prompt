# Fix Schema Dimensions Under Domains

## Goal

Prevent region-schema generation from collapsing confirmed coarse domains into
one score per domain. A generated `dimension` must be a concrete, text-scoreable
sub-variable under a confirmed `domain`, not the domain itself.

## What I Already Know

* The user wants domain pools reused as coarse explanatory categories.
* The user does not want active dimensions to be a 1:1 mapping from domains.
* The ACC diagnostic generated 5 dimensions for 5 domains, with each
  `dimension_id` equal to its `domain`, which is the exact failure pattern.
* The old 24-36 total-dimension count guidance has already been removed and
  must not be reintroduced.
* Existing schema generation code lives in `brain_region_pipeline/region_schema.py`.

## Requirements

* Prompt requirements must explicitly state that domains are coarse categories,
  not score columns.
* Prompt requirements must ask the model to infer concrete scoring dimensions
  under each retained domain.
* Validation must reject obvious domain-as-dimension collapses, including a
  dimension whose `dimension_id` equals its `domain`.
* Validation must reject a dimension whose `dimension_id` equals any confirmed
  `domain_id`.
* Non-`emotion_experience` domains should each generate 3 to 8 active
  dimensions so schema granularity stays aligned with vmPFC-style scoring.
* `emotion_experience` keeps its separate vmPFC emotion-panel contract rather
  than being forced into the non-emotion 4-8 range.
* The `emotion_*` prefix must imply `emotion_experience` only for vmPFC's
  required emotion panel; non-vmPFC ROIs may place emotion-related dimensions
  under the most specific confirmed domain.
* Tests must cover prompt wording and local validation behavior.
* Do not restore any fixed total-dimension count limit.
* Do not change provider, retry, timeout, ROI selection, or domain-pool logic.

## Acceptance Criteria

* [ ] Prompt tests confirm domain/dimension hierarchy guidance is present.
* [ ] Unit tests confirm a domain-as-dimension schema is rejected.
* [ ] Unit tests confirm non-emotion domains outside the 3-8 dimension range
      are rejected.
* [ ] Unit tests confirm a valid per-domain dimension count is still accepted.
* [ ] Existing brain-region workflow tests pass under `uv`.
* [ ] Maintained specs document the new quality contract.
* [ ] ACC schema can be regenerated after the fix without the 1:1 collapse.

## Definition of Done

* Tests added or updated for the new schema contract.
* `uv run python -m unittest tests.test_brain_region_description_workflow`
  passes.
* `uv run python -m unittest discover -s tests -p 'test_*.py'` passes.
* `uv run python -m compileall brain_region_pipeline tests` passes.
* No unrelated source refactor or generated-output cleanup is included.

## Out of Scope

* Scientifically reviewing the generated dimensions.
* Changing domain-pool generation or consolidation.
* Running scoring, manifest, or encoding stages.
* Reintroducing fixed dimension-count guidance.

## Technical Notes

* Relevant code: `brain_region_pipeline/region_schema.py`.
* Relevant tests: `tests/test_brain_region_description_workflow.py`.
* Relevant spec: `.trellis/spec/backend/quality-guidelines.md`.
* Current invalid diagnostic artifact:
  `friends/demo/multi_roi_pilot/rois/ACC/region_schema.json`.
