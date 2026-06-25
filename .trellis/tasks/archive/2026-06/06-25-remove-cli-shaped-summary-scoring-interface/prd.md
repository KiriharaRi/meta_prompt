# Remove CLI-shaped summary scoring interface

## Goal

Deepen the summary and scoring stage runner modules by replacing their
CLI-shaped `argparse.Namespace` interface with typed input objects. CLI modules
and scripts may still parse command-line arguments, but maintained stage runner
modules should expose a typed interface that callers and tests can use directly.

## Background

The previous Friends architecture rounds moved artifact layout into
`brain_region_pipeline.pilot.artifacts` and reusable concurrency into
`brain_region_pipeline.pilot.concurrent`. A temporary fake-data smoke confirmed
that the current 14-ROI concurrent full run can execute the real stage dispatch,
artifact graph, manifest writing, and output validation when model/encoding
edges are faked.

The remaining shallow interface is the CLI-shaped runner seam:

- `brain_region_pipeline.scoring.summary_generator.summarize_descriptions_from_file`
  currently accepts an untyped `args` object and reads `args.descriptions` /
  `args.output_file`.
- `brain_region_pipeline.scoring.runner.score_descriptions_from_file` currently
  accepts an untyped `args` object and reads scoring parameters from attributes.
- `brain_region_pipeline.pilot.concurrent` constructs `Namespace` for summary
  and scoring calls at `concurrent.py:200` and `concurrent.py:370`.
- `brain_region_pipeline.pilot.runner` constructs `Namespace` for summary and
  scoring calls at `runner.py:352` and `runner.py:450`.
- `scripts/run_friends_14roi_s01s02_vertex_pilot.py` and
  `scripts/run_friends_7roi_vertex_pilot.py` have been deleted by the user and
  are not migration targets for this task.
- `brain_region_pipeline.cli` should remain the CLI adapter. Its direct calls
  are currently at `cli.py:347` and `cli.py:350`.

## Requirements

### R1. Typed summary runner input

Add a `SummaryDescriptionsInput` dataclass in
`brain_region_pipeline/scoring/summary_generator.py` with `Path` fields:

- `descriptions`
- `output_file`

`summarize_descriptions_from_file` must accept this typed input, not a
CLI-shaped `Namespace`.

### R2. Typed scoring runner input

Add a `ScoreDescriptionsInput` dataclass in
`brain_region_pipeline/scoring/runner.py` with fields equivalent to the current
scoring `Namespace` surface:

- `descriptions: Path`
- `region_schema: Path`
- `output_dir: Path`
- `model: str`
- `tr_s: float`
- `total_trs: int | None`
- `resume: bool`
- `overwrite: bool`
- `summary_file: Path | None`
- `provider: str`
- `scoring_batch_size: int`
- `local_buffer_size: int`
- `gt_dir: Path | None`
- `gt_file_pattern: str`
- `gt_time_column: str`
- `gt_emotion_column: str`
- `alignment: str`

`score_descriptions_from_file` must accept this typed input, not a
CLI-shaped `Namespace`.

### R3. CLI remains an adapter

`brain_region_pipeline/cli.py` may still receive `argparse.Namespace`, but it
must convert CLI args to `SummaryDescriptionsInput` and `ScoreDescriptionsInput`
before calling the stage runner functions.

### R4. Pilot callers use typed inputs directly

`brain_region_pipeline.pilot.concurrent`, `brain_region_pipeline.pilot.runner`,
and any remaining Friends script callers must construct typed summary/scoring
inputs instead of forging `Namespace` objects for those stage runner calls.

### R5. Scope boundary

This task intentionally does not migrate domain-pool, region-schema, or encoding
stage runner interfaces. Existing `Namespace` usage in those paths may remain.

### R6. Spec update

Add a narrow backend guideline stating that CLI adapters may receive
`argparse.Namespace`, but maintained stage runner modules should expose typed
input objects rather than accepting CLI-shaped `Namespace` directly.

## Acceptance Criteria

- [x] `summarize_descriptions_from_file` accepts `SummaryDescriptionsInput`.
- [x] `score_descriptions_from_file` accepts `ScoreDescriptionsInput`.
- [x] No summary/scoring caller in `brain_region_pipeline.pilot.concurrent`,
  `brain_region_pipeline.pilot.runner`, or remaining Friends scripts constructs
  `argparse.Namespace` solely to call the summary/scoring runner functions.
- [x] `brain_region_pipeline.cli` still supports the existing
  `summarize-descriptions` and `score-descriptions` commands through adapter
  conversion.
- [x] Behavior-level tests verify that concurrent pilot summary/scoring calls
  pass typed inputs.
- [x] Existing CLI and workflow behavior remains compatible for summary and
  scoring commands.
- [x] Backend spec records the typed stage runner interface rule.
- [x] The following validation commands pass:
  - `uv run python -m unittest tests.test_friends_14roi_concurrent_script`
  - `uv run python -m unittest discover -s tests -p 'test_*.py'`
  - `uv run python -m compileall brain_region_pipeline tests scripts`
  - `git diff --check`
- [x] A temporary fake-data smoke verifies the 14ROI concurrent full-run path
  with typed summary/scoring inputs and leaves the working tree clean.

## Out of Scope

- Migrating domain-pool runner `Namespace` usage.
- Migrating region-schema runner `Namespace` usage.
- Migrating encoding runner `Namespace` usage.
- Reworking the scoring domain model, GT parameter grouping, output-policy
  abstraction, checkpoint semantics, or TR inference rules.
- Keeping a general backwards-compatible runner entrypoint that still accepts
  `argparse.Namespace`.

## Open Questions

None. The scope decisions were resolved in the grilling session.
