# Implementation Plan: Friends round3 next10 scoring and encoding

## Preconditions

- User has approved task creation.
- User must approve starting implementation before `task.py start`.
- Before encoding refresh, decide whether to snapshot the current 55-train
  `encoding/` directory. Recommended: snapshot it.

## Ordered Checklist

1. Verify current working tree status.
2. Create `configs/friends_train_size_sweep_20260625_round3/round3_scoring_encoding.json`
   from round2 config with the 10 selected train episodes appended.
3. Validate split counts are `65 train / 5 val / 4 test`.
4. Re-run preflight for the 10 selected episodes:
   description exists, H5 dataset exists, summary exists, and feature TR
   coverage reaches the default trimmed fMRI interval.
5. Dry-run the scoring stage:
   `uv run python scripts/run_friends_14roi_concurrent_pilot.py --config configs/friends_train_size_sweep_20260625_round3/round3_scoring_encoding.json --stage scoring --scoring-workers 6 --dry-run`
6. If preserving the 55-train baseline, copy the current encoding directory to
   a clearly named analysis/snapshot directory before refreshing encoding.
7. Launch scoring with concurrency 6:
   `uv run python scripts/run_friends_14roi_concurrent_pilot.py --config configs/friends_train_size_sweep_20260625_round3/round3_scoring_encoding.json --stage scoring --scoring-workers 6`
8. Poll early scoring frequently:
   - read runner output;
   - count completed metadata files among the 140 new jobs;
   - check warning files and zero-filled batches;
   - inspect progress files for active representative jobs.
9. Once progress is stable and no warning pattern appears, reduce polling
   frequency.
10. After scoring finishes, validate all 140 new scoring outputs.
11. Run manifest refresh:
   `uv run python scripts/run_friends_14roi_concurrent_pilot.py --config configs/friends_train_size_sweep_20260625_round3/round3_scoring_encoding.json --stage manifest`
12. Validate manifest rows, split counts, and 14 ROI feature coverage.
13. Run encoding:
   `uv run python scripts/run_friends_14roi_concurrent_pilot.py --config configs/friends_train_size_sweep_20260625_round3/round3_scoring_encoding.json --stage encoding`
14. Summarize final metrics and compare primary metric to the 55-train baseline
    `0.20813553012023459`.
15. Report output paths, warnings, failures, and remaining risks.

## Validation Commands

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py --config configs/friends_train_size_sweep_20260625_round3/round3_scoring_encoding.json --stage scoring --scoring-workers 6 --dry-run
```

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py --config configs/friends_train_size_sweep_20260625_round3/round3_scoring_encoding.json --stage manifest
```

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py --config configs/friends_train_size_sweep_20260625_round3/round3_scoring_encoding.json --stage encoding
```

## Rollback Points

- Before scoring: delete only the new round3 config if the selected episodes
  are rejected.
- During scoring: rely on resume-compatible outputs; do not overwrite unless a
  concrete incompatible partial state is identified.
- Before encoding: snapshot 55-train encoding if requested or if preserving the
  known baseline is important.
- After failed scoring: do not run encoding; inspect warnings and retry failed
  batches first.

## Execution Notes

- Created
  `configs/friends_train_size_sweep_20260625_round3/round3_scoring_encoding.json`
  from the round2 config.
- Preserved the 55-train encoding baseline at
  `friends/analysis/train_size_sweep_20260625_round3/encoding_55train_snapshot/`.
- Dry-run completed successfully with scoring concurrency 6.
- Main scoring completed all 140 new ROI/episode outputs, but an early provider
  network failure left zero-filled failed-batch warnings.
- Retried failed batches with:
  `uv run python scripts/run_friends_14roi_concurrent_pilot.py --config configs/friends_train_size_sweep_20260625_round3/round3_scoring_encoding.json --retry-failed-batches --scoring-workers 6`
- Retry completed, refreshed the manifest, and ran encoding automatically.
- Final scoring validation:
  `complete=140`, `partial=0`, `missing=0`, `warning_jobs=0`,
  `zero_filled=0`.
- Final encoding:
  `mean_subject_mean_test_pearson = 0.21207336267220675`,
  `mean_subject_median_test_pearson = 0.2048392383408515`,
  `best_alpha = 10000.0`, `n_retained_parcels = 86`, `n_test_trs = 1812`.
