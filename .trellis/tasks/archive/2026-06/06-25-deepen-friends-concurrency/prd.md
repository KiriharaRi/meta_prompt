# Deepen Friends Concurrency Module

## Goal

Deepen the Friends concurrent pilot workflow by moving reusable concurrency and
general stage-job behavior out of run-specific scripts and behind a maintained
`brain_region_pipeline.pilot` module.

This is the second architecture optimization round after `PilotArtifacts`.
The first round intentionally did not solve concurrent script private imports or
the CLI-shaped downstream stage runner interface. This round chooses only the
first follow-up: **Move Friends concurrency behind a deeper module**. The
separate follow-up **Remove CLI-shaped stage runner interface** remains out of
scope.

## What I already know

- The prior architecture HTML report ranked "Deepen the Friends pilot artifact
  graph" first and "Move Friends concurrency behind a deeper module" next.
- The first round introduced `brain_region_pipeline/pilot/artifacts.py`, so
  Friends pilot artifact paths and generated encoding sidecars now have a
  maintained module.
- The first-round PRD explicitly left both concurrent script migration and
  `argparse.Namespace` stage-runner replacement for separate follow-up tasks.
- `scripts/run_friends_14roi_concurrent_pilot.py` is the general config-driven
  concurrent Friends runner.
- The 14-ROI script currently imports private helpers from
  `scripts/run_friends_7roi_vertex_pilot.py`, including `_run_parallel`,
  `_run_domain_pool_jobs`, `_run_schema_jobs`, `_run_scoring_jobs`,
  `_retry_failed_batches`, and `_validate_full_outputs`.
- The 7-ROI script mixes reusable concurrent pilot behavior with run-specific
  Vertex/smoke/copy-summary behavior.
- Existing smoke tests already care about single-stage dispatch not falling
  through to downstream stages.

## Scope Decision

**Chosen scope: Option B, General concurrent pilot module.**

Introduce a maintained concurrency module under `brain_region_pipeline/pilot/`
that owns reusable concurrent job execution and general Friends pilot stage-job
behavior. Update the 14-ROI script to depend on that maintained module instead
of importing private helpers from the 7-ROI script.

This task may touch the 7-ROI script only enough to keep its existing behavior
working when general helpers move. Its run-specific smoke path, summary-copying,
Vertex environment checks, and default config remain script concerns.

## Requirements

- Introduce a deeper maintained pilot concurrency module with a small interface
  and high locality.
- Move reusable concurrent behavior behind that module:
  - parallel job execution and aggregate failure reporting;
  - domain-pool jobs;
  - schema jobs;
  - scoring jobs;
  - failed-batch retry orchestration;
  - full-output validation;
  - manifest plus encoding refresh after scoring or retry.
- Reuse `PilotArtifacts` for pilot artifact paths where this module needs
  summary, schema, scoring, manifest, or encoding paths.
- Remove the 14-ROI script's dependency on private functions from the 7-ROI
  script.
- Preserve existing 14-ROI behavior for dry-run, single-stage dispatch,
  full-run dispatch, failed-batch retry, worker validation, manifest writing,
  encoding, and output validation.
- Preserve existing 7-ROI script behavior if reusable helpers are moved out of
  that script.
- Keep downstream stage runner calls CLI-shaped for this task. The new module
  may still internally build `argparse.Namespace` objects to call existing
  summary, schema, scoring, and encoding runners.
- Keep run-specific concerns in scripts when they are not general pilot
  concurrency behavior.

## Acceptance Criteria

- [ ] `scripts/run_friends_14roi_concurrent_pilot.py` no longer imports private
      stage/concurrency helpers from `scripts/run_friends_7roi_vertex_pilot.py`.
- [ ] A maintained module under `brain_region_pipeline/pilot/` owns reusable
      concurrent job execution and general pilot stage jobs.
- [ ] General stage-job code uses `PilotArtifacts` rather than reintroducing
      duplicated path-layout knowledge.
- [ ] Existing 14-ROI concurrent script behavior remains compatible.
- [ ] Existing 7-ROI script behavior remains compatible where shared helpers are
      moved.
- [ ] New or updated tests cover the extracted module's public interface.
- [ ] Tests confirm single-stage dispatch does not fall through to downstream
      stages.
