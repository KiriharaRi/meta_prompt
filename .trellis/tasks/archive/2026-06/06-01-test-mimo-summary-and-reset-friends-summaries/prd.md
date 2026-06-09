# test-mimo-summary-and-reset-friends-summaries

## Goal

Validate that the existing `summarize-descriptions` CLI can generate a
requirements-compatible Friends summary file with `packyapi` and
`mimo-v2.5-pro`. If the single-episode smoke test passes, remove only the
existing formal summary outputs under `friends/demo/multi_roi_pilot/summaries/`
so the next run can regenerate summaries cleanly.

Continue the pipeline by validating `mimo-v2.5-pro` domain-pool generation on a
single ROI before regenerating formal domain pools for every configured pilot
ROI.

Continue one more stage by validating region-schema generation on one ROI before
regenerating formal `region_schema.json` files for all configured pilot ROIs.

## What I Already Know

- The CLI entrypoint is `uv run python -m brain_region_pipeline summarize-descriptions`.
- The current project default model is `mimo-v2.5-pro`, and the pilot config also
  uses `generation_provider=packyapi` plus `generation_model=mimo-v2.5-pro`.
- Summary output contract is a JSON array plus `summary_metadata.json`.
- Each summary row must include `batch_idx`, `segment_start`, `segment_end`,
  `timestamp_range`, `batch_summary`, and `cumulative_summary`.
- The summary batch size is fixed at 40 segments in the current CLI config.

## Requirements

- Run a single-episode summary smoke test without overwriting the formal pilot
  `summaries/` directory.
- Use `packyapi` with `mimo-v2.5-pro`.
- Validate the generated summary JSON and metadata before deleting anything.
- If validation passes, delete only `friends/demo/multi_roi_pilot/summaries/`.
- After the smoke test passes, migrate the validated smoke summary into the
  formal pilot summary directory.
- Generate matching summary outputs for the remaining pilot episodes.
- Run a single-ROI domain-pool smoke test outside the formal ROI output
  directories.
- If the smoke domain pool validates, regenerate formal `domain_pool_draft.json`
  and `domain_pool_auto_confirmed.json` for all pilot ROIs.
- Run a single-ROI schema smoke test outside the formal ROI output directories.
- If the smoke schema validates, regenerate formal `region_schema.json` for all
  pilot ROIs from the new auto-confirmed domain pools.
- Do not delete scoring, schema, encoding, repair-log, or unrelated demo outputs.

## Acceptance Criteria

- [x] The smoke output `summary.json` exists and is a JSON array.
- [x] Every row has the required summary fields.
- [x] `batch_summary` and `cumulative_summary` are non-empty strings.
- [x] `summary_metadata.json` exists and records `provider=packyapi` and
      `model=mimo-v2.5-pro`.
- [x] `n_batches` matches the number of summary rows.
- [x] If all checks pass, `friends/demo/multi_roi_pilot/summaries/` is removed.
- [x] Formal summaries exist for all configured pilot episodes:
      `s01e01a`, `s01e02a`, `s01e03a`, `s01e05a`, and `s01e06a`.
- [x] Every formal summary records `provider=packyapi` and
      `model=mimo-v2.5-pro` in `summary_metadata.json`.
- [x] The VMPFC domain-pool smoke output validates through the existing
      `load_domain_pool` contract and preserves required vmPFC domain anchors.
- [x] Every configured pilot ROI has regenerated `domain_pool_draft.json` and
      `domain_pool_auto_confirmed.json`.
- [x] Every regenerated auto-confirmed pool has `curation_status=confirmed`,
      `source_model=mimo-v2.5-pro`, and metadata
      `confirmation_mode=auto_pilot`.
- [ ] The VMPFC schema smoke output validates through `load_region_schema` and
      includes concrete dimensions under confirmed domains.
- [ ] Every configured pilot ROI has a regenerated `region_schema.json`.
- [ ] Every regenerated schema has `target_region` matching its ROI,
      dimensions with 0-10 anchors, and metadata that references the regenerated
      domain pool.

## Out of Scope

- Regenerating all official Friends summaries.
- Running scoring, schema generation, or encoding.
- Changing pipeline code or prompt contracts.
- Deleting any directories outside `friends/demo/multi_roi_pilot/summaries/`.

## Technical Notes

- Smoke output path:
  `friends/demo/mimo_summary_smoke/s01e01a/summary.json`
- Test episode:
  `friends/description/downloaded_refine_descriptions/mv_friends_s01e01a/descriptions/refined_description.md`
- Formal output root:
  `friends/demo/multi_roi_pilot/summaries/`
- Domain-pool smoke output root:
  `friends/demo/mimo_domain_pool_smoke/VMPFC/`
- Formal ROI domain-pool root:
  `friends/demo/multi_roi_pilot/rois/<ROI>/`
- Schema smoke output root:
  `friends/demo/mimo_schema_smoke/VMPFC/`
- Schema staging root:
  `friends/demo/mimo_schema_staging/<ROI>/`
