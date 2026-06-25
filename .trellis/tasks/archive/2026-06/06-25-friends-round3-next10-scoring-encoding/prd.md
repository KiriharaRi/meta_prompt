# Friends round3 next10 scoring and encoding

## Goal

Extend the current Friends 14-ROI full run from the confirmed 55-train round2
encoding setup to a 65-train round3 setup by adding 10 more valid training
episode segments, running real 14-ROI scoring with scoring concurrency 6, then
refreshing manifest and encoding outputs.

## Background

- Baseline config:
  `configs/friends_train_size_sweep_20260624_round2/round2_scoring_encoding.json`.
- Baseline output root:
  `friends/full_runs/friends_full_scoring_start_14roi_gemini35_20260612`.
- Current confirmed baseline split count is `55 train / 5 val / 4 test`.
- Current confirmed baseline encoding metric is
  `mean_subject_mean_test_pearson = 0.20813553012023459`.
- Validation split must stay unchanged:
  `s02e01a`, `s02e02a`, `s02e03a`, `s02e04a`, `s02e05a`.
- Held-out test split must stay unchanged:
  `s06e01a`, `s06e01b`, `s06e03a`, `s06e03b`.
- "Satisfy TR and H5 requirements" means every added episode has:
  refined descriptions, one matching dataset in
  `friends/BN/sub-01/BN_246.h5`, existing summary output, and
  description-derived feature TR coverage that reaches the default trimmed
  fMRI interval required by encoding.

## Selected Episodes

Use these 10 new train episode segments:

| episode | h5_dataset | description segments | feature_trs | h5_trs | h5-feature gap |
| --- | --- | ---: | ---: | ---: | ---: |
| `s02e15b` | `ses-015_task-s02e15b` | 281 | 466 | 466 | 0 |
| `s02e16a` | `ses-016_task-s02e16a` | 282 | 478 | 478 | 0 |
| `s02e16b` | `ses-016_task-s02e16b` | 291 | 478 | 478 | 0 |
| `s02e17a` | `ses-016_task-s02e17a` | 264 | 489 | 489 | 0 |
| `s02e17b` | `ses-016_task-s02e17b` | 282 | 489 | 489 | 0 |
| `s02e18a` | `ses-017_task-s02e18a` | 271 | 460 | 460 | 0 |
| `s02e18b` | `ses-017_task-s02e18b` | 269 | 460 | 460 | 0 |
| `s02e19a` | `ses-017_task-s02e19a` | 271 | 478 | 478 | 0 |
| `s02e19b` | `ses-017_task-s02e19b` | 265 | 478 | 478 | 0 |
| `s02e20a` | `ses-017_task-s02e20a` | 263 | 449 | 449 | 0 |

The earlier valid candidates `s02e01b` through `s02e05b` are intentionally not
selected because their paired `a` halves are validation episodes.

## Requirements

- Create a round3 config under
  `configs/friends_train_size_sweep_20260625_round3/` by extending the round2
  config with the 10 selected train episodes.
- Keep generation provider/model, scoring batch size, local buffer size, TR
  duration, lags, alphas, ROI definitions, atlas labels, H5 file, and output
  root consistent with round2 unless a validation check proves a change is
  required.
- Run scoring through the existing config-driven concurrent 14-ROI runner with
  `--scoring-workers 6`.
- During early scoring, poll frequently to verify jobs are making progress and
  no failure pattern appears; after stable progress is established, reduce the
  polling frequency.
- Verify all 140 new ROI/episode scoring outputs are complete before running
  encoding.
- Refresh manifest and run encoding only after scoring validation passes.
- Report the final encoding metrics and compare the primary metric against the
  55-train baseline.

## Acceptance Criteria

- [x] Round3 config validates with dry-run and contains `65 train / 5 val / 4 test`.
- [x] The 10 added train episodes all have existing summary files and pass
      description/H5/TR coverage preflight.
- [x] Scoring is launched with `--scoring-workers 6`.
- [x] Early scoring progress is checked by polling runner output and per-job
      progress or metadata files; polling frequency is lowered only after
      stable progress is observed.
- [x] All 140 new scoring outputs contain `segment_region_scores.jsonl`,
      `tr_features.jsonl`, and `scoring_metadata.json`.
- [x] New scoring metadata has no failed zero-filled batches. If warnings
      occur, they are reported and resolved before encoding.
- [x] The refreshed encoding manifest contains every round3 sample with all 14
      ROI feature files.
- [x] Encoding completes and reports `mean_subject_mean_test_pearson`,
      `mean_subject_median_test_pearson`, selected alpha, retained parcel count,
      test TR count, and any warning/failure summary.
- [x] The final response identifies all written output locations and any
      remaining risk.

## Result

- Round3 scoring completed for all 140 new ROI/episode jobs.
- A first scoring pass hit provider/network failures that produced zero-filled
  batches; `--retry-failed-batches --scoring-workers 6` reran the failed
  batches and cleared all scoring warnings.
- Independent validation after retry: `complete=140`, `partial=0`,
  `missing=0`, `warning_jobs=0`, `zero_filled=0`.
- Encoding manifest rows: `74`.
- Encoding metric: `mean_subject_mean_test_pearson = 0.21207336267220675`.
- Other encoding summary: `mean_subject_median_test_pearson =
  0.2048392383408515`, `best_alpha = 10000.0`, `n_retained_parcels = 86`,
  `n_test_trs = 1812`.

## Out of Scope

- Changing validation or held-out test split policy.
- Generating new ROI schemas or domain pools.
- Changing provider/model or scoring prompt behavior.
- Broad code refactors or pipeline behavior changes.

## Decision

- Preserve the current 55-train `encoding/` directory as a snapshot before
  refreshing round3 encoding, so the confirmed 55-train result remains directly
  inspectable after the 65-train run.
