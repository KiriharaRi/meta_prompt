# Friends additional10 scoring and encoding

## Goal

Extend the current Friends 14-ROI scoring/encoding experiment by selecting 10
more valid train episode segments beyond the confirmed 65-train round3 split,
running real scoring with concurrency 6, then refreshing manifest and encoding
outputs.

## Background

- The current confirmed full-run line is round3:
  `configs/friends_train_size_sweep_20260625_round3/round3_scoring_encoding.json`.
- Round3 kept validation fixed at `s02e01a`, `s02e02a`, `s02e03a`,
  `s02e04a`, and `s02e05a`.
- Round3 kept held-out test fixed at `s06e01a`, `s06e01b`, `s06e03a`, and
  `s06e03b`.
- Round3 ended with `65 train / 5 val / 4 test` and
  `mean_subject_mean_test_pearson = 0.21207336267220675`.
- The next run should add 10 more train episode segments while preserving the
  existing validation and held-out test splits.

## Requirements

- Select exactly 10 additional train episode segments that are not already in
  the round3 train/val/test split.
- Each selected episode must pass all input checks:
  - refined descriptions exist;
  - matching dataset exists in `friends/BN/sub-01/BN_246.h5`;
  - summary output exists for the full-run schema;
  - description-derived feature TR coverage reaches the encoding-required H5
    interval, using the same tolerance policy as recent Friends runs.
- Create a new round-specific config rather than mutating the round3 config.
- Keep provider/model, ROI definitions, scoring schema, H5 file, lags, alphas,
  validation split, and held-out test split consistent with round3 unless a
  validation check proves a change is required.
- Run scoring with `--scoring-workers 6`.
- Poll early scoring frequently until progress is stable and no repeated
  provider or output-integrity failure pattern appears; reduce polling
  frequency after stability is confirmed.
- Do not run encoding until all newly required scoring outputs are complete and
  warning-free.
- Report the selected episode list, output paths, scoring validation status,
  encoding metrics, and any residual risk.

## Acceptance Criteria

- [ ] A preflight report identifies the selected 10 episodes and records H5/TR
      coverage evidence for each.
- [ ] New config validates with dry-run and contains `75 train / 5 val / 4 test`.
- [ ] Scoring is launched with concurrency 6.
- [ ] All newly required 14-ROI scoring outputs for the 10 selected episodes
      contain `segment_region_scores.jsonl`, `tr_features.jsonl`, and
      `scoring_metadata.json`.
- [ ] No selected episode has unresolved failed zero-filled batches before
      encoding starts.
- [ ] Manifest refresh includes every selected episode with all 14 ROI feature
      files.
- [ ] Encoding completes and reports primary metric, median metric, selected
      alpha, retained parcel count, and test TR count.
- [ ] Final report compares the new primary metric against the round3 baseline
      `0.21207336267220675`.

## Out of Scope

- Changing validation or held-out test split policy.
- Generating new ROI schemas or prompt schema definitions.
- Changing provider/model routing or scoring prompt behavior.
- Broad source-code refactors.
