# Implement: Friends round7 next20 summary scoring encoding

## Checklist

1. Reconfirm the current baseline config and fixed split:
   `round6_all_scored_95train_encoding.json`.
2. Build a deterministic preflight audit for all candidate episodes.
3. Select exactly 20 eligible new train episodes.
4. Write:
   - `preflight_round7_next20.json`
   - `preflight_round7_next20.csv`
   - `configs/friends_train_size_sweep_20260628_round7/round7_next20_scoring_encoding.json`
5. Dry-run the round7 config.
6. Run summaries with skip-existing behavior.
7. Validate selected summary outputs.
8. Run 14-ROI scoring with `--scoring-workers 6`.
9. Validate selected scoring outputs, warning metadata, and zero-filled failure
   state.
10. Run manifest generation.
11. Validate manifest split counts and ROI feature coverage.
12. Run `fit-roi-encoding` into the round7 115-train snapshot directory.
13. Extract and report encoding metrics.
14. Approved follow-up: expand the S06 head test set by 6 eligible episodes.
15. Run summaries and scoring for the added S06 test episodes.
16. Regenerate manifest and run a 115-train / 10-test encoding snapshot.
17. Approved follow-up: add 30 eligible episodes to the train split for a
    145-train / 10-test snapshot.
18. Run summary/scoring for the 30 new train episodes with a targeted
    split-complete config.
19. Regenerate manifest and run a 145-train / 10-test encoding snapshot.
20. Approved follow-up: screen 10 eligible episodes to add to the train split
    for a 155-train / 10-test snapshot.
21. Write round9 full and targeted scoring-only configs plus preflight
    JSON/CSV.
22. Dry-run both round9 configs before any provider-backed summary/scoring run.
23. Run final checks:
    - `git status --short --untracked-files=all`
    - `git diff --check`
    - config JSON parse
    - selected summary/scoring completeness validation
    - encoding metric extraction

## Planned Commands

Use `uv run` for Python execution.

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_train_size_sweep_20260628_round7/round7_next20_scoring_encoding.json \
  --dry-run
```

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_train_size_sweep_20260628_round7/round7_next20_scoring_encoding.json \
  --stage summaries \
  --summary-workers 3 \
  --skip-existing-summaries
```

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_train_size_sweep_20260628_round7/round7_next20_scoring_encoding.json \
  --stage scoring \
  --scoring-workers 6
```

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_train_size_sweep_20260628_round7/round7_next20_scoring_encoding.json \
  --stage manifest
```

```bash
uv run python -m brain_region_pipeline fit-roi-encoding \
  --manifest friends/full_runs/friends_full_scoring_start_14roi_gemini35_20260612/encoding/roi_encoding_manifest.jsonl \
  --roi-schemas friends/full_runs/friends_full_scoring_start_14roi_gemini35_20260612/encoding/roi_schemas.json \
  --atlas-labels atlas/subregion_func_network_Yeo_updated.csv \
  --output-dir friends/analysis/train_size_sweep_20260628_round7/encoding_115train_next20_snapshot
```

## Review Gates

- Do not start provider-backed summary/scoring until the selected next20 list
  and config are reviewed.
- Do not run scoring until summaries exist for all selected episodes.
- Do not run manifest or encoding until all 280 selected ROI/episode scoring
  jobs validate cleanly.
- Stop and report if the preflight cannot find 20 eligible episodes under the
  current constraints.
- Stop and report if unresolved zero-filled failed batches remain after retry.

## Commit Scope Notes

When this task is eventually committed, keep staging scoped to:

- round7 configs,
- this task directory,
- selected next20 summary/scoring outputs,
- round7 analysis snapshot,
- full-run manifest/encoding files updated by the round7 run.

Do not stage unrelated train-size comparison curve files unless the user
explicitly folds them into this task.

## Execution Results

