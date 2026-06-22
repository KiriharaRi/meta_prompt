# Friends S01 Train / S02 Validation Encoding

## Goal

Run a Friends fMRI Ridge encoding experiment using existing 14-ROI scoring outputs, with all eligible S01 episodes as training samples, S02 episodes as validation samples, and S06 episodes as held-out test samples.

## Requirements

* Reuse existing scoring artifacts under `friends/full_runs/friends_full_scoring_start_14roi_gemini35_20260612`; do not rerun LLM scoring.
* Include `s01e02a` in training because it has all required ROI `tr_features.jsonl` files, a description file, and the H5 dataset `ses-001_task-s01e02a`.
* Use these 25 S01 training episodes:
  * `s01e01a`
  * `s01e02a`
  * `s01e03a`
  * `s01e05a`
  * `s01e06a`
  * `s01e01b`
  * `s01e02b`
  * `s01e03b`
  * `s01e05b`
  * `s01e06b`
  * `s01e11a`
  * `s01e11b`
  * `s01e12a`
  * `s01e12b`
  * `s01e13a`
  * `s01e13b`
  * `s01e14a`
  * `s01e14b`
  * `s01e15b`
  * `s01e16a`
  * `s01e16b`
  * `s01e17a`
  * `s01e17b`
  * `s01e18a`
  * `s01e18b`
* Use these 5 S02 validation episodes:
  * `s02e01a`
  * `s02e02a`
  * `s02e03a`
  * `s02e04a`
  * `s02e05a`
* Use these 4 S06 test episodes:
  * `s06e01a`
  * `s06e01b`
  * `s06e03a`
  * `s06e03b`
* Run manifest generation and encoding only.
* Report overall and ROI-level fMRI prediction performance from encoding outputs.

## Acceptance Criteria

* [ ] A dedicated config exists for the S01/S02/S06 split.
* [ ] The generated manifest contains 25 train rows, 5 validation rows, and 4 test rows.
* [ ] Encoding completes successfully with `uv run`.
* [ ] The final response reports `mean_subject_mean_test_pearson`, median test Pearson, selected alpha, retained parcels, test TR count, and ROI-level Pearson values.

## Definition of Done

* Config and generated encoding outputs are present in task-specific analysis paths.
* No LLM scoring stage is rerun.
* Relevant verification commands complete or any failure is explicitly reported.
* Any reusable project knowledge is considered for Trellis spec updates.

## Technical Approach

Create a config under `configs/friends_train_size_sweep_20260617/` following the existing sweep configs. Use `run-multi-roi-pilot` or the equivalent manifest/encoding APIs to build a split-specific manifest from existing scoring features and fit Ridge encoding.

To avoid losing previous full-run encoding snapshots, preserve the resulting encoding output under `friends/analysis/train_size_sweep_20260617/s01_train_s02_val/encoding/`.

## Decision (ADR-lite)

**Context**: Prior train-size sweep configs kept `s01e02a` as validation, but the user requested S02 as validation and S01 as training.

**Decision**: Include `s01e02a` in training because required scoring and fMRI inputs are available.

**Consequences**: The experiment uses 30 non-S06 episodes instead of the earlier 29-episode scoring subset. Results are best compared as a new split variant rather than directly as `train_20`.

## Out of Scope

* Regenerating summaries, domain pools, schemas, or scoring outputs.
* Changing model code unless an execution bug blocks the experiment.
* Running additional subjects beyond `sub-01`.

## Technical Notes

* Existing H5 file: `friends/BN/sub-01/BN_246.h5`.
* Existing scoring root: `friends/full_runs/friends_full_scoring_start_14roi_gemini35_20260612`.
* `s01e02a` check passed before implementation: all 14 ROI `tr_features.jsonl` files exist, description exists, and H5 dataset shape is `(482, 246)`.
