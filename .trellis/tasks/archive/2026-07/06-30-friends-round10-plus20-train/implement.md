# Implementation Plan

## Checklist

- [x] Load backend development guidance before editing.
- [x] Re-run the read-only candidate validator and record the selected 20
      episode facts.
- [x] Generate `configs/friends_train_size_sweep_20260630_round10/`.
- [x] Add `round10_next20_scoring_only.json`.
- [x] Add `round10_next20_175train_10test_scoring_encoding.json`.
- [x] Verify split counts and provider/model fields with `jq`.
- [x] Run the round10 full config dry-run:
      `uv run python -m brain_region_pipeline run-multi-roi-pilot --config <config> --dry-run`.
- [x] Check that unrelated dirty files remain unchanged.
- [x] Check current summary/scoring coverage for selected round10 episodes.
- [x] Run scoring-only summaries with `--skip-existing-summaries`.
- [x] Run scoring-only scoring in resume mode.
- [x] Run full-config manifest refresh.
- [x] Run full-config encoding.
- [x] Validate selected scoring outputs, manifest split counts, and final
      encoding metrics.

## Run Results

- Summary stage completed with 6 workers and `--skip-existing-summaries`.
- Scoring stage completed with 6 workers for 308 scoring-only ROI/episode jobs.
- Output validation found 0 missing scoring files, 0 provider/model mismatches,
  0 failed batches, and 0 zero-filled segments across the scoring-only config.
- Full manifest refresh wrote 190 samples with split counts
  `train=175`, `val=5`, `test=10`; every row has 14 ROI feature files.
- Encoding completed with primary metric
  `mean_subject_mean_test_pearson=0.22847160573835776`.
- Snapshot copied to
  `friends/analysis/train_size_sweep_20260630_round10/encoding_175train_10test_snapshot/`.

## Validation Commands

```bash
uv run python -m brain_region_pipeline run-multi-roi-pilot \
  --config configs/friends_train_size_sweep_20260630_round10/round10_next20_175train_10test_scoring_encoding.json \
  --dry-run

jq '{episode_count:(.episodes|length), split_counts:(.episodes|group_by(.split)|map({split:.[0].split,count:length})), generation_provider, generation_model}' \
  configs/friends_train_size_sweep_20260630_round10/round10_next20_175train_10test_scoring_encoding.json

uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_train_size_sweep_20260630_round10/round10_next20_scoring_only.json \
  --stage summaries \
  --summary-workers 6 \
  --skip-existing-summaries

uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_train_size_sweep_20260630_round10/round10_next20_scoring_only.json \
  --stage scoring \
  --scoring-workers 6

uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_train_size_sweep_20260630_round10/round10_next20_175train_10test_scoring_encoding.json \
  --stage manifest

uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_train_size_sweep_20260630_round10/round10_next20_175train_10test_scoring_encoding.json \
  --stage encoding
```

## Risky Files and Rollback Points

- New configs are the only intended tracked-source edits.
- The working tree already has unrelated dirty files under round8
  interpretability artifacts; leave them untouched.
- If generation fails, remove the new round10 config directory and regenerate
  from the round9 source config.
