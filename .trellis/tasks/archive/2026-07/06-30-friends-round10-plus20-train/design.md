# Design

## Architecture and Boundaries

This task stays inside the existing Friends pilot configuration boundary. The
maintained pipeline already owns scoring, manifest refresh, and encoding through
`brain_region_pipeline.pilot` and `scripts/run_friends_14roi_concurrent_pilot.py`.
No new Python workflow code is needed.

The round10 artifacts should be derived from the round9 config rather than
hand-written from scratch, so path conventions, ROI definitions, generation
settings, lags, alphas, atlas labels, and trim values stay synchronized.

## Data Flow

1. Load the round9 full config.
2. Validate the selected round10 episodes against:
   - refined description file exists;
   - H5 dataset exists in `friends/BN/sub-01/BN_246.h5`;
   - inferred description TR count satisfies
     `h5_trs - fmri_trim_end_tr <= inferred_trs <= h5_trs`.
3. Create a scoring-only config containing the 20 new train episodes plus one
   unchanged validation episode and one unchanged test episode, matching prior
   `scoring_only` config shape.
4. Create a full scoring/encoding config by appending the 20 train episodes to
   the round9 full config while preserving existing val/test rows.
5. Validate the full config with the existing `run-multi-roi-pilot --dry-run`
   path.
6. Run the operational stages requested by the user:
   - `summaries` and `scoring` on `round10_next20_scoring_only.json`;
   - `manifest` and `encoding` on
     `round10_next20_175train_10test_scoring_encoding.json`.

## Contracts

- Episode entries keep the existing shape:
  `episode_id`, `split`, `descriptions`, and `h5_dataset`.
- Relative paths continue to be written relative to the config directory.
- The full config keeps the shared `output_root` so existing scored ROI outputs
  can be reused and the new episodes can be scored into the same tree.
- The scoring-only config keeps provider/model as `aihubmix` /
  `gemini-3.5-flash`.
- Scoring runs in resume mode unless explicitly overwritten; existing complete
  outputs are reused.
- Manifest/encoding runs against the full config so validation and test splits
  remain the canonical round10 `175/5/10` split.

## Trade-offs

- Backfilling technically eligible early season gaps would also pass the TR/H5
  rule, but it would disrupt the current sequential expansion pattern. Round10
  therefore continues after the current round9 train tail.
- Running scoring is provider-dependent and may require retry/repair if
  `batch_generation_failed_zero_filled` or active `missing_segment_zero_filled`
  warnings remain. Validation should inspect current metadata, not just logs.

## Rollback

- Delete the new `configs/friends_train_size_sweep_20260630_round10/`
  directory if the selected episodes or naming need to change.
- No existing config or pipeline code should need rollback.
