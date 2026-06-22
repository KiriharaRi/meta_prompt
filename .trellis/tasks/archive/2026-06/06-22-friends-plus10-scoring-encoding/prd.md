# Friends Plus10 Scoring and Encoding

## Goal

Add 10 more eligible Friends episodes to the current 14-ROI scoring corpus, then refresh the encoding manifest and Ridge fMRI encoding outputs for a new split-specific run.

## What I already know

* The previous `friends-s01-train-s02-val-encoding` task is considered leftover and should not drive this task.
* Current complete 14-ROI scoring coverage under `friends/full_runs/friends_full_scoring_start_14roi_gemini35_20260612` includes 34 episodes: 25 S01 train candidates, 5 S02 validation episodes, and 4 S06 test episodes.
* There are 15 S01 episodes not yet fully scored that have local description files, H5 datasets, and existing summary metadata under the current full-run output root.
* The existing concurrent runner supports staged execution: `scoring`, `manifest`, and `encoding`.
* `s01e04a` and `s01e04b` are not valid default added targets because their description-derived TR coverage is shorter than the default trimmed fMRI interval required by encoding.
* LLM scoring should use `aihubmix` with the existing `gemini-3.5-flash` config pattern.

## Assumptions

* "符合要求" means each added episode must have a refined description file, an H5 dataset in `friends/BN/sub-01/BN_246.h5`, existing summary output, missing/incomplete 14-ROI scoring, and description-derived TR coverage that reaches the default trimmed fMRI interval.
* The 10 additional episodes should be added to the train split, while S02 remains validation and S06 remains held-out test, unless the user chooses a different split policy.
* Existing complete scoring outputs should be reused in resume mode; only missing episode/ROI scoring should call the LLM.
* `AIHUBMIX_API_KEY` must be available in the execution environment before running scoring.

## Candidate Episodes

Recommended first 10 that pass description/H5 length alignment:

* `s01e15a` -> `ses-007_task-s01e15a`
* `s01e19a` -> `ses-008_task-s01e19a`
* `s01e19b` -> `ses-008_task-s01e19b`
* `s01e20a` -> `ses-009_task-s01e20a`
* `s01e20b` -> `ses-009_task-s01e20b`
* `s01e21a` -> `ses-009_task-s01e21a`
* `s01e21b` -> `ses-009_task-s01e21b`
* `s01e22a` -> `ses-009_task-s01e22a`
* `s01e22b` -> `ses-009_task-s01e22b`
* `s01e23a` -> `ses-010_task-s01e23a`

Other eligible candidates if the chosen set changes:

* `s01e23b`
* `s01e24a`
* `s01e24b`

Excluded from the default set because description coverage is too short for default encoding trim:

* `s01e04a`
* `s01e04b`

## Open Questions

* None.

## Requirements

* Create a dedicated config for the plus10 scoring+encoding run.
* Use `generation_provider: "aihubmix"` for all LLM scoring in this task.
* Reuse existing ROI schemas, domain pools, summaries, and already complete scoring outputs.
* Run 14-ROI scoring only for newly added missing episode/ROI pairs.
* Generate a fresh encoding manifest from the expanded split.
* Run Ridge encoding and preserve outputs in a task-specific analysis path.
* Report overall and ROI-level fMRI prediction metrics from the encoding outputs.

## Acceptance Criteria

* [ ] A dedicated config exists for the expanded split.
* [ ] The chosen 10 added episodes pass description, H5 dataset, summary, scoring-missing, and description/H5 length-alignment checks before scoring.
* [ ] Scoring completes or resumes successfully for all 14 ROI x 10 added episode pairs.
* [ ] The manifest row counts match the selected split policy.
* [ ] Encoding completes successfully with `uv run`.
* [ ] Final metrics include `mean_subject_mean_test_pearson`, median test Pearson, selected alpha, retained parcels, test TR count, and ROI-level Pearson values.

## Definition of Done

* Config and generated outputs are present in task-specific paths.
* No existing complete scoring outputs are overwritten unless explicitly approved.
* Relevant verification commands complete, or any failure is explicitly reported.
* Reusable project knowledge is considered for Trellis spec updates.

