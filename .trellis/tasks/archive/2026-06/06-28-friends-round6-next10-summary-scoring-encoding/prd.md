# Friends round6 next10 summary scoring encoding

## Goal

Extend the current Friends 14-ROI experiment with 10 additional train episode
segments, then run the required `summary -> scoring -> manifest -> encoding`
workflow. The round must continue from the current round4/round5 experiment
line without reusing already-selected episodes, and must skip `s03e06a` because
its refined description timeline is abnormal.

## Background

- The current repository is clean on `main`.
- Current confirmed recent configs are:
  - `configs/friends_train_size_sweep_20260627_75swap/75_from65_round4_add10.json`
  - `configs/friends_train_size_sweep_20260627_75swap/75_from65_round5_add10.json`
- The new candidate set must exclude the union of the episode rows in those two
  configs.
- The previous validation/test policy remains unchanged:
  - validation: `s02e01a`, `s02e02a`, `s02e03a`, `s02e04a`, `s02e05a`
  - held-out test: `s06e01a`, `s06e01b`, `s06e03a`, `s06e03b`
- Candidate eligibility follows the durable Friends preflight rule:
  `inferred_feature_trs >= h5_trs - 5`, using TR seconds `1.49` and the current
  default 5/5 fMRI trim.
- `s03e06a` technically passes the lower-bound coverage rule, but its refined
  description infers `872` feature TRs for a `470` TR H5 dataset. The user
  confirmed this description is problematic and should be skipped.

## Selected Episodes

Use these 10 new train episodes:

| episode | h5_dataset | inferred_feature_trs | h5_trs | margin | description segments |
| --- | --- | ---: | ---: | ---: | ---: |
| `s03e04b` | `ses-020_task-s03e04b` | 473 | 473 | 5 | 274 |
| `s03e05a` | `ses-020_task-s03e05a` | 484 | 484 | 5 | 286 |
| `s03e05b` | `ses-020_task-s03e05b` | 484 | 484 | 5 | 299 |
| `s03e06b` | `ses-020_task-s03e06b` | 469 | 470 | 4 | 283 |
| `s03e07a` | `ses-021_task-s03e07a` | 467 | 467 | 5 | 263 |
| `s03e07b` | `ses-021_task-s03e07b` | 467 | 467 | 5 | 268 |
| `s03e08a` | `ses-021_task-s03e08a` | 460 | 460 | 5 | 289 |
| `s03e09a` | `ses-021_task-s03e09a` | 493 | 493 | 5 | 284 |
| `s03e09b` | `ses-021_task-s03e09b` | 493 | 493 | 5 | 248 |
| `s03e10a` | `ses-022_task-s03e10a` | 451 | 451 | 5 | 234 |

## Requirements

- Create a round-specific config rather than mutating any existing round4 or
  round5 config.
- The config must add the selected 10 episodes to the train split and preserve
  provider/model, ROI definitions, H5 source, atlas labels, lags, alphas,
  validation split, and held-out test split from the round5 config unless a
  validation check proves a change is required.
- Generate and preserve a preflight report that records candidate exclusion,
  selected episode evidence, H5 dataset shape, inferred TRs, and the skipped
  `s03e06a` abnormality.
- Run summary generation for selected episodes because they do not currently
  have full-run summary outputs.
- Run 14-ROI scoring for the selected 10 episodes with `--scoring-workers 6`
  and resume existing outputs rather than deleting successful results.
- Do not run encoding until the selected 10 episodes have complete summary and
  scoring outputs for every configured ROI.
- Run manifest and encoding using a dedicated analysis output snapshot so the
  latest confirmed encoding output is not accidentally overwritten.
- Report `s03e06a` content evidence to the user so they can inspect why the
  description is abnormal.

## Acceptance Criteria

- [ ] A new round6 config exists and dry-run validates.
- [ ] A preflight report exists with selected candidates and skipped
      `s03e06a` evidence.
- [ ] Summary outputs exist for all 10 selected episodes:
      `summary.json` and `summary_metadata.json`.
- [ ] Scoring outputs exist for every selected episode across all 14 ROIs:
      `segment_region_scores.jsonl`, `tr_features.jsonl`, and
      `scoring_metadata.json`.
- [ ] Validation confirms selected scoring outputs are complete and have no
      unresolved failed zero-filled batches before encoding.
- [ ] Manifest/encoding completes from the selected train expansion and reports
      primary metrics, selected alpha, retained parcels, and test TR count.
- [ ] Final response includes the selected episode list, output paths,
      validation status, encoding metrics, and `s03e06a` abnormal content
      summary.

## Out of Scope

- Changing validation/test split policy.
- Adding `s03e06a` to train.
- Generating new ROI schemas or domain pools unless existing schema artifacts
  are missing.
- Refactoring pipeline source code unless a real blocking bug is found.