- Selected 20 new train episodes:
  `s03e10b`, `s03e11a`, `s03e11b`, `s03e12a`, `s03e12b`,
  `s03e13b`, `s03e14a`, `s03e14b`, `s03e15a`, `s03e15b`,
  `s03e16a`, `s03e16b`, `s03e17a`, `s03e17b`, `s03e18a`,
  `s03e18b`, `s03e19a`, `s03e19b`, `s03e20a`, `s03e20b`.
- Skipped `s03e06a` because its description is known bad; skipped `s03e13a`
  because description/H5 TR coverage was insufficient.
- Summary validation passed for all selected episodes.
- Scoring validation passed for all 280 ROI/episode pairs after a targeted
  overwrite rerun of `SMG/s03e20b` cleared one `missing_segment_zero_filled`
  warning.
- Manifest validation passed with 124 total rows: train=115, val=5, test=4.
- Encoding snapshot:
  `friends/analysis/train_size_sweep_20260628_round7/encoding_115train_next20_snapshot`.
- Primary metric:
  `mean_subject_mean_test_pearson=0.2220917195623162`.

## Follow-up: S06 Head Test Expansion

Approved added test episodes:

- `s06e02a`
- `s06e04a`
- `s06e05a`
- `s06e05b`
- `s06e06a`
- `s06e06b`

Rejected or deferred head candidates:

- `s06e02b`: insufficient description/H5 TR coverage.
- `s06e04b`: insufficient description/H5 TR coverage.
- `s06e07a`, `s06e08a`, `s06e08b`: valid backups, not part of the approved
  recommended +6 set.
- `s06e07b`: missing H5 dataset.

Expanded-test target split:

- train: 115
- validation: 5
- test: 10

Expanded-test encoding snapshot:

```bash
friends/analysis/train_size_sweep_20260628_round7/encoding_115train_10test_s06head_snapshot
```

Expanded-test execution results:

- Full config dry-run passed after appending the 6 approved S06 test episodes.
- Summary generation and validation passed for all 6 added test episodes:
  `s06e02a`, `s06e04a`, `s06e05a`, `s06e05b`, `s06e06a`, `s06e06b`.
- Targeted scoring used
  `configs/friends_train_size_sweep_20260628_round7/round7_s06head_plus6_scoring_only.json`
  to avoid refreshing all 130 manifest episodes.
- The targeted scoring command exited non-zero only because filler
  `SMG/s03e20b` had a stale `scoring_progress.json` resume mismatch; the
  approved +6 test set completed successfully.
- Scoring validation passed for all 84 added ROI/episode pairs:
  provider=`aihubmix`, model=`gemini-3.5-flash`, warning_count=0,
  failed_batches empty, zero_filled_segments=0.
- Added test TR rows validated consistently across all 14 ROI outputs:
  `s06e02a=453`, `s06e04a=439`, `s06e05a=452`, `s06e05b=486`,
  `s06e06a=443`, `s06e06b=478`.
- Manifest validation passed with 130 total rows: train=115, val=5, test=10.
- Expanded-test encoding snapshot:
  `friends/analysis/train_size_sweep_20260628_round7/encoding_115train_10test_s06head_snapshot`.
- Expanded-test primary metric:
  `mean_subject_mean_test_pearson=0.22223919585476926`.
- Expanded-test subject details:
  best_alpha=10000.0, n_test_trs=4467, n_retained_parcels=86.

## Follow-up: Round8 +30 Train Expansion

Approved added train episodes:

- `s03e21a`
- `s03e21b`
- `s03e22a`
- `s03e22b`
- `s03e23a`
- `s03e23b`
- `s03e24a`
- `s03e24b`
- `s03e25a`
- `s03e25b`
- `s04e01a`
- `s04e01b`
- `s04e02a`
- `s04e02b`
- `s04e03a`
- `s04e03b`
- `s04e04a`
- `s04e04b`
- `s04e05a`
- `s04e05b`
- `s04e06a`
- `s04e06b`
- `s04e07a`
- `s04e07b`
- `s04e08a`
- `s04e08b`
- `s04e09a`
- `s04e09b`
- `s04e10a`
- `s04e10b`

Round8 target split:

- train: 145
- validation: 5
- test: 10

Round8 config and audit files:

- `configs/friends_train_size_sweep_20260629_round8/round8_next30_145train_10test_scoring_encoding.json`
- `configs/friends_train_size_sweep_20260629_round8/round8_next30_scoring_only.json`
- `.trellis/tasks/06-28-friends-round7-next20-summary-scoring-encoding/preflight_round8_next30_145train.json`
- `.trellis/tasks/06-28-friends-round7-next20-summary-scoring-encoding/preflight_round8_next30_145train.csv`

Round8 encoding snapshot:

```bash
friends/analysis/train_size_sweep_20260629_round8/encoding_145train_10test_snapshot
```

Round8 execution results:

- Full and targeted config dry-runs passed.
- Summary generation and validation passed for all 30 added train episodes.
- Targeted scoring used
  `configs/friends_train_size_sweep_20260629_round8/round8_next30_scoring_only.json`
  to avoid refreshing all 160 manifest episodes during provider-backed
  scoring.
- Scoring validation passed for all 420 added ROI/episode pairs after one
  `--retry-failed-batches` pass: warning_count=0, failed_batches empty,
  zero-filled segment files=0.
- Added train TR rows validated consistently across all 14 ROI outputs:
  `s03e21a/b=460`, `s03e22a/b=463`, `s03e23a/b=470`,
  `s03e24a/b=454`, `s03e25a/b=479`, `s04e01a/b=468`,
  `s04e02a/b=478`, `s04e03a/b=445`, `s04e04a/b=453`,
  `s04e05a/b=471`, `s04e06a/b=465`, `s04e07a/b=497`,
  `s04e08a/b=503`, `s04e09a/b=441`, `s04e10a/b=449`.
- Manifest validation passed with 160 total rows: train=145, val=5, test=10;
  every manifest row has 14 ROI feature paths and all H5/feature paths exist.
- Round8 encoding primary metric:
  `mean_subject_mean_test_pearson=0.22569421197201892`.
- Round8 subject details:
  best_alpha=10000.0, n_test_trs=4467, n_retained_parcels=86.
- The default full-run encoding directory was rerun with the full round8
  config after the targeted retry pass so its `group_summary.json` is aligned
  with the 160-row manifest.
- Delta from the 115-train / 10-test S06-head snapshot:
  `+0.0034550161172496596` mean_subject_mean_test_pearson.
- Validation artifacts:
  `summary_validation_round8_next30_145train.json`,
  `scoring_validation_round8_next30_145train.json`,
  `manifest_validation_round8_next30_145train.json`,
  `encoding_validation_round8_next30_145train.json`.

## Follow-up: Round9 +10 Train Screening

Selected 10 new train episodes:

- `s04e11a`
- `s04e11b`
- `s04e12a`
- `s04e12b`
- `s04e13a`
- `s04e13b`
- `s04e14a`
- `s04e14b`
- `s04e15a`
- `s04e15b`

Round9 target split:

- train: 155
- validation: 5
- test: 10

Round9 config and audit files:

- `configs/friends_train_size_sweep_20260630_round9/round9_next10_155train_10test_scoring_encoding.json`
- `configs/friends_train_size_sweep_20260630_round9/round9_next10_scoring_only.json`
- `.trellis/tasks/06-28-friends-round7-next20-summary-scoring-encoding/preflight_round9_next10_155train.json`
- `.trellis/tasks/06-28-friends-round7-next20-summary-scoring-encoding/preflight_round9_next10_155train.csv`

Round9 screening results:

- Candidate audit considered 341 episode ids and found 105 eligible unused train
  candidates after excluding current train/val/test episodes, `s03e06a`,
  missing inputs, failed TR coverage, and unresolved scoring warnings.
- Selected coverage:
  `s04e11a/b=483`, `s04e12a/b=466`, `s04e13a/b=448`,
  `s04e14a=447`, `s04e14b=446 inferred feature TRs vs 447 H5 TRs`,
  `s04e15a/b=444`.