## Technical Approach

Create a new config under `configs/friends_train_size_sweep_20260617/` or another clearly named Friends experiment config directory. The config should follow existing Friends 14-ROI pilot configs, use the existing full scoring root as `output_root`, add the chosen 10 S01 episodes to the train split, keep S02 validation and S06 test unchanged, then run staged scoring, manifest, and encoding with `uv run`.

To avoid mixing the new encoding result with previous snapshots, copy or preserve the final encoding output under a dedicated analysis directory such as `friends/analysis/train_size_sweep_20260617/plus10_scoring_encoding/`.

## Decision (ADR-lite)

**Context**: The previous task used already-scored episodes only. This task intentionally expands the scoring corpus, which can call the LLM for missing ROI/episode pairs.

**Decision**: Use the confirmed first 10 length-aligned S01 candidates (`s01e15a`, `s01e19a`, `s01e19b`, `s01e20a`, `s01e20b`, `s01e21a`, `s01e21b`, `s01e22a`, `s01e22b`, `s01e23a`) and add them to the train split. Keep S02 as validation and S06 as held-out test.

**Consequences**: The run will be more expensive and slower than manifest+encoding-only tasks because it includes 140 scoring jobs for 14 ROI x 10 episodes.

## Out of Scope

* Regenerating domain pools or schemas.
* Re-scoring already complete episode/ROI pairs.
* Changing encoding model code unless an execution bug blocks the run.
* Adding non-S01 episodes unless explicitly requested.

## Technical Notes

* Current task: `.trellis/tasks/06-22-friends-plus10-scoring-encoding`.
* Existing full scoring root: `friends/full_runs/friends_full_scoring_start_14roi_gemini35_20260612`.
* Existing H5 file: `friends/BN/sub-01/BN_246.h5`.
* Current complete scoring count: 34 episodes across all 14 ROI.
* Eligible-by-existence unscored S01 count: 15 episodes.
* Length-aligned unscored S01 count: 13 episodes.
* Length check method: scoring infers feature rows as `ceil(description_end_s / 1.49)` when `total_trs` is absent; encoding with default trim requires feature coverage through raw TR `h5_trs - 5`.
* `s01e04a`: description exists, H5 dataset `ses-002_task-s01e04a` has shape `(503, 246)`, summary and summary metadata exist, and all 14 ROI scoring outputs are missing; however `description_end_s=672`, inferred feature TRs = `452`, while default encoding needs coverage through TR `498`, so it is excluded.
* `s01e04b`: description exists, H5 dataset `ses-002_task-s01e04b` has shape `(503, 246)`, summary and summary metadata exist, and all 14 ROI scoring outputs are missing; however `description_end_s=453`, inferred feature TRs = `305`, while default encoding needs coverage through TR `498`, so it is excluded.
* Length-aligned checked candidates:
  * `s01e15a`: inferred feature TRs `473`, H5 TRs `477`, default needed end `472`.
  * `s01e19a`: inferred feature TRs `460`, H5 TRs `460`, default needed end `455`.
  * `s01e19b`: inferred feature TRs `460`, H5 TRs `460`, default needed end `455`.
  * `s01e20a`: inferred feature TRs `460`, H5 TRs `460`, default needed end `455`.
  * `s01e20b`: inferred feature TRs `460`, H5 TRs `460`, default needed end `455`.
  * `s01e21a`: inferred feature TRs `477`, H5 TRs `477`, default needed end `472`.
  * `s01e21b`: inferred feature TRs `477`, H5 TRs `477`, default needed end `472`.
  * `s01e22a`: inferred feature TRs `474`, H5 TRs `474`, default needed end `469`.
  * `s01e22b`: inferred feature TRs `474`, H5 TRs `474`, default needed end `469`.
  * `s01e23a`: inferred feature TRs `462`, H5 TRs `462`, default needed end `457`.
  * `s01e23b`: inferred feature TRs `462`, H5 TRs `462`, default needed end `457`.
  * `s01e24a`: inferred feature TRs `515`, H5 TRs `515`, default needed end `510`.
  * `s01e24b`: inferred feature TRs `515`, H5 TRs `515`, default needed end `510`.
