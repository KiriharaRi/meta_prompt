# Design: Remove CLI-shaped schema design interface

## Boundary

This task changes the Python runner boundary for schema-design stages. It does
not change the public CLI contract or the serialized domain-pool /
region-schema JSON contracts.

The desired boundary is:

```text
argparse.Namespace
  -> brain_region_pipeline.cli adapter
  -> DomainPoolInput / RegionSchemaInput
  -> brain_region_pipeline.schema_design.runner
```

Pilot callers should skip the CLI-shaped layer and construct typed input
objects directly:

```text
PilotConfig + PilotArtifacts + RoiDefinition
  -> DomainPoolInput / RegionSchemaInput
  -> brain_region_pipeline.schema_design.runner
```

## Contracts

### DomainPoolInput

Owned by `brain_region_pipeline/schema_design/runner.py`.

Fields:

- `atlas_labels: Path`
- `output_file: Path`

The runner should continue to use `DomainPoolConfig` for generation settings:
provider, model, target region, and proposal runs. The typed input object should
not duplicate `target_region` because the runner does not need a second source
for that value.

### RegionSchemaInput

Owned by `brain_region_pipeline/schema_design/runner.py`.

Fields:

- `atlas_labels: Path`
- `domain_pool: Path`
- `output_file: Path`
- `roi_definitions: Path | None = None`
- `roi_id: str | None = None`

The paired fixed-ROI fields keep the existing behavior:

- both absent: generate schema without fixed ROI selection rules;
- both present: load ROI definitions and apply the selected ROI rules;
- exactly one present: raise `ValueError("--roi-definitions and --roi-id must be provided together.")`.

The runner should compare the confirmed domain pool target region against
`cfg.target_region`, preserving current behavior and error text.

### Target Region Ownership

Target region remains owned by `DomainPoolConfig` and `RegionSchemaConfig`.
This avoids an avoidable two-source consistency problem where `inputs.target_region`
could disagree with `cfg.target_region`.

CLI and pilot adapters should still pass the ROI value into the config builders
exactly as they do today. Tests should verify adapter behavior through the typed
input fields the runner actually consumes, plus existing CLI/schema behavior
tests that assert the configured target region is honored.

## Call Sites

### CLI

`brain_region_pipeline/cli.py` remains the only intended `argparse.Namespace`
consumer for these stages. Add helpers parallel to the existing summary/scoring
helpers:

- `_build_domain_pool_input(args: argparse.Namespace) -> DomainPoolInput`
- `_build_region_schema_input(args: argparse.Namespace) -> RegionSchemaInput`

Then dispatch:

```python
make_domain_pool(_build_domain_pool_input(args), _build_domain_pool_config(args), deps=deps)
make_region_schema(_build_region_schema_input(args), _build_region_schema_config(args), deps=deps)
```

### Concurrent Pilot

`brain_region_pipeline/pilot/concurrent.py` should import the new typed input
objects and construct them in `run_domain_pool_job(...)` and `run_schema_job(...)`.
After this change, the module should not need `from argparse import Namespace`
unless the out-of-scope encoding call still requires it. If encoding remains in
the same file and still uses `Namespace`, keep the import but make the remaining
usage visibly tied to encoding.

### Staged Pilot Runner

`brain_region_pipeline/pilot/runner.py` should do the same in `_run_domain_pools`
and `_run_schemas`. The encoding stage may continue to construct a `Namespace`
for `fit_roi_encoding_from_manifest(...)` in this task.

## Testing Strategy

- Keep existing CLI tests that run `make-domain-pool` and `make-region-schema`
  through `main(...)`; they should still verify the public CLI behavior.
- Add direct runner or pilot tests that inspect patched call arguments and
  assert they are `DomainPoolInput` / `RegionSchemaInput`.
- Extend existing concurrent pilot tests next to the summary/scoring typed input
  assertions so the architecture regression is local and easy to review.
- Add a staged pilot assertion for `_run_domain_pools(...)` and `_run_schemas(...)`
  so the non-concurrent orchestration path cannot keep a hidden CLI-shaped
  schema-design call.
- Use an `rg` check for `Namespace(` to confirm only accepted remaining uses
  remain.

## Trade-offs

This design does not create a separate shared adapter module. The conversion
logic is short and caller-specific: CLI converts user flags, pilots convert
artifact graph paths. A shared factory would hide the two different boundaries
and add indirection without removing real complexity.

This design does not add compatibility overloads that accept both `args` and
typed inputs. A compatibility path would preserve the shallow interface this
task is meant to remove, and there are only a few maintained call sites.

## Rollback

The change is local to runner signatures and call sites. Rollback is a normal
git revert of the task commit. No generated artifacts or schema files need
migration because output contracts are unchanged.
