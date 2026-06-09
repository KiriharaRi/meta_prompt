# Rerun OFC Schema Diagnostic

## Goal

Rerun the OFC region-schema generation as a one-off diagnostic using PackyAPI,
with no provider retry loop and with the total active-dimension count check
disabled, so successful provider responses are either saved or rejected with a
visible local reason.

## Requirements

* Do not modify source code.
* Use UV for Python execution.
* Run only OFC.
* Use streaming PackyAPI request collection so provider progress is observable.
* Do not retry failed generation calls.
* Disable only the `MIN_REGION_DIMENSIONS` / `MAX_REGION_DIMENSIONS` count
  restriction for this diagnostic run.
* Preserve other JSON parsing, schema conversion, field-level validation, fixed
  ROI selection rule application, and atlas selection-rule validation.
* Save to `friends/demo/multi_roi_pilot/rois/OFC/region_schema.json` only if
  the relaxed validation succeeds.
* Print explicit parse/validation/save errors if the provider returns output
  that cannot be accepted locally.

## Acceptance Criteria

* [ ] OFC diagnostic command completes or prints an explicit local rejection
      reason.
* [ ] If accepted, `friends/demo/multi_roi_pilot/rois/OFC/region_schema.json`
      exists and can be loaded.
* [ ] Final report includes elapsed time, dimension count, and save/rejection
      status.

## Out of Scope

* Changing maintained source files.
* Rerunning all ROIs.
* Running scoring, manifest, or encoding.
