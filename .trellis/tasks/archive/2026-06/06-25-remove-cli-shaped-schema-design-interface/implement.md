# Implementation Plan: Remove CLI-shaped schema design interface

## Checklist

1. Add typed input dataclasses in `brain_region_pipeline/schema_design/runner.py`.
   - Import `dataclass`.
   - Define `DomainPoolInput` and `RegionSchemaInput` near the existing runner
     functions.
   - Keep comments/docstrings focused on the boundary, not trivial field
     descriptions.

2. Update schema-design runners to use typed inputs.
   - Rename the first parameter from `args` to `inputs`.
   - Convert path fields with `Path(...)` only at the runner boundary.
   - Preserve existing validation and error text for paired fixed-ROI fields.
   - Preserve existing logging and dependency injection.

3. Update CLI adapters.
   - Import `DomainPoolInput` and `RegionSchemaInput`.
   - Add `_build_domain_pool_input(...)` and `_build_region_schema_input(...)`.
   - Dispatch typed inputs to `make_domain_pool(...)` and
     `make_region_schema(...)`.
   - Do not move business logic into `cli.py`.

4. Update pilot call sites.
   - Replace schema-design `Namespace(...)` calls in
     `brain_region_pipeline/pilot/concurrent.py`.
   - Replace schema-design `Namespace(...)` calls in
     `brain_region_pipeline/pilot/runner.py`.
   - Leave the encoding `Namespace(...)` calls intact and clearly out of scope.

5. Update tests.
   - Add/extend concurrent pilot tests to assert `DomainPoolInput` and
     `RegionSchemaInput` are passed with expected artifact paths and ROI IDs.
   - Add staged pilot tests or focused patched-call assertions for
     `_run_domain_pools(...)` and `_run_schemas(...)` so both orchestration
     paths are covered.
   - Keep existing CLI behavior tests passing.
   - Add a focused direct runner test only if current CLI/pilot tests do not
     cover the new paired `roi_definitions` / `roi_id` input shape clearly.

6. Search for stale schema-design CLI-shaped usage.
   - `rg -n "Namespace\\(|from argparse import Namespace|argparse\\.Namespace" brain_region_pipeline scripts tests -g '*.py'`
   - Verify remaining pilot `Namespace(...)` calls are encoding-only.

7. Validate.
   - `uv run python -m unittest tests.test_friends_14roi_concurrent_script`
   - `uv run python -m unittest discover -s tests -p 'test_*.py'`
   - `uv run python -m compileall brain_region_pipeline tests scripts`
   - `uv run python -m brain_region_pipeline`
   - `uv run python -m brain_region_pipeline make-domain-pool --help`
   - `uv run python -m brain_region_pipeline make-region-schema --help`
   - `git diff --check`

## Risk Points

- `RegionSchemaInput.roi_definitions` and `roi_id` must remain paired. A
  partial input should fail before loading ROI definitions.
- Target region should remain in `DomainPoolConfig` / `RegionSchemaConfig`
  only. Do not add a second `inputs.target_region` value unless implementation
  reveals a concrete runner need.
- Keep encoding out of scope. `fit_roi_encoding_from_manifest(...)` still uses
  CLI-shaped input and should be migrated in a separate task.

## Review Gate Before Implementation

Do not run `task.py start` or edit product code until the user approves this
plan.
