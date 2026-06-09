# Complete Remaining Segment Scoring

## Goal

Score the remaining Fallen movie description segments with the same vmPFC region schema and scoring configuration used for the first 800 segments, merge the existing and new segment-level scores into one full result file, and recompute no-lag plus lagged correlations against the GT agitation signal.

## What I Already Know

- Existing run directory: `fallen/demo/vmpfc_gemini3_flash_800_20260514/`.
- Existing first-800 scores: `scoring_first_schema_800/segment_region_scores.jsonl`.
- Existing first-800 GT means: `scoring_first_schema_800/segment_gt_means.jsonl`.
- Full description source: `fallen/demo/refined_description_for_scoring.md`.
- First-800 description source: `fallen/demo/refined_description_20calls_800segments.md`.
- Full description file has 2078 parsed segments from 0.0s to 6070.0s.
- Existing first-800 scores cover segments 0-799, ending at 2289.0s.
- Remaining work starts at original segment index 800 and covers 1278 segments.
- Current scoring config in metadata:
  - model: `gemini-3-flash-preview`
  - schema: `fallen/demo/vmpfc_gemini3_flash_800_20260514/vmpfc_region_schema_draft.json`
  - summary file: `fallen/previous_code/summary.json`
  - scoring batch size: 40
  - local buffer size: 10
  - TR: 1.49s
  - alignment: `overlap_weighted`
  - GT directory: `fallen/gt`
  - GT time column: `视频时间(s)`
  - GT emotion column: `情绪值`

## Requirements

- Reuse the original first-800 score rows without re-scoring them.
- Score only original segment indexes 800-2077.
- Preserve original batch boundaries. Because 800 is divisible by the configured batch size 40, the remaining scoring can start at batch 20 without changing prompt context semantics.
- Include the same Story Context summaries and Local Buffer behavior as the current batch scorer.
- Write remaining-score outputs separately for traceability.
- Merge existing first-800 and newly scored remaining rows into one full 2078-row `segment_region_scores.jsonl`.
- Recompute full 2078-row `segment_gt_means.jsonl`.
- Recompute correlations:
  - no-lag Pearson/Spearman by dimension
  - lagged Pearson/Spearman using -60s to +60s in 5s steps
  - same lag convention as previous analysis: positive lag means feature at time `t` is compared with GT at `t + lag`.

## Acceptance Criteria

- [ ] Remaining score file has 1278 rows.
- [ ] Full merged score file has 2078 rows.
- [ ] Full GT file has 2078 rows.
- [ ] Merged row 799 matches the existing first-800 endpoint ending at 2289.0s.
- [ ] Merged row 800 starts at 2289.0s.
- [ ] Scoring warnings are summarized and persisted if present.
- [ ] No-lag and lagged correlation summaries are written and reported to the user.

## Out of Scope

- Do not redesign the schema.
- Do not re-score the existing first 800 segments unless explicitly requested.
- Do not change production pipeline source code unless an execution blocker requires it.
- Do not commit changes unless the user asks for a commit.

## Technical Notes

- Existing CLI does not expose a resume/start-index argument, so this task can use a small one-off runner script in the shell to call existing package functions with the desired batch range.
- The one-off runner should rely on existing package APIs: `load_description_segments`, `load_region_schema`, `_score_segment_batch`, `build_batch_score_schema`, `average_gt_to_segments`, `align_scores_to_trs`, and JSONL writers.
- Generated output files should live under `fallen/demo/vmpfc_gemini3_flash_800_20260514/` so the run remains self-contained.
