# Friends Next10 Round2 Scoring and Encoding

## Goal

Run 14-ROI scoring and encoding for 10 newly selected Friends episode segments
that satisfy the existing description/H5/TR coverage requirements, expanding
the train split from 45 to 55 episode segments while keeping validation and test
splits fixed.

## What I Already Know

* Current completed config:
  `configs/friends_train_size_sweep_20260622_next10/next10_scoring_encoding.json`.
* Current output root:
  `friends/full_runs/friends_full_scoring_start_14roi_gemini35_20260612`.
* Current split counts are train 45, validation 5, test 4.
* The 14 ROI list stays unchanged:
  `DLPFC`, `VMPFC`, `OFC`, `ACC`, `PCC`, `Precuneus`, `IPL`, `SMG`, `AG`,
  `TPJ`, `pSTS`, `FFA`, `Insula`, `Temporal_Pole`.
* Scoring provider/model stay `aihubmix` / `gemini-3.5-flash`.
* Encoding trim stays `fmri_trim_start_tr=5` and `fmri_trim_end_tr=5`.
* The user explicitly approved running scoring and encoding with concurrency 6.
* Current working tree has one unrelated dirty file:
  `friends/analysis/train_size_sweep_20260622_fresh/train_size_comparison_friends_vs_tribe_plus45.png`.

## Selected Episodes

These 10 episodes were chosen by the conservative strategy: skip `s02e01b` to
`s02e05b` because their paired `a` halves are validation episodes, then take the
next eligible unused segments with valid H5/TR coverage and existing summaries.

| episode_id | h5_dataset | inferred_feature_trs | h5_trs | needed_end | margin |
|---|---|---:|---:|---:|---:|
| `s02e10a` | `ses-013_task-s02e10a` | 479 | 479 | 474 | 5 |
| `s02e10b` | `ses-013_task-s02e10b` | 479 | 479 | 474 | 5 |
| `s02e11a` | `ses-014_task-s02e11a` | 488 | 488 | 483 | 5 |
| `s02e12a` | `ses-014_task-s02e12a` | 488 | 488 | 483 | 5 |
| `s02e12b` | `ses-014_task-s02e12b` | 488 | 488 | 483 | 5 |
| `s02e13a` | `ses-014_task-s02e13a` | 488 | 488 | 483 | 5 |
| `s02e13b` | `ses-014_task-s02e13b` | 488 | 488 | 483 | 5 |
| `s02e14a` | `ses-015_task-s02e14a` | 474 | 474 | 469 | 5 |
| `s02e14b` | `ses-015_task-s02e14b` | 474 | 474 | 469 | 5 |
| `s02e15a` | `ses-015_task-s02e15a` | 466 | 466 | 461 | 5 |

## Requirements

* Generate a dedicated config for this round, based on the current 45-train
  config, with the selected 10 episodes appended to the train split.
* Keep validation episodes unchanged:
  `s02e01a`, `s02e02a`, `s02e03a`, `s02e04a`, `s02e05a`.
* Keep test episodes unchanged:
  `s06e01a`, `s06e01b`, `s06e03a`, `s06e03b`.
* Reuse existing summaries, domain pools, ROI schemas, H5 file, atlas labels,
  lags, alphas, and trim settings.
* Run 14-ROI scoring for the selected 10 episodes with scoring concurrency 6.
* Run manifest generation and encoding after scoring completes.
* Do not modify unrelated dirty files.

## Acceptance Criteria

* [ ] New config contains 55 train, 5 validation, and 4 test episode rows.
* [ ] Selected 10 episodes are all in train and all have the expected H5
  dataset names.
* [ ] Scoring metadata exists for all 10 episodes across all 14 ROIs.
* [ ] Scoring metadata for the 140 new ROI/episode pairs records provider
  `aihubmix`, model `gemini-3.5-flash`, and zero residual warning batches.
* [ ] `tr_features.jsonl` row counts match expected TR counts for each selected
  episode.
* [ ] Manifest contains 64 total samples with split counts 55/5/4.
* [ ] Encoding completes and writes updated group and subject summaries.
* [ ] Validation commands report any blocker or pass.

## Definition of Done

* Config is generated from the prior config with minimal changes.
* Scoring is run with `--scoring-workers 6`.
* Manifest and encoding are run after scoring.
* Output validation checks pass for the new 140 scoring pairs and updated
  encoding outputs.
* Task-specific changes are committed only after user confirmation of a commit
  plan.

## Technical Approach

Use the existing concurrent runner:

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config <round2_config.json> \
  --stage scoring \
  --scoring-workers 6

uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config <round2_config.json> \
  --stage manifest

uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config <round2_config.json> \
  --stage encoding
```

If scoring leaves failed batches, run the existing failed-batch retry mode
before manifest/encoding.

## Out of Scope

* Regenerating summaries, domain pools, or ROI schemas.
* Changing validation/test split policy.
* Including `s02e01b` to `s02e05b` in this round.
* Changing model/provider, lags, alphas, or fMRI trim.
* Updating train-size comparison plots unless requested after encoding.

## Technical Notes

* Candidate scan used `brain_region_pipeline.scoring.description_io`.
* H5 source is `friends/BN/sub-01/BN_246.h5`.
* The selected 10 episodes all have existing summary and summary metadata files
  under the current output root.
* The selected 10 episodes currently have 0 clean scoring metadata files across
  the 14 ROI set, so they require fresh scoring.