- All selected episodes pass the 5-TR trim contract. `s04e14b` has margin=4,
  which still satisfies `inferred_feature_trs >= h5_trs - 5`.
- No selected episode currently has complete summary or scoring outputs, so the
  next execution stage should run summary generation first.
- Full config dry-run passed with 170 total episodes and 2380 ROI/episode
  scoring jobs.
- Targeted scoring-only config dry-run passed with 12 total episodes and 168
  ROI/episode scoring jobs.
- Summary generation and validation passed for all 10 selected train episodes.
- Provider retry note: `AIHUBMIX_BASE_URL=https://api.inferera.com/` continued
  to produce batch warnings, so scoring was switched back to
  `https://aihubmix.com/gemini`; a later retry and same-concurrency scoring
  resume completed without new batch warnings.
- Scoring validation passed for all 140 added ROI/episode pairs:
  warning_count=0, failed_batches empty, zero-filled segment files=0.
- Manifest validation passed with 170 total rows: train=155, val=5, test=10;
  every manifest row has 14 ROI feature paths and all H5/feature paths exist.
- Round9 encoding snapshot:
  `friends/analysis/train_size_sweep_20260630_round9/encoding_155train_10test_snapshot`.
- Round9 encoding primary metric:
  `mean_subject_mean_test_pearson=0.22744391736273634`.
- Round9 subject details:
  best_alpha=10000.0, n_test_trs=4467, n_retained_parcels=86.
- Delta from the round8 145-train / 10-test snapshot:
  `+0.00174970539071742` mean_subject_mean_test_pearson.
- The default full-run encoding directory was rerun with the full round9 config
  after targeted scoring passed, so its `group_summary.json` is aligned with
  the 170-row manifest.
- Validation artifacts:
  `summary_validation_round9_next10_155train.json`,
  `scoring_validation_round9_next10_155train.json`,
  `manifest_validation_round9_next10_155train.json`,
  `encoding_validation_round9_next10_155train.json`.

## Follow-up: Round8 BN246 All-Parcel Encoding Test

User-approved scope:

- Reuse the latest completed round8 145-train / 10-test encoding inputs.
- Keep the existing 14 ROI scored feature sets unchanged.
- Expand the target fMRI parcel selection to all Brainnetome label ids
  `1..246`.
- Do not run any provider-backed summary/scoring job.

Experimental schema and output paths:

- BN246 all-parcel schema copies:
  `friends/analysis/train_size_sweep_20260629_round8/bn246_allparcels_schemas/`
- BN246 all-parcel schema mapping:
  `friends/analysis/train_size_sweep_20260629_round8/roi_schemas_bn246_allparcels.json`
- BN246 all-parcel encoding snapshot:
  `friends/analysis/train_size_sweep_20260629_round8/encoding_145train_10test_bn246_allparcels_snapshot`
- Validation summary:
  `.trellis/tasks/06-28-friends-round7-next20-summary-scoring-encoding/encoding_validation_round8_bn246_allparcels.json`

Execution and validation results:

- Schema validation confirmed 14 ROI schema copies, each selecting 246
  Brainnetome parcels, with a 246-parcel union.
- Manifest reuse preserved the round8 split shape: 160 rows total, train=145,
  validation=5, test=10.
- Encoding completed with selected_parcels=246, retained_parcels=246,
  finite parcel Pearson rows=246, and n_test_trs=4467.
- BN246 all-parcel primary metric:
  `mean_subject_mean_test_pearson=0.195873864052212`.
- BN246 all-parcel subject details:
  best_alpha=10000.0,
  `mean_subject_median_test_pearson=0.18435572026160357`.
- Delta from the round8 86-parcel ROI-selected baseline:
  `-0.029820347919806922` mean_subject_mean_test_pearson.

Interpretation note:

- Because every ROI schema copy selects all 246 target parcels, per-ROI
  summaries are intentionally identical and should not be interpreted as
  anatomical ROI summaries. The meaningful comparisons are the overall
  all-parcel summary and parcel-level metrics.
