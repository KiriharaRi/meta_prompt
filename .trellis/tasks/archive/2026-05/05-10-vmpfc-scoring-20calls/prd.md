# Run 20-call vmPFC scoring pilot

## Goal

Run the updated `score-descriptions` workflow on a bounded Fallen pilot subset so the current vmPFC domain-pool/module-prompt scoring behavior can be inspected efficiently before full-movie scoring.

## What I already know

* Use the existing confirmed domain-pool derived module prompt under `fallen/demo/vmpfc_module_prompt.json`.
* Use a copied description subset containing exactly the first 800 parsed segments.
* Keep the original absolute timestamps in that subset so `fallen/gt/*.csv` rows can still align through `gt_aligner`.
* Use `--scoring-batch-size 40`, which makes 800 target segments equal 20 LLM scoring calls.
* Write outputs under `fallen/demo/`.

## Requirements

* Create a description subset file from `fallen/demo/refined_description_for_scoring.md` containing the first 800 parsed segments.
* Verify that the subset spans the expected absolute time range and has non-reset timestamps.
* Run `uv run python -m brain_region_pipeline score-descriptions` with:
  * `--descriptions` set to the subset file.
  * `--module-prompt fallen/demo/vmpfc_module_prompt.json`.
  * `--summary-file fallen/previous_code/summary.json`.
  * `--gt-dir fallen/gt`.
  * `--scoring-batch-size 40`.
  * `--alignment overlap_weighted`.
* Produce a concise analysis of segment/TR score distributions, warnings, and GT-anxiety relationships.

## Acceptance Criteria

* [ ] Scoring output directory exists under `fallen/demo/`.
* [ ] `scoring_metadata.json` reports `n_segments = 800` and `scoring_batch_size = 40`.
* [ ] GT segment means are written and correspond to the same absolute timestamps.
* [ ] Analysis identifies any warnings or zero-filled rows.
* [ ] Analysis summarizes the most relevant vmPFC dimensions for Fallen anxiety.

## Out of Scope

* No source-code changes.
* No prompt regeneration.
* No full-movie scoring beyond the first 800 segments.

## Technical Notes

* Existing CLI entrypoint: `uv run python -m brain_region_pipeline score-descriptions`.
* Existing parser preserves absolute timestamp ranges from the description text.
* The default summary file has batch summaries indexed in 40-segment groups, matching the requested scoring batch size.
