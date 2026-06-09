# Remove Region Schema Dimension Count Limit

## Goal

Remove the hard total active-dimension count gate from region-schema validation
so PackyAPI-generated schemas are not rejected only because the total number of
dimensions falls outside the previous 24-36 range.

## What I Already Know

* User asked to cancel the original project dimension limit.
* The relevant check lives in `brain_region_pipeline/region_schema.py`.
* The current validation rejects schemas when total active dimensions are not
  between `MIN_REGION_DIMENSIONS` and `MAX_REGION_DIMENSIONS`.
* A recent OFC diagnostic showed provider calls can succeed but be rejected
  locally. The diagnostic relaxed the total dimension-count gate and saved a
  valid OFC schema.
* The user wants this behavior in the maintained project, not only in a one-off
  diagnostic script.

## Requirements

* Remove the hard rejection based only on total active dimension count.
* Preserve all other schema-quality checks:
  * schema domains must snapshot confirmed domain-pool domains;
  * every dimension must use a confirmed domain;
  * score range must remain 0 to 10;
  * scoreability/exclusion notes remain required;
  * trigger list, graded anchors, and calibration examples remain required;
  * emotion-domain naming and allowed-label checks remain enforced;
  * vmPFC required emotion panel checks remain enforced.
* Keep the schema prompt guidance that suggests a target count unless the user
  explicitly asks to remove prompt guidance too.
* Update tests that currently expect the total dimension-count rejection.
* Use UV for test execution.

## Proposed Design

Keep `MIN_REGION_DIMENSIONS` / `MAX_REGION_DIMENSIONS` as prompt guidance if
needed, but stop using them as a hard error in
`validate_region_schema_quality()`. This preserves the scientific/contract
checks that protect downstream scoring while allowing the model to produce
fewer or more active feature columns when a region's domain pool naturally
leads there.

## Files Expected To Change

* `brain_region_pipeline/region_schema.py`
  * Remove or neutralize the total-dimension hard error block.
  * Optionally add a short comment that total count is prompt guidance rather
    than a validation gate.
* `tests/test_brain_region_description_workflow.py`
  * Update tests that assume the 24-36 hard limit.
  * Add/adjust a test proving a schema outside the previous total count range
    can pass when all field-level requirements are valid.

## Acceptance Criteria

* [ ] Region schemas are no longer rejected solely for total dimension count
      outside 24-36.
* [ ] Other validation failures still raise clear errors.
* [ ] Relevant unit tests pass with `uv run python -m unittest ...`.

## Out of Scope

* Changing the PackyAPI streaming/non-streaming implementation.
* Changing the per-dimension required fields.
* Removing vmPFC emotion panel constraints.
* Rerunning all Friends schemas.
* Changing scoring, manifest, or encoding.
