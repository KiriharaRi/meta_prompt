# Design: Friends additional10 scoring and encoding

## Boundaries

This task is an experiment execution task, not a pipeline refactor. The work
should reuse the existing config-driven 14-ROI runner and existing full-run
schema outputs. Source-code edits are out of scope unless a real bug blocks the
run.

## Data Flow

1. Use the round3 config as the baseline contract for split policy, provider,
   ROI list, H5 source, scoring output root, manifest output, and encoding
   settings.
2. Enumerate available Friends episode segments from the refined description
   files and H5 datasets.
3. Exclude all round3 train, validation, and held-out test episodes.
4. For remaining candidates, verify:
   - refined description file can produce features;
   - matching H5 dataset is present;
   - summary file exists under the full-run schema output;
   - feature TR coverage satisfies the same tolerance used in prior runs.
5. Pick the first 10 valid candidates in deterministic episode order, unless
   evidence shows a candidate should be skipped.
6. Write a new round config that appends those 10 episodes to the round3 train
   split and leaves val/test unchanged.
7. Run scoring, validate new scoring outputs, refresh manifest, then run
   encoding.

## Compatibility

- The new config must be additive and must not mutate
  `round3_scoring_encoding.json`.
- Existing scoring outputs should be reused when already complete; retry logic
  should target failed or incomplete work rather than deleting successful
  outputs.
- The full-run schema source remains the existing scoring/summary output root.

## Operational Notes

- Scoring is external-provider dependent, so transient network/provider errors
  are expected. The runner's retry path should be preferred if failed batches
  are detected.
- Encoding should be delayed until a separate validation confirms no warning
  jobs and no zero-filled failed batches in the newly selected 10 episodes.
- If fewer than 10 candidates pass preflight, stop before scoring and report the
  blocker instead of weakening the H5/TR policy.

## Rollback

- Before scoring, remove only the new config and temporary preflight report if
  the candidate set is rejected.
- During scoring, leave completed outputs in place and use resume/retry
  behavior.
- Before encoding, preserve any existing encoding snapshot if the new run would
  overwrite a prior confirmed result.
