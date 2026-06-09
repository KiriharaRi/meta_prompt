# Brain Region Pipeline vmPFC Review

## Current Flow

```text
make-domain-pool
  -> confirmed domain_pool_v2.json
make-region-schema --domain-pool confirmed_domain_pool.json
  -> region_schema_v1.json
score-descriptions --region-schema region_schema.json
  -> segment_region_scores.jsonl
  -> tr_features.jsonl
fit-roi-encoding --manifest roi_encoding_manifest.jsonl
  -> parcel_metrics.jsonl / roi_summaries.json / group_summary.json
```

The maintained conceptual stack is:

```text
domain_pool = coarse functional domains
region_schema = executable dimensions and scoring rules
score outputs = numeric dimension scores and TR-aligned feature vectors
encoding outputs = parcel-wise Ridge predictions for schema-selected H5 fMRI columns
```

## Domain Pool

`domain_pool_v2` is an auditable coarse-domain artifact.

Key rules:

- It includes required seed candidate `required_emotion_experience` with
  `source_run = 0`.
- Curated domains must include `emotion_experience`.
- Curated `emotion_experience` must preserve `required_emotion_experience` in
  `source_domain_ids` and `0` in `source_runs`.
- `source_run = 0` is counted in `proposal_frequency` for a simple contract.
- It does not contain active dimensions.
- It does not contain atlas `selection_rules`.
- It must be manually confirmed before `make-region-schema` can use it.

## Region Schema

`region_schema_v1` is the executable feature schema for one target region.

Top-level fields:

- `target_region`
- `functional_hypothesis`
- `scoring_instruction`
- `selection_rules`
- `domains`
- `active_domain_ids`
- `dimensions`
- `metadata`

`domains` stores the full confirmed domain-pool snapshot. `active_domain_ids`
lists domains that actually have active dimensions, ordered by the original
domain order.

## Emotion Panel

The required `emotion_experience` domain contains discrete typical-viewer
emotion dimensions.

Core dimensions:

```text
emotion_admiration
emotion_amusement
emotion_joy
emotion_tenderness
emotion_confusion
emotion_surprise
emotion_agitation
emotion_sadness
```

All `emotion_experience` dimensions must use `emotion_<label>`, where the label
comes from the 20-label English set. The domain must contain 8 to 12 emotion
dimensions. `emotion_agitation` is the feature used for Fallen GT agitation
validation, but `region_schema` does not store Fallen-specific metadata.

## Scoring Output

Segment scores are flat:

```json
{
  "start_s": 0.0,
  "end_s": 5.0,
  "description": "...",
  "dimension_scores": {
    "emotion_agitation": 6.0
  },
  "rationale": ""
}
```

TR rows contain `feature_vector` plus a `source_description` for inspection.
`scoring_metadata.json` stores `feature_names` and `feature_metadata`, so matrix
columns can always be mapped back to `dimension_id` and `domain`.

## Ridge Encoding Output

`fit-roi-encoding` consumes explicit JSONL manifest rows that bind
`roi_features` to an H5 `TR x parcel` dataset. A single ROI is represented as a
one-entry `roi_features` mapping; multiple ROIs use the same command with more
keys. The command uses ROI schema `selection_rules` and `--atlas-labels` to
choose the union of parcel columns, then fits subject-level multi-output Ridge
models with lag-expanded score features.

Encoding is intentionally strict:

- no automatic feature/H5 filename matching;
- no silent feature/fMRI length truncation;
- no sklearn model pickle;
- one global alpha per subject selected on the manifest `val` split;
- primary test metric is mean Pearson across retained selected parcels.

## Review Risks

- `emotion_experience` is a required anchor domain, not pure discovery output.
  This should be treated as a pre-registered validation-oriented constraint.
- Larger active-dimension schemas increase scoring cost and may increase feature
  collinearity; pilot checks should inspect sparsity, variance, and
  correlations.
- Feature order is controlled by code after schema generation.
- Previous JSON contracts are intentionally not compatible with the current
  contract.

## Key Files

```text
brain_region_pipeline/core/contracts.py
brain_region_pipeline/schema_design/domain_models.py
brain_region_pipeline/schema_design/schema_models.py
brain_region_pipeline/schema_design/domain_pool.py
brain_region_pipeline/schema_design/region_schema.py
brain_region_pipeline/scoring/region_schema_scorer.py
brain_region_pipeline/scoring/score_aligner.py
brain_region_pipeline/encoding/manifest.py
brain_region_pipeline/encoding/fmri.py
brain_region_pipeline/encoding/features.py
brain_region_pipeline/encoding/ridge.py
brain_region_pipeline/encoding/runner.py
brain_region_pipeline/cli.py
```
