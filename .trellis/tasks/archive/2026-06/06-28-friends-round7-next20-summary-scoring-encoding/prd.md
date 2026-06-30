# Friends round7 next20 summary scoring encoding

## Goal

Extend the current Friends 14-ROI experiment from the confirmed 95-train
round6 state by selecting 20 additional eligible train episodes, then prepare
the `summary -> scoring -> manifest -> encoding` workflow for a 115-train
snapshot. A follow-up user-approved scope change expands the held-out S06 test
set with additional early-season eligible episodes. Later approved follow-ups
add 30 more eligible episodes to the train split for a 145-train snapshot, then
screen 10 more eligible train episodes for a 155-train snapshot.

This task is an experiment execution task. It should preserve the existing
validation/test policy, skip known-bad episode `s03e06a`, and use evidence-based
preflight checks before committing to the next 20 episodes.

## Background

- The latest committed all-scored round6 config is
  `configs/friends_train_size_sweep_20260628_round6/round6_all_scored_95train_encoding.json`.
- That config has 104 total episode rows:
  - train: 95 episodes
  - validation: `s02e01a`, `s02e02a`, `s02e03a`, `s02e04a`, `s02e05a`
  - held-out test: `s06e01a`, `s06e01b`, `s06e03a`, `s06e03b`
- The new round should add 20 train episodes beyond the current 95-train set,
  resulting in 115 train episodes if all selected episodes complete summary and
  scoring validation.
- Follow-up test expansion adds six S06 head episodes to the held-out test set:
  `s06e02a`, `s06e04a`, `s06e05a`, `s06e05b`, `s06e06a`, `s06e06b`.
- Follow-up train expansion adds 30 train episodes after the 115-train state:
  `s03e21a`, `s03e21b`, `s03e22a`, `s03e22b`, `s03e23a`,
  `s03e23b`, `s03e24a`, `s03e24b`, `s03e25a`, `s03e25b`,
  `s04e01a`, `s04e01b`, `s04e02a`, `s04e02b`, `s04e03a`,
  `s04e03b`, `s04e04a`, `s04e04b`, `s04e05a`, `s04e05b`,
  `s04e06a`, `s04e06b`, `s04e07a`, `s04e07b`, `s04e08a`,
  `s04e08b`, `s04e09a`, `s04e09b`, `s04e10a`, `s04e10b`.
- Follow-up train screening after the 145-train state selects 10 more eligible
  train episodes: `s04e11a`, `s04e11b`, `s04e12a`, `s04e12b`,
  `s04e13a`, `s04e13b`, `s04e14a`, `s04e14b`, `s04e15a`,
  `s04e15b`.
- Candidate eligibility must use the durable Friends preflight rule:
  `inferred_feature_trs >= h5_trs - 5`, using TR seconds `1.49` and the current
  default 5/5 fMRI trim.
- `s03e06a` must remain excluded because its refined description timeline was
  already identified as abnormal.
- The provider/model should stay aligned with the current Friends full-run
  setup: `aihubmix` / `gemini-3.5-flash`.
- Current unrelated working-tree changes exist in
  `friends/analysis/train_size_comparison_20260627/`; this task must not
  overwrite or reinterpret those curve files unless the user explicitly folds
  them into this task.

## Requirements

- Create a round-specific config under
  `configs/friends_train_size_sweep_20260628_round7/` rather than mutating any
  round6 config.
- Select exactly 20 candidate train episodes after a full preflight audit.
- Exclude from the candidate pool:
  - every episode already present in the round6 all-scored config,
  - the fixed validation and held-out test episodes,
  - `s03e06a`,
  - episodes missing refined descriptions or H5 datasets,
  - episodes whose inferred feature TR coverage fails the 5-TR trim rule,
  - episodes with existing artifacts that indicate unresolved warning or
    zero-filled failure states.
- Preserve ROI definitions, atlas labels, H5 source, lags, alphas, validation
  split, provider, and model from the round6 config unless a validation check
  proves a change is required. The held-out test split may be expanded only by
  the explicitly approved S06 head episodes listed above.
- For the +30 train follow-up, create a round8 config rather than mutating
  round7 in place. Preserve the expanded S06 test split and fixed validation
  split, so the expected final split is 145 train, 5 validation, and 10 test
  episodes.
- For the +10 train follow-up, create a round9 config rather than mutating
  round8 in place. Preserve the expanded S06 test split and fixed validation
  split, so the expected final split is 155 train, 5 validation, and 10 test
  episodes.
- Generate a deterministic preflight report that records every candidate's
  inclusion/exclusion decision, refined description path, H5 dataset, TR counts,
  segment counts, current summary/scoring status, and skip reason when excluded.
- Run or prepare summary generation for selected episodes that do not already
  have complete `summary.json` and `summary_metadata.json` outputs.
- Run or prepare 14-ROI scoring for the selected 20 episodes using resume
  semantics and `--scoring-workers 6`; do not delete successful outputs.
- Do not run encoding until all 280 selected ROI/episode scoring jobs are
  complete and validation reports no unresolved failed zero-filled batches.
- Run manifest generation and encoding into a dedicated round7 analysis
  snapshot, not into the shared full-run encoding directory except for the
  generated manifest sidecar.
- Report the selected next20 list, excluded notable episodes, output paths,
  validation status, final train size, and encoding metrics.

## Acceptance Criteria

- [ ] A round7 Trellis task records the requirements, design, and execution
      checklist before implementation starts.
- [ ] A candidate preflight JSON/CSV exists under the task directory and
      explains why each considered episode was selected or skipped.
- [ ] A new round7 config exists and validates with the concurrent Friends
      runner dry-run.
- [ ] The selected list contains exactly 20 new train episodes and excludes the
      fixed validation/test episodes plus `s03e06a`.
- [ ] Summary outputs exist for all selected episodes:
      `summary.json` and `summary_metadata.json`.
- [ ] Scoring outputs exist for every selected episode across all 14 ROIs:
      `segment_region_scores.jsonl`, `tr_features.jsonl`, and
      `scoring_metadata.json`.
- [ ] Scoring validation confirms zero unresolved failed zero-filled batches
      before encoding.
- [ ] Manifest validation confirms the expected split shape after S06 test
      expansion: 115 train, 5 validation, and 10 test episodes.
- [ ] Encoding completes into the round7 snapshot and reports primary Pearson
      metrics, selected alpha, retained parcels, and test TR count.
- [ ] For the +30 train follow-up, a round8 preflight/config exists, selected
      episodes pass description/H5 coverage, scoring validates for all 420 new
      ROI/episode pairs, and encoding completes with 145 train, 5 validation,
      and 10 test episodes.
- [ ] For the +10 train follow-up, a round9 preflight/config exists, selected
      episodes pass description/H5 coverage, and both full and targeted configs
      pass dry-run validation before any provider-backed summary/scoring run.
- [ ] Final handoff includes paths to config, preflight, validation reports,
      manifest, encoding snapshot, and metric summary.

## Out of Scope

- Changing validation split policy or adding non-approved test episodes.
- Adding `s03e06a`.
- Refactoring pipeline source code unless a confirmed blocking bug appears.
- Re-running already complete summary/scoring outputs solely to refresh
  timestamps.
- Modifying the existing train-size curve CSV/PDF/PNG files unless the user
  explicitly requests it during this task.
