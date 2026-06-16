# Encoding Raw TR Alignment

## Goal

Make the meta_prompt encoding stage align scored description features to fMRI targets using the original raw TR axis, matching the intended notebook-style fMRI-driven training boundary while keeping scoring unchanged. The immediate need is to handle Friends episodes whose scored feature length differs by episode from the h5 fMRI TR count.

## Requirements

* Do not change the `score-descriptions` stage. It should continue scoring all description content and writing `tr_features.jsonl` based on the description-derived TR range.
* Store unified encoding trim settings in pilot config via an `encoding_trim` object.
* Pilot manifest generation should write explicit trim fields for every sample row:
  * `feature_trim_start_tr = 0`
  * `feature_trim_end_tr = 0`
  * `fmri_trim_start_tr = 5`
  * `fmri_trim_end_tr = 5`
* Encoding should align features and fMRI on raw TR indices after fMRI trim:
  * `required_start = fmri_trim_start_tr`
  * `required_end = h5_trs - fmri_trim_end_tr`
  * `x_aligned = feature[required_start:required_end]`
  * `y_aligned = fmri[required_start:required_end]`
* If feature rows cover fewer than `required_end` raw TRs, encoding must fail the whole run.
* If feature rows are longer than `required_end`, encoding may truncate extra feature rows.
* Encoding must validate `tr_features.jsonl` raw TR provenance:
  * `tr_index` starts at 0
  * `tr_index` is continuous
  * `tr_index` equals the feature row position
* Error messages for short feature files must include:
  * sample id
  * feature coverage range
  * required trimmed fMRI raw TR range
  * suggested minimum `fmri_trim_end_tr`

## Acceptance Criteria

* [x] `run-multi-roi-pilot --stage manifest` writes trim fields from `encoding_trim` into each manifest row.
* [x] Encoding slices feature and fMRI matrices by the same raw TR range derived from fMRI trim.
* [x] Feature files longer than the required raw TR range are accepted and truncated.
* [x] Feature files shorter than the required raw TR range fail before model fitting with an actionable error.
* [x] Non-contiguous or mismatched `tr_index` metadata fails before model fitting.
* [x] Existing encoding behavior still works for equal-length synthetic fixtures.
* [x] Relevant unit tests pass under `uv run python -m unittest`.

## Definition of Done

* Tests added or updated for manifest trim writing, raw TR alignment, feature truncation, feature-short failure, and TR provenance validation.
* Existing public CLI behavior remains backward-compatible for direct `fit-roi-encoding` users with explicit manifests.
* Lint/type checks or the project test suite are run with `uv`.
* No scoring-stage behavior changes.

## Technical Approach

Add a focused encoding-layer alignment helper that consumes raw feature and fMRI matrices plus manifest trim metadata, validates TR coverage, slices both matrices on the raw fMRI TR interval, and then delegates lag expansion to the existing `build_lagged_sample` function.

Pilot config should parse an optional `encoding_trim` object with a default of `{fmri_trim_start_tr: 5, fmri_trim_end_tr: 5}` for the pilot workflow, then persist those values into the generated manifest. Encoding itself should not hard-code trim defaults; it should execute what the manifest says.

## Decision (ADR-lite)

**Context**: Scored description features can be shorter or longer than h5 fMRI datasets depending on episode-specific description coverage. The notebook is fMRI-driven and removes fMRI boundary TRs for training, but it also has fallback behavior for short stimulus features. The desired meta_prompt behavior is stricter: no feature repetition, no scoring-stage changes.

**Decision**: Keep scoring unchanged. Move all alignment to encoding. Use raw TR indices as the alignment contract. Apply uniform fMRI trim5 via manifest rows generated from pilot config. Fail on insufficient feature coverage, allow truncation when features are longer.

**Consequences**: The behavior is explicit and preserves sample provenance. Some short-description episodes will fail encoding until descriptions/features are fixed or removed. This is intentional to avoid silently training on repeated or fabricated feature rows.

## Out of Scope

* Changing LLM scoring prompts or batching behavior.
* Regenerating missing or short description files.
* Automatically increasing `fmri_trim_end_tr` per episode.
* Skipping invalid episodes during encoding.
* Notebook parity for last-feature repetition fallback.

## Technical Notes

* Relevant files:
  * `brain_region_pipeline/scoring/runner.py`
  * `brain_region_pipeline/scoring/score_aligner.py`
  * `brain_region_pipeline/encoding/features.py`
  * `brain_region_pipeline/encoding/runner.py`
  * `brain_region_pipeline/encoding/manifest.py`
  * `brain_region_pipeline/pilot/runner.py`
  * `tests/test_brain_region_encoding.py`
  * `tests/test_brain_region_multi_roi.py`
* Existing `score-descriptions --total-trs` remains untouched.
* Existing `build_lagged_sample` already drops the first `max(lags)` target rows after alignment.
