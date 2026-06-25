# Remove CLI-shaped schema design interface

## Goal

Move the schema-design stage runner interface away from CLI-shaped `args`
objects so maintained callers pass explicit typed input objects. This is the
remaining schema-design slice of the broader "remove CLI-shaped stage runner
interface" cleanup after summary/scoring was migrated.

The work should make `make-domain-pool` and `make-region-schema` deep enough
for both CLI and pilot callers: CLI parsing remains in `brain_region_pipeline/cli.py`,
while `brain_region_pipeline/schema_design/runner.py` receives typed inputs.

## Confirmed Facts

- Backend guidelines state that `cli.py` may receive `argparse.Namespace`, but
  maintained stage runner modules should expose typed input objects rather than
  accepting CLI-shaped `Namespace` directly
  (`.trellis/spec/backend/directory-structure.md`).
- `make_domain_pool(args, cfg, deps)` currently reads `args.output_file` and
  `args.atlas_labels` from an untyped object
  (`brain_region_pipeline/schema_design/runner.py:25`).
- `make_region_schema(args, cfg, deps)` currently reads `args.output_file`,
  `args.atlas_labels`, `args.domain_pool`, `args.roi_definitions`, and
  `args.roi_id` from an untyped object
  (`brain_region_pipeline/schema_design/runner.py:60`).
- The concurrent Friends pilot constructs `Namespace(...)` only to call these
  schema-design runners (`brain_region_pipeline/pilot/concurrent.py:276`,
  `brain_region_pipeline/pilot/concurrent.py:329`).
- The staged pilot runner has the same schema-design `Namespace(...)` adapter
  shape (`brain_region_pipeline/pilot/runner.py:377`,
  `brain_region_pipeline/pilot/runner.py:413`).
- CLI dispatch still calls the schema-design runners with parsed CLI args
  (`brain_region_pipeline/cli.py:378`, `brain_region_pipeline/cli.py:381`).
- Summary and scoring already use typed input objects, providing the local
  pattern for this change (`brain_region_pipeline/scoring/runner.py:36` and
  `brain_region_pipeline/scoring/summary_generator.py`).
- `DomainPoolConfig.target_region` and `RegionSchemaConfig.target_region` are
  already the stage configuration contract for the target ROI
  (`brain_region_pipeline/core/config.py:68`).

## Requirements

- Add typed schema-design input objects for the two maintained stage runners:
  `DomainPoolInput` and `RegionSchemaInput`.
- Keep CLI parsing and `argparse.Namespace` handling inside
  `brain_region_pipeline/cli.py`; CLI may build typed inputs from parsed args.
- Update pilot callers to construct typed inputs directly instead of creating
  `Namespace(...)` objects for schema-design stages.
- Preserve all existing make-domain-pool and make-region-schema behavior,
  output contracts, validation, logging, dependency injection, provider/model
  configuration, and fixed ROI selection-rule behavior.
- Preserve the paired `roi_definitions` / `roi_id` contract for region schemas:
  both absent is allowed, both present applies fixed ROI selection rules, and
  only one present raises the existing validation error.
- Keep target-region ownership in `DomainPoolConfig` and `RegionSchemaConfig`.
  The new typed input objects should not duplicate `target_region` unless a
  runner actually needs a separate input value.
- Keep the change scoped to schema-design runners only. Do not migrate
  `fit_roi_encoding_from_manifest` in this task.
- Keep `brain_region_pipeline/cli.py` as an adapter/dispatch layer only; do not
  move schema generation logic into the CLI.
- Do not reintroduce deleted Friends pilot scripts or add compatibility wrapper
  modules for removed run-specific scripts.

## Acceptance Criteria

- [ ] `brain_region_pipeline/schema_design/runner.py` exposes typed input
      dataclasses for domain-pool and region-schema runner inputs.
- [ ] `make_domain_pool(...)` and `make_region_schema(...)` accept typed input
      objects, not CLI-shaped `args`.
- [ ] `brain_region_pipeline/cli.py` builds typed inputs for
      `make-domain-pool` and `make-region-schema` before dispatch.
- [ ] `brain_region_pipeline/pilot/concurrent.py` no longer imports or
      constructs `argparse.Namespace` for schema-design stages.
- [ ] `brain_region_pipeline/pilot/runner.py` no longer imports or constructs
      `argparse.Namespace` for schema-design stages; encoding may remain
      CLI-shaped and is explicitly out of scope.
- [ ] Existing CLI tests for `make-domain-pool` and `make-region-schema`
      continue to pass.
- [ ] Staged pilot and concurrent pilot regression tests prove schema-design
      stage calls receive typed input objects with correct artifact paths and
      fixed-ROI inputs.
- [ ] A repository search shows remaining `Namespace(...)` usage in
      `brain_region_pipeline/pilot/*` is limited to the encoding stage, or any
      other explicitly out-of-scope location.
- [ ] Standard backend validation passes:
      `uv run python -m unittest discover -s tests -p 'test_*.py'`,
      `uv run python -m compileall brain_region_pipeline tests scripts`,
      `uv run python -m brain_region_pipeline`,
      `uv run python -m brain_region_pipeline make-domain-pool --help`,
      `uv run python -m brain_region_pipeline make-region-schema --help`,
      and `git diff --check`.

## Notes

- Out of scope: converting `fit_roi_encoding_from_manifest(args, cfg)` to a
  typed input interface. That should be a separate task because encoding has
  different contracts around manifests, H5 datasets, ROI schema mappings, and
  Ridge outputs.
- Out of scope: changing serialized domain-pool or region-schema JSON
  contracts.
- Out of scope: changing CLI command names, command flags, provider/model
  defaults, or pilot config schema.
