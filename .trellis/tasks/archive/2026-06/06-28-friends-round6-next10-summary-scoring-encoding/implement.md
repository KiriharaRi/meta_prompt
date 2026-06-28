# Implement: Friends round6 next10 summary scoring encoding

## Checklist

1. Inspect `s03e06a` description and report abnormal timeline evidence to the
   user.
2. Generate a deterministic preflight report for the round6 candidates.
3. Create `configs/friends_train_size_sweep_20260628_round6/round6_scoring_encoding.json`
   from the round5 template with the selected 10 episodes appended as train.
4. Dry-run the config with the concurrent Friends runner.
5. Run summaries with skip-existing behavior.
6. Validate selected summary outputs.
7. Run 14-ROI scoring with `--scoring-workers 6`.
8. Validate selected scoring outputs and failed-batch metadata.
9. Run manifest via the concurrent pilot.
10. Run `fit-roi-encoding` directly into the round6 analysis snapshot.
11. Run final checks:
    - `git status --short`
    - config JSON parse/dry-run
    - selected summary/scoring completeness validation
    - encoding metric extraction

## Commands

Use `uv run` for Python execution.

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_train_size_sweep_20260628_round6/round6_scoring_encoding.json \
  --dry-run
```

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_train_size_sweep_20260628_round6/round6_scoring_encoding.json \
  --stage summaries \
  --summary-workers 3 \
  --skip-existing-summaries
```

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_train_size_sweep_20260628_round6/round6_scoring_encoding.json \
  --stage scoring \
  --scoring-workers 6
```

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_train_size_sweep_20260628_round6/round6_scoring_encoding.json \
  --stage manifest

uv run python -m brain_region_pipeline fit-roi-encoding \
  --manifest friends/full_runs/friends_full_scoring_start_14roi_gemini35_20260612/encoding/roi_encoding_manifest.jsonl \
  --roi-schemas friends/full_runs/friends_full_scoring_start_14roi_gemini35_20260612/encoding/roi_schemas.json \
  --atlas-labels atlas/subregion_func_network_Yeo_updated.csv \
  --output-dir friends/analysis/train_size_sweep_20260628_round6/encoding_85train_snapshot
```

## Review Gates

- Do not run scoring until summaries exist for the selected 10 episodes.
- Do not run encoding until all 140 selected ROI/episode scoring jobs are
  complete.
- Stop and report if provider failures create unresolved zero-filled batches.
