# Design: Friends round7 next20 summary scoring encoding

## Boundaries

This task uses the existing config-driven Friends 14-ROI pipeline. It should
not introduce a source-code refactor unless the existing commands cannot
complete because of a confirmed bug. The main editable artifacts are configs,
Trellis audit files, Friends full-run summary/scoring outputs, and round7
analysis outputs.

The latest round6 all-scored config is the structural baseline. Round7 extends
that baseline by adding 20 new train episodes while preserving the fixed
validation split. A follow-up approved change expands the held-out S06 test
split with additional early-season eligible episodes. The next approved
follow-up creates a round8 config that appends 30 additional train episodes to
the 115-train / 10-test state. The next screening follow-up creates a round9
config that appends 10 additional train episodes to the 145-train / 10-test
state while preserving the same validation and test episodes.

## Data Flow

1. Read the round6 all-scored config to establish the current 95-train,
   5-validation, and initial 4-test episode sets.
2. Enumerate available Friends refined descriptions and H5 task datasets.
3. Build a candidate audit table with, at minimum:
   - episode id,
   - refined description path and existence,
   - H5 dataset and TR length,
   - description segment count,
   - inferred feature TR count,
   - current summary status,
   - current 14-ROI scoring status,
   - selected/excluded decision and skip reason.
4. Exclude already-used, reserved, known-bad, missing, or TR-ineligible
   episodes.
5. Select the next 20 eligible episodes deterministically from the remaining
   ordered candidate pool.
6. Write the round7 config with the selected 20 appended as `train`.
7. For the S06 test expansion, append only eligible approved S06 head episodes
   as `test`, after verifying refined descriptions, H5 datasets, and TR
   coverage.
8. Dry-run the config, then run summaries, scoring, manifest generation, and
   encoding with validation gates between stages.
9. For the +30 train follow-up, write a separate round8 full config for
   manifest/encoding and a smaller split-complete scoring config that targets
   only the 30 new train episodes plus minimal val/test fillers required by
   config validation.
10. For the +10 train follow-up, write a separate round9 full config for
    manifest/encoding and a smaller split-complete scoring config that targets
    only the 10 new train episodes plus minimal val/test fillers required by
    config validation.

## Output Strategy

- Config:
  `configs/friends_train_size_sweep_20260628_round7/round7_next20_scoring_encoding.json`
- Task audit files:
  `.trellis/tasks/06-28-friends-round7-next20-summary-scoring-encoding/`
- Summary/scoring output root:
  `friends/full_runs/friends_full_scoring_start_14roi_gemini35_20260612`
- Encoding snapshot:
  `friends/analysis/train_size_sweep_20260628_round7/encoding_115train_next20_snapshot`
- Expanded-test encoding snapshot:
  `friends/analysis/train_size_sweep_20260628_round7/encoding_115train_10test_s06head_snapshot`
- Round8 +30 train config:
  `configs/friends_train_size_sweep_20260629_round8/round8_next30_145train_10test_scoring_encoding.json`
- Round8 targeted scoring config:
  `configs/friends_train_size_sweep_20260629_round8/round8_next30_scoring_only.json`
- Round8 +30 train encoding snapshot:
  `friends/analysis/train_size_sweep_20260629_round8/encoding_145train_10test_snapshot`
- Round9 +10 train config:
  `configs/friends_train_size_sweep_20260630_round9/round9_next10_155train_10test_scoring_encoding.json`
- Round9 targeted scoring config:
  `configs/friends_train_size_sweep_20260630_round9/round9_next10_scoring_only.json`
- Round9 +10 train encoding snapshot:
  `friends/analysis/train_size_sweep_20260630_round9/encoding_155train_10test_snapshot`

The shared full-run encoding directory may be touched by manifest generation,
but final experiment metrics should be preserved in the dedicated round7
analysis snapshot.

## Contracts

- Candidate TR contract:
  `inferred_feature_trs >= h5_trs - fmri_trim_end_tr`.
- Split contract:
  fixed validation episodes stay unchanged; the held-out test set may contain
  the original S06 test episodes plus the approved S06 head expansion episodes.
  New train episodes remain train only. The +30 train follow-up keeps val=5 and
  test=10 while increasing train from 115 to 145. The +10 train screening
  follow-up keeps val=5 and test=10 while increasing train from 145 to 155.
- Scoring contract:
  each selected ROI/episode directory must contain `scoring_metadata.json`,
  `segment_region_scores.jsonl`, and `tr_features.jsonl`.
- Quality contract:
  zero unresolved failed zero-filled batches before manifest/encoding.
- Encoding contract:
  manifest rows must contain all configured ROI feature paths and preserve the
  same trim settings expected by the fMRI alignment code.

## Risks and Mitigations

- Provider failures can create partial summary/scoring outputs. Use resume and
  targeted retry behavior rather than deleting successful outputs.
- Some Friends descriptions may appear present but have abnormal time coverage.
  Treat TR coverage and known anomaly checks as required, not optional.
- There are unrelated uncommitted train-size curve artifacts in the worktree.
  Keep this task's staging/commit scope limited so those files are not
  accidentally bundled into round7.
- The shared full-run manifest path may be overwritten by the manifest stage.
  Preserve final metrics in the dedicated analysis snapshot.

## Rollback

- If the selected candidate list is rejected, remove only the round7 config and
  task-local preflight files.
- If summary/scoring has partial failures, keep completed outputs and retry
  only failed or incomplete episode/ROI jobs.
- If encoding fails after scoring validation passes, keep summary/scoring
  outputs and rerun only manifest/encoding after fixing the validation blocker.
