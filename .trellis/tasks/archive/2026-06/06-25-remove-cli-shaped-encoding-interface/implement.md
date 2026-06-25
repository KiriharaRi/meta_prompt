# Implementation Plan: Remove CLI-shaped encoding interface

## Checklist

1. Add typed encoding input in `brain_region_pipeline/encoding/runner.py`.
   - Import `dataclass`.
   - Define `RoiEncodingInput` near the runner entrypoint.
   - Keep fields limited to `manifest`, `roi_schemas`, `atlas_labels`, and
     `output_dir`.

2. Update `fit_roi_encoding_from_manifest(...)`.
   - Rename first parameter from `args` to `inputs`.
   - Replace `args.manifest`, `args.roi_schemas`, `args.atlas_labels`, and
     `args.output_dir` with `inputs.*`.
   - Preserve output metadata field names and string values.

3. Update CLI adapter.
   - Import `RoiEncodingInput`.
   - Add `_build_roi_encoding_input(...)`.
   - Dispatch typed input for `fit-roi-encoding`.
   - Leave `_build_ridge_encoding_config(...)` as the owner of `lags` and
     `alphas` parsing.

4. Update pilot call sites.
   - Replace encoding `Namespace(...)` in `brain_region_pipeline/pilot/runner.py`.
   - Replace encoding `Namespace(...)` in
     `brain_region_pipeline/pilot/concurrent.py`.
   - Remove now-unused `from argparse import Namespace` imports if no remaining
     call needs them.

5. Update tests.
   - Add a concurrent pilot test asserting `run_encoding(...)` passes
     `RoiEncodingInput` and config-owned `lags` / `alphas`.
   - Add a staged pilot test or assertion for `_run_encoding(...)` with the same
     contract.
   - Keep existing CLI encoding output tests passing.

6. Search for stale CLI-shaped usage.
   - `rg -n "Namespace\\(|from argparse import Namespace|argparse\\.Namespace" brain_region_pipeline/pilot brain_region_pipeline/encoding brain_region_pipeline/cli.py tests -g '*.py'`
   - Remaining `argparse.Namespace` usage should be CLI adapter type hints or
     unrelated test fake objects only.

7. Validate.
   - `uv run python -m unittest tests.test_brain_region_encoding`
   - `uv run python -m unittest tests.test_brain_region_multi_roi`
   - `uv run python -m unittest tests.test_friends_14roi_concurrent_script`
   - `uv run python -m unittest discover -s tests -p 'test_*.py'`
   - `uv run python -m compileall brain_region_pipeline tests scripts`
   - `uv run python -m brain_region_pipeline`
   - `uv run python -m brain_region_pipeline fit-roi-encoding --help`
   - `git diff --check`

## Risk Points

- Do not duplicate `lags` / `alphas` in `RoiEncodingInput`; those remain
  config-owned.
- Do not change manifest-relative path resolution. `load_roi_encoding_manifest`
  and `_load_roi_schemas` continue to own that behavior.
- Do not alter `encoding_metadata.json` field names or values beyond replacing
  the source object from `args` to `inputs`.

## Review Gate Before Implementation

Do not run `task.py start` or edit product code until the user approves this
planning artifact.
