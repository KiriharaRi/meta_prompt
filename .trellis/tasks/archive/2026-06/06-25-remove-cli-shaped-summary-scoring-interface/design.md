# Design

## Architecture

This task deepens the summary and scoring stage modules by making their module
interface typed. The CLI remains an adapter at the outer seam, while pilot and
script callers use the same typed interface as tests.

```text
Before

CLI / pilot / scripts
  -> forge argparse.Namespace
  -> summary/scoring runner reads ad hoc args attributes

After

CLI adapter
  -> SummaryDescriptionsInput / ScoreDescriptionsInput
pilot / scripts
  -> SummaryDescriptionsInput / ScoreDescriptionsInput
summary/scoring runner
  -> typed input + stage config
```

## Module Boundaries

- `brain_region_pipeline/scoring/summary_generator.py`
  - owns `SummaryDescriptionsInput`
  - owns summary generation behavior
  - no longer depends on CLI-shaped input
- `brain_region_pipeline/scoring/runner.py`
  - owns `ScoreDescriptionsInput`
  - owns score-descriptions orchestration, checkpointing, GT alignment, TR output
  - no longer depends on CLI-shaped input
- `brain_region_pipeline/cli.py`
  - remains the adapter that converts parsed CLI args into typed inputs
- `brain_region_pipeline/pilot/concurrent.py`
  - constructs typed inputs from `PilotConfig`, `RoiDefinition`, and
    `PilotEpisode`
- `brain_region_pipeline/pilot/runner.py`
  - uses typed inputs for the serial pilot summary/scoring paths
- `scripts/run_friends_14roi_s01s02_vertex_pilot.py` and
  `scripts/run_friends_7roi_vertex_pilot.py`
  - have been deleted by the user and are not migration targets

## Data Contracts

### SummaryDescriptionsInput

`SummaryDescriptionsInput` is a small dataclass with `Path` fields:

- `descriptions`
- `output_file`

### ScoreDescriptionsInput

`ScoreDescriptionsInput` is a field-equivalent typed version of the existing
scoring CLI-shaped args. Path-like fields become `Path`:

- `descriptions`
- `region_schema`
- `output_dir`
- `summary_file`
- `gt_dir`

All existing scalar fields keep their current meaning.

## Compatibility

No general `Namespace` compatibility path will be retained in the stage runner
modules. Compatibility lives at CLI/script adapter sites by constructing typed
inputs before calling the runner.

Domain-pool, region-schema, and encoding stage runner interfaces are explicitly
unchanged in this task.

## Testing Strategy

- Add behavior-level tests that capture the object passed from
  `ConcurrentPilotStages` into summary/scoring runner functions and assert
  `isinstance(..., SummaryDescriptionsInput | ScoreDescriptionsInput)`.
- Update existing scoring dispatch tests that inspect artifact paths to read
  typed input fields instead of `Namespace` attributes.
- Keep CLI tests focused on command behavior, not runner internals.
- Use a temporary source-level guard only during migration if useful; remove it
  before final validation.
- Run the existing full suite plus a temporary fake-data smoke through
  `scripts/run_friends_14roi_concurrent_pilot.py --stage all`.

## Risks

- Scoring has many input fields. Mitigation: migrate field-equivalently first
  and avoid semantic reshaping.
- Checkpoint helpers currently accept `args`. Mitigation: update them to use the
  typed input object if needed, preserving serialized signatures.
- Some older scripts may import runner functions directly. Mitigation: search
  all remaining Python callers and migrate summary/scoring calls together.
