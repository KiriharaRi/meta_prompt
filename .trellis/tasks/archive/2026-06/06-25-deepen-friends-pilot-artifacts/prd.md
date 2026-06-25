# Deepen Friends Pilot Artifact Graph

## Goal

Deepen the serial Friends `run-multi-roi-pilot` artifact graph so path layout and encoding input artifact generation live behind a small, focused module interface instead of being scattered through `brain_region_pipeline/pilot/runner.py`.

This should improve locality for pilot output layout changes while keeping the first implementation narrow enough to avoid changing downstream stage runner interfaces or concurrent Friends scripts.

## Requirements

- Add a new `brain_region_pipeline/pilot/artifacts.py` module.
- Define a narrow `PilotArtifacts(config)` interface that holds only `PilotConfig`.
- Move pilot artifact graph knowledge behind `PilotArtifacts`, including:
  - summary output path;
  - ROI output directory;
  - domain-pool draft, auto-confirmed, and confirmed paths;
  - region schema path;
  - scoring directory;
  - encoding directory;
  - encoding manifest path;
  - ROI schema mapping path.
- Allow `PilotArtifacts` to generate and write only encoding input artifacts:
  - `roi_encoding_manifest.jsonl`;
  - `roi_schemas.json`.
- Keep stage execution in `pilot/runner.py`.
- Keep downstream runner calls CLI-shaped for this first task; do not replace `argparse.Namespace` calls yet.
- Keep existing private function names in `pilot/runner.py` as thin transitional forwarding functions so existing Friends scripts do not break in this task.
- Update serial pilot code paths to use `PilotArtifacts` internally where practical.
- Add or update focused tests for `PilotArtifacts` path behavior and encoding input artifact generation.

## Acceptance Criteria

- [ ] `PilotArtifacts(config)` exposes the pilot artifact paths currently computed in `pilot/runner.py`.
- [ ] `PilotArtifacts.write_encoding_inputs(rois)` writes the same manifest rows and ROI schema mapping shape as the current `_write_manifest(config, rois)` behavior.
- [ ] Existing private helper names used by Friends scripts remain available from `pilot/runner.py` during this first migration.
- [ ] Serial `run-multi-roi-pilot --stage manifest` behavior remains unchanged for existing tests.
- [ ] No concurrent Friends script migration is included in this task.
- [ ] No downstream stage runner interface migration is included in this task.

## Definition of Done

- Tests added or updated for the new artifact module behavior.
- Relevant existing multi-ROI pilot tests pass.
- A broader test run is attempted if the focused tests pass.
- No generated caches or unrelated files are left dirty.

## Technical Approach

Create `PilotArtifacts` as a small frozen dataclass in `brain_region_pipeline/pilot/artifacts.py`. The module should depend on pilot config data and core IO helpers, but it should not call LLM-backed stages, scoring, or encoding model execution.

`pilot/runner.py` should instantiate `PilotArtifacts(config)` and delegate path lookup plus manifest/schema mapping generation to it. Existing private helpers such as `_summary_path`, `_scoring_dir`, `_manifest_path`, `_roi_schema_mapping_path`, `_write_manifest`, and `_run_encoding` should remain importable for now. Path and manifest helpers should forward to `PilotArtifacts`; `_run_encoding` can stay as stage execution because it calls the encoding runner.

## Decision (ADR-lite)

**Context**: The architecture review found that `pilot/runner.py` mixes artifact graph rules, stage dispatch, CLI-shaped downstream calls, and manifest generation. Deleting the current path helpers would push output layout knowledge back into callers and scripts, so there is real module depth available here.

**Decision**: First deepen only the artifact graph by introducing `PilotArtifacts(config)`. Keep `Namespace` forging and concurrent script private imports out of scope for this task.

**Consequences**: The first change improves locality for artifact layout and manifest generation while preserving existing call sites. Some seam leakage remains by design: concurrent scripts still import private runner helpers, and downstream stage runners still accept `args` objects. Those can be handled in separate follow-up tasks.

## Out of Scope

- Migrating `scripts/run_friends_*pilot.py` to a new public pilot/concurrency module.
- Removing transitional private helper functions from `pilot/runner.py`.
- Replacing downstream runner `args`/`Namespace` interfaces with dataclass inputs.
- Changing serialized manifest, schema mapping, score, summary, or encoding output formats.
- Changing execution behavior for domain-pool, schema, scoring, summary, or Ridge encoding stages.

## Technical Notes

- Existing artifact helpers are in `brain_region_pipeline/pilot/runner.py`.
- Current path and manifest behavior is exercised mainly through `tests/test_brain_region_multi_roi.py`.
- Backend package structure guidance lives in `.trellis/spec/backend/directory-structure.md`.
- Backend quality guidance lives in `.trellis/spec/backend/quality-guidelines.md`.
