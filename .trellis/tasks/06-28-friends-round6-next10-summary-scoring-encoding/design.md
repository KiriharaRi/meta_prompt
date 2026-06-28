# Design: Friends round6 next10 summary scoring encoding

## Boundaries

This is an experiment execution task, not a source-code refactor. The work uses
the existing config-driven Friends 14-ROI runner, existing ROI schemas, existing
H5 source, and the same validation/test split policy as recent runs.

## Data Flow

1. Use `75_from65_round5_add10.json` as the structural template.
2. Exclude the union of episode rows in the current round4 and round5
   75-train configs.
3. Select the confirmed 10 valid candidates, skipping abnormal `s03e06a`.
4. Write a new round6 config with the selected episodes appended as `train`.
5. Write preflight JSON/CSV evidence under the Trellis task directory.
6. Run `scripts/run_friends_14roi_concurrent_pilot.py` in stages:
   - `summaries`
   - `scoring`
   - `manifest`
7. Run `fit-roi-encoding` directly from the generated manifest into the round6
   analysis snapshot.
8. Validate artifacts between each stage before moving to the next stage.

## Output Strategy

- Keep summary/scoring outputs under the existing full-run output root because
  the ROI schema and scoring corpus are already organized there:
  `friends/full_runs/friends_full_scoring_start_14roi_gemini35_20260612`.
- Preserve encoding results in a dedicated snapshot directory under
  `friends/analysis/train_size_sweep_20260628_round6/` by invoking
  `fit-roi-encoding` with that output directory. The shared
  `full_runs/.../encoding` directory should only be used for generated manifest
  sidecars in this task.

## Contracts

- Candidate TR contract:
  `inferred_feature_trs >= h5_trs - fmri_trim_end_tr`.
- Manifest contract:
  every episode row must have all configured ROI `tr_features.jsonl` files and
  keep `fmri_trim_start_tr=5`, `fmri_trim_end_tr=5`.
- Scoring quality contract:
  selected ROI/episode scoring directories must contain metadata, segment
  scores, and TR features, and must not contain unresolved failed zero-filled
  batches.

## Operational Notes

- Summary/scoring may call an external provider and can fail transiently. Prefer
  resume/retry behavior instead of deleting completed outputs.
- `s03e06a` should remain documented as skipped because it has a description
  timeline much longer than its H5 dataset.
- Source changes are out of scope unless existing commands cannot complete due
  to a confirmed bug.

## Rollback

- Before running provider-backed stages, delete only the new config and preflight
  files if the candidate set is rejected.
- During summary/scoring, leave successful outputs in place and resume failed
  work.
- If encoding fails, keep scoring outputs and regenerate manifest/encoding only
  after fixing the validation blocker.
