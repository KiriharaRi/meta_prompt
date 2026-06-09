# Test one more Mimo region schema rerun

## Goal

Run one more `mimo-v2.5-pro` region-schema generation test for a pilot ROI that
did not already have a `friends/demo/mimo_schema_staging/<ROI>/region_schema.json`
artifact. The run should validate that the schema path still works after the
region-schema prompt-rule cleanup, without overwriting formal multi-ROI pilot
schema files.

## What I Already Know

- Current pilot config is `configs/friends_multi_roi_pilot.json`.
- The pilot uses `generation_provider=packyapi` and
  `generation_model=mimo-v2.5-pro`.
- Configured ROIs are: `DLPFC`, `VMPFC`, `OFC`, `ACC`, `PCC`, `Precuneus`,
  `IPL`, `SMG`, `AG`, `TPJ`, `pSTS`, `FFA`, `Insula`, and `Temporal_Pole`.
- `friends/demo/mimo_schema_staging/` already contains schemas for 12 ROIs:
  all configured ROIs except `IPL` and `Temporal_Pole`.
- `friends/demo/mimo_domain_pool_staging/IPL/domain_pool_auto_confirmed.json`
  exists, has `target_region=IPL`, `curation_status=confirmed`, and
  `source_model=mimo-v2.5-pro`.
- Formal schemas under `friends/demo/multi_roi_pilot/rois/<ROI>/region_schema.json`
  already exist for all 14 configured ROIs, so this task should avoid touching
  formal output unless explicitly requested later.

## Assumptions

- Use `IPL` as the next test ROI because it has an auto-confirmed Mimo domain
  pool but no staging schema artifact yet.
- Write the test output to
  `friends/demo/mimo_schema_staging/IPL/region_schema.json`.
- Do not delete, overwrite, or regenerate scoring, summaries, encoding outputs,
  or formal `friends/demo/multi_roi_pilot/rois/<ROI>/region_schema.json` files.

## Requirements

- Run `make-region-schema` for `IPL` using PackyAPI and `mimo-v2.5-pro`.
- If Mimo fails to satisfy the current schema quality gate, try the same IPL
  domain pool with Gemini 3 Flash (`generation_provider=gemini`,
  `generation_model=gemini-3-flash-preview`) as a provider comparison.
- Use fixed ROI definitions so the output selection rules come from
  `configs/roi_definitions_brainnetome246_yeo.json`.
- Use the confirmed Mimo IPL domain pool from
  `friends/demo/mimo_domain_pool_staging/IPL/domain_pool_auto_confirmed.json`.
- Save output only under `friends/demo/mimo_schema_staging/IPL/`.
- Save Gemini comparison output only under
  `friends/demo/gemini3_flash_schema_staging/IPL/`.
- Validate the output with `load_region_schema` and basic contract checks:
  `version`, `target_region`, non-empty dimensions, 0-10 anchors, provider/model
  metadata, and domain-pool provenance.

## Acceptance Criteria

- [ ] `friends/demo/mimo_schema_staging/IPL/region_schema.json` exists.
- [ ] The schema loads through `brain_region_pipeline.region_schema.load_region_schema`.
- [ ] `target_region` is `IPL`.
- [ ] Metadata records `source_provider=packyapi` and `source_model=mimo-v2.5-pro`.
- [ ] Metadata references the IPL Mimo domain pool.
- [ ] Every dimension has score range 0 to 10 and complete `0` through `10`
      graded anchors.
- [ ] No formal multi-ROI pilot schema or scoring output is modified.
- [ ] Gemini comparison either writes a qualified IPL schema or records the
      exact failure point without changing formal outputs.

## Out of Scope

- Regenerating all ROI schemas.
- Copying the staging schema into the formal pilot ROI directory.
- Running scoring or encoding.
- Changing pipeline code or prompt contracts.

## Technical Notes

Planned command:

```bash
uv run python -m brain_region_pipeline make-region-schema \
  --atlas-labels atlas/subregion_func_network_Yeo_updated.csv \
  --target-region IPL \
  --domain-pool friends/demo/mimo_domain_pool_staging/IPL/domain_pool_auto_confirmed.json \
  --roi-definitions configs/roi_definitions_brainnetome246_yeo.json \
  --roi-id IPL \
  --provider packyapi \
  --model mimo-v2.5-pro \
  --output-file friends/demo/mimo_schema_staging/IPL/region_schema.json
```

## Run Log

### Attempt 1: IPL staging schema generation

- Command reached `Step 2/2: Build region feature schema`.
- Domain pool loaded successfully with 9 curated domains.
- PackyAPI returned text, but local JSON parsing failed before schema
  conversion.
- Error:
  `json.decoder.JSONDecodeError: Expecting ',' delimiter: line 611 column 7`.
- No `friends/demo/mimo_schema_staging/IPL/region_schema.json` file was written.

### Attempt 2: IPL staging schema generation

- Command again loaded the IPL Mimo domain pool successfully.
- PackyAPI returned parseable JSON, but generated schema failed
  `validate_region_schema_quality`.
- Error summary:
  - `effort_and_uncertainty_appraisal`: expected 3 to 8 dimensions, got 2.
  - `expectancy_violation_detection`: expected 3 to 8 dimensions, got 2.
  - `multisensory_scene_integration`: expected 3 to 8 dimensions, got 2.
  - `salience_integration_and_prioritization`: expected 3 to 8 dimensions, got 0.
- No `friends/demo/mimo_schema_staging/IPL/region_schema.json` file was written.

### Attempt 3: IPL Gemini 3 Flash comparison

- Planned model id from repo conventions:
  `gemini-3-flash-preview`.
- Output path:
  `friends/demo/gemini3_flash_schema_staging/IPL/region_schema.json`.

## Findings

- The IPL rerun did not fail at path/config/domain-pool loading; it failed at
  model output contract compliance.
- The current IPL Mimo domain pool has 9 confirmed domains, so the current
  quality gate requires at least 27 active non-emotion dimensions.
- The existing formal IPL schema has 24 dimensions across 5 active domain
  labels and does not appear aligned to the current 9-domain Mimo pool contract.
- A quick scan suggests multiple formal ROI schemas are stale relative to the
  current Mimo auto-confirmed domain pools, so "schema exists" is not equivalent
  to "schema satisfies current Mimo pool + current quality gate".