- [ ] Tests or import checks confirm the 14-ROI script does not import
      `run_friends_7roi_vertex_pilot`.
- [ ] No downstream stage runner interface migration is included in this task.
- [ ] Standard backend checks pass:
      `uv run python -m unittest discover -s tests -p 'test_*.py'` and
      `uv run python -m compileall brain_region_pipeline tests scripts`.

## Definition of Done

- Tests added or updated where behavior is moved.
- Standard backend validation passes.
- `.trellis/spec/` is updated if this task establishes a new maintained module
  responsibility.
- Work commit is created before finish-work.

## Technical Approach

Create a maintained module such as `brain_region_pipeline/pilot/concurrent.py`.
Its external interface should be small enough that script adapters do not need
to know the implementation details of ThreadPool execution, retry scanning,
stage-job construction, path validation, or refresh sequencing.

The module should use `PilotConfig`, `PilotEpisode`, `RoiDefinition`,
`PipelineDependencies`, and `PilotArtifacts`. It can keep internal helper seams
for retry mutation locks and validation, but callers should not have to import
many private functions to run common concurrent stage behavior.

`scripts/run_friends_14roi_concurrent_pilot.py` should remain a script adapter:
parse options, load config, validate static inputs, print dry-run details, and
dispatch to the maintained concurrency module. It should not import from
`scripts/run_friends_7roi_vertex_pilot.py`.

`scripts/run_friends_7roi_vertex_pilot.py` can keep run-specific behavior in
place while importing shared concurrent helpers from the maintained module if
needed. Do not redesign its smoke workflow or Vertex-specific environment
checks in this task.

## Decision (ADR-lite)

**Context**: The architecture report found that Friends concurrent scripts are
shallow adapters: understanding the general 14-ROI runner requires jumping into
a separate run-specific 7-ROI script because general concurrency helpers live
behind the wrong seam. The deletion test says these helpers are earning their
keep, but their module locality is poor.

**Decision**: Move general Friends concurrent pilot behavior into a maintained
`brain_region_pipeline.pilot` module and update the 14-ROI script to depend on
that module. Keep CLI-shaped downstream runner calls as an internal detail for
now.

**Consequences**: This improves locality for concurrent stage behavior and gives
future scripts more leverage from one maintained module. Some seam leakage
remains by design: stage runners still accept `argparse.Namespace` inputs. That
is a separate optimization candidate, not part of this round.

## Out of Scope

- Removing or replacing downstream runner `args`/`Namespace` interfaces.
- Redesigning the serial `run-multi-roi-pilot` CLI.
- Changing pilot config JSON shape.
- Changing serialized summary, domain-pool, schema, scoring, manifest, or
  encoding output formats.
- Running live LLM scoring, schema generation, domain-pool generation, or
  encoding jobs as part of tests.
- Migrating every Friends concurrent script in one sweep.
- Redesigning 7-ROI run-specific smoke, summary-copy, default-config, or Vertex
  environment behavior.
- Migrating run-specific cross-output-root artifact copying unless the scope is
  explicitly expanded.

## Technical Notes

- Existing HTML report:
  `/private/var/folders/6w/klcglgl936g60n8fb40h18500000gn/T/architecture-review-20260625-153401.html`
- Existing report candidate:
  "Move Friends concurrency behind a deeper module" describes scripts doing
  implementation work and importing private helpers across seams.
- Files inspected:
  - `scripts/run_friends_14roi_concurrent_pilot.py`
  - `scripts/run_friends_7roi_vertex_pilot.py`
  - `tests/test_friends_14roi_concurrent_script.py`
  - `brain_region_pipeline/pilot/artifacts.py`
- Relevant specs:
  - `.trellis/spec/backend/directory-structure.md`
  - `.trellis/spec/backend/quality-guidelines.md`
- No project `CONTEXT.md` or `docs/adr/` files were found during this planning
  pass, so there is no known domain glossary or ADR conflict to preserve.

## Future Follow-Up Candidates

- **Remove CLI-shaped stage runner interface**: replace downstream runner
  `argparse.Namespace` inputs with deeper typed inputs after concurrency has a
  stable module seam.
- **Migrate older Friends concurrent scripts**: after the maintained concurrency
  module proves its shape through the 14-ROI path, evaluate whether older
  one-off scripts should become thinner adapters too.
