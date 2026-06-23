# Friends Next10 Scoring and Encoding Prep

## Goal

Find 10 additional Friends episode segments that satisfy the existing scoring
and fMRI encoding eligibility checks, then prepare the plan for a follow-up
14-ROI scoring plus manifest/encoding run.

## What I already know

* The previous completed split has 35 train episode segments, 5 validation
  episode segments, and 4 held-out test episode segments.
* Existing output root is
  `friends/full_runs/friends_full_scoring_start_14roi_gemini35_20260612`.
* Existing plus10 config is
  `configs/friends_train_size_sweep_20260617/plus10_scoring_encoding.json`.
* Scoring should continue to use `generation_provider: "aihubmix"` and
  `generation_model: "gemini-3.5-flash"` unless explicitly changed.
* Default encoding trim remains `fmri_trim_start_tr=5` and
  `fmri_trim_end_tr=5`.
* Scoring TR coverage is inferred as `ceil(max(description_end_s) / 1.49)`
  when no explicit `total_trs` is provided.
* `s01e04a` and `s01e04b` still fail the default TR-length check and should
  stay excluded unless the encoding trim policy changes.

## Assumptions

* "符合要求和 tr 长度" means the candidate has:
  * refined description file,
  * H5 dataset in `friends/BN/sub-01/BN_246.h5`,
  * existing summary and summary metadata in the full-run output root,
  * description-derived feature TR coverage through `h5_trs - 5`,
  * no existing complete 14-ROI score set.
* The new 10 episode segments will be added to the train split, while existing
  S02 validation and S06 test episodes remain unchanged.
* Existing summaries, domain pools, ROI schemas, and complete scores should be
  reused.

## Candidate Episodes

### Recommended Conservative Set

This set avoids using the `b` halves of S02 episodes whose `a` halves are
currently validation episodes (`s02e01a` to `s02e05a`), reducing possible
validation/train proximity.

| episode_id | h5_dataset | inferred_feature_trs | h5_trs | needed_end | margin |
|---|---|---:|---:|---:|---:|
| `s01e23b` | `ses-010_task-s01e23b` | 462 | 462 | 457 | 5 |
| `s01e24a` | `ses-010_task-s01e24a` | 515 | 515 | 510 | 5 |
| `s01e24b` | `ses-010_task-s01e24b` | 515 | 515 | 510 | 5 |
| `s02e06a` | `ses-012_task-s02e06a` | 500 | 500 | 495 | 5 |
| `s02e06b` | `ses-012_task-s02e06b` | 500 | 500 | 495 | 5 |
| `s02e07a` | `ses-012_task-s02e07a` | 496 | 496 | 491 | 5 |
| `s02e07b` | `ses-012_task-s02e07b` | 496 | 496 | 491 | 5 |
| `s02e08a` | `ses-013_task-s02e08a` | 458 | 458 | 453 | 5 |
| `s02e08b` | `ses-013_task-s02e08b` | 457 | 458 | 453 | 4 |
| `s02e09a` | `ses-013_task-s02e09a` | 452 | 452 | 447 | 5 |

### Strict Chronological Set

This set simply takes the next 10 eligible segments after the current split,
but includes `s02e01b` to `s02e05b`, whose matching `a` halves are validation
segments.

* `s01e23b`
* `s01e24a`
* `s01e24b`
* `s02e01b`
* `s02e02b`
* `s02e03b`
* `s02e04b`
* `s02e05b`
* `s02e06a`
* `s02e06b`

### Additional Eligible Pool

There are 43 total aligned candidates not already in the plus10 config and not
fully scored. After the recommended conservative set, the next available
segments include:

* `s02e09a`, `s02e10a`, `s02e10b`, `s02e11a`, `s02e12a`, `s02e12b`
* `s02e13a`, `s02e13b`, `s02e14a`, `s02e14b`, `s02e15a`, `s02e15b`
* `s02e16a`, `s02e16b`, `s02e17a`, `s02e17b`, `s02e18a`, `s02e18b`
* `s02e19a`, `s02e19b`, `s02e20a`, `s02e20b`, `s02e21a`, `s02e21b`
* `s02e22a`, `s02e22b`, `s02e23a`, `s02e23b`, `s02e24b`

## Decision

* Use the recommended conservative validation-safe set.
* Do not include `s02e01b` to `s02e05b` in this next train expansion because
  their matching `a` halves are currently validation episodes.

## Requirements

* Select exactly 10 eligible episode segments for the next scoring/encoding
  run.
* Use the recommended conservative validation-safe set:
  * `s01e23b`
  * `s01e24a`
  * `s01e24b`
  * `s02e06a`
  * `s02e06b`
  * `s02e07a`
  * `s02e07b`
  * `s02e08a`
  * `s02e08b`
  * `s02e09a`
* Keep the 14 ROI list unchanged.
* Keep existing S02 validation and S06 test splits unchanged unless the user
  explicitly chooses a different split policy.
* Use `aihubmix` with `gemini-3.5-flash` for new LLM scoring.
* Run no scoring or encoding until the selected episode set is confirmed.

## Acceptance Criteria

* [ ] The selected 10 episode segments each have a refined description file.
* [ ] Each selected segment has an H5 dataset in `BN_246.h5`.
* [ ] Each selected segment has summary outputs available.
* [ ] Each selected segment satisfies `inferred_feature_trs >= h5_trs - 5`.
* [ ] Each selected segment is not already fully scored across all 14 ROI.
* [ ] A follow-up config can be generated from the confirmed selection.

## Definition of Done

* User confirms the selected 10 episode segments.
* A dedicated config is prepared only after confirmation.
* Validation commands complete or any blocker is reported.
* No scoring or encoding is started without explicit user approval.

## Technical Approach

Use the prior plus10 config as the base, append the confirmed new 10 episode
segments to the train split, keep validation/test fixed, then run the existing
concurrent Friends 14-ROI runner in staged mode: scoring first, then manifest
and encoding.

## Out of Scope

* Regenerating domain pools or ROI schemas.
* Changing encoding trim policy.
* Adding `s01e04a` or `s01e04b` under the current default trim.
* Starting LLM scoring before the user confirms the selected set.

## Technical Notes

* Candidate scan used project parser `brain_region_pipeline.scoring.description_io`.
* H5 source: `friends/BN/sub-01/BN_246.h5`.
* ROI count under current full-run root: 14.
* Current config split count: 35 train, 5 val, 4 test.
* All listed candidates have 0 complete ROI scores out of 14 at scan time.
