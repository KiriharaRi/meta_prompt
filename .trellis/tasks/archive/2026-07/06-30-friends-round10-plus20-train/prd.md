# Add 20 Friends train episodes for round10

## Goal

Extend the current Friends train-size sweep from the round9 baseline to a
round10 configuration with 20 additional train episodes that satisfy the
description/TR and H5 availability requirements.

After the round10 configs were created, the requested scope expanded to running
the round10 summaries, scoring, manifest refresh, and encoding stages.

The current baseline is:

- Source config:
  `configs/friends_train_size_sweep_20260630_round9/round9_next10_155train_10test_scoring_encoding.json`
- Split counts: `train=155`, `val=5`, `test=10`
- Encoding trim: `fmri_trim_start_tr=5`, `fmri_trim_end_tr=5`
- Provider/model provenance for scoring configs: `aihubmix` /
  `gemini-3.5-flash`

The target round10 split is `train=175`, `val=5`, `test=10`.

## Confirmed Facts

- The existing encoding path treats the fMRI trim interval as authoritative.
  A feature file may be slightly shorter than raw H5 as long as it still covers
  the retained fMRI interval.
- Current round9 train episodes use a conservative length profile: all are
  either exact `inferred_trs == h5_trs` or are shorter by at most 5 TRs.
- A read-only candidate scan found 95 remaining H5-linked episodes that meet
  this conservative rule: `h5_trs - 5 <= inferred_trs <= h5_trs`.
- `s04e16a` fails the conservative rule because its inferred description TR
  count is 59 rows shorter than H5.
- Some earlier missing episodes such as `s01e07a` meet the technical rule, but
  round10 should continue after the current round9 train tail rather than
  backfill early season gaps.

## Requirements

- Add these 20 episodes to the train split:
  - `s04e16b`
  - `s04e17a`
  - `s04e17b`
  - `s04e18a`
  - `s04e18b`
  - `s04e19a`
  - `s04e19b`
  - `s04e20a`
  - `s04e20b`
  - `s04e21a`
  - `s04e21b`
  - `s04e22a`
  - `s04e22b`
  - `s04e23a`
  - `s04e23b`
  - `s05e01a`
  - `s05e01b`
  - `s05e02a`
  - `s05e02b`
  - `s05e03a`
- Preserve the existing round9 validation and test episode sets unchanged.
- Keep the current scoring output root:
  `../../friends/full_runs/friends_full_scoring_start_14roi_gemini35_20260612`.
- Keep the current H5 file, atlas labels, ROI definitions, lags, alphas, and
  encoding trim values from round9.
- Produce a scoring-only config for the new 20 episodes and a full
  scoring/encoding config for the 175-train split.
- Follow the existing `scoring_only` config pattern by including the 20 new
  train episodes plus one unchanged validation episode and one unchanged test
  episode for runner compatibility checks.
- Do not modify existing round8/round9 configs or analysis reports.
- Do not overwrite unrelated dirty files already present in the working tree.
- Run the necessary workflow stages for round10:
  summaries for the scoring-only config, scoring for the scoring-only config,
  then manifest and encoding for the full 175-train config.

## Acceptance Criteria

- [x] A round10 scoring-only config exists with exactly the 20 selected train
      episodes, one unchanged validation episode, one unchanged test episode,
      and the same provider/model as round9.
- [x] A round10 scoring/encoding config exists with split counts
      `train=175`, `val=5`, `test=10`.
- [x] Every newly selected episode has a description file, an H5 dataset, and
      `h5_trs - 5 <= inferred_trs <= h5_trs`.
- [x] `run-multi-roi-pilot --dry-run` succeeds for the round10 full config.
- [x] Existing dirty files outside the round10 scope remain untouched.
- [x] Round10 scoring-only summaries complete for the 20 selected train
      episodes, reusing existing val/test summaries when present.
- [x] Round10 scoring outputs exist for every selected train ROI/episode pair.
- [x] Round10 full-config manifest refresh succeeds with split counts
      `train=175`, `val=5`, `test=10`.
- [x] Round10 encoding completes and writes `group_summary.json` plus
      `encoding_metadata.json`.
- [x] Final validation confirms no missing selected outputs, no residual
      blocking scoring warnings, expected provider/model provenance, and a
      readable final test metric.

## Out of Scope

- Changing pipeline code or scoring/encoding algorithms.
- Changing validation/test splits.
- Regenerating round8 interpretability artifacts.

## Notes

- This task is configuration/data-workflow focused. If full scoring is deferred,
  the produced configs should still be directly runnable with the existing
  Friends pilot script.
- Before the run request, the selected 20 train episodes did not have
  `tr_features.jsonl` outputs under the shared full-run root.
- The completed round10 encoding metric is
  `mean_subject_mean_test_pearson=0.22847160573835776`.
