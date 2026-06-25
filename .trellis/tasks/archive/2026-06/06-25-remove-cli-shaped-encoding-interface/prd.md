# Remove CLI-shaped encoding interface

## Goal

Move the encoding stage runner interface away from CLI-shaped `args` objects so
maintained callers pass an explicit typed input object. This is the final
encoding slice of the broader "remove CLI-shaped stage runner interface"
cleanup after summary/scoring and schema-design were migrated.

The public CLI command `fit-roi-encoding` remains unchanged. The internal
boundary should become:

```text
CLI / pilot adapter -> RoiEncodingInput + RidgeEncodingConfig -> encoding runner
```

## Confirmed Facts

- Backend guidelines allow `argparse.Namespace` inside `cli.py`, but maintained
  stage runner modules should expose typed input objects rather than accepting
  CLI-shaped `Namespace` directly.
- Backend guidelines also state that stage config dataclasses own generation
  settings and model hyperparameters; typed runner input objects should carry
  file/resource inputs the runner actually consumes.
- `fit_roi_encoding_from_manifest(args, cfg)` currently reads
  `args.output_dir`, `args.manifest`, `args.roi_schemas`, and
  `args.atlas_labels` directly
  (`brain_region_pipeline/encoding/runner.py:581`).
- The CLI still passes parsed `args` directly to `fit_roi_encoding_from_manifest`
  for `fit-roi-encoding` (`brain_region_pipeline/cli.py:437`).
- The staged pilot runner still constructs `Namespace(...)` for encoding
  (`brain_region_pipeline/pilot/runner.py:485`).
- The concurrent pilot runner still constructs `Namespace(...)` for encoding
  (`brain_region_pipeline/pilot/concurrent.py:636`).
- `RidgeEncodingConfig` already owns `lags` and `alphas`; these should remain
  config-owned instead of being duplicated in the typed input object.

## Requirements

- Add a typed encoding runner input object, named `RoiEncodingInput`, for the
  file/resource inputs consumed by `fit_roi_encoding_from_manifest`.
- `RoiEncodingInput` should contain only:
  - `manifest: Path`
  - `roi_schemas: Path`
  - `atlas_labels: Path`
  - `output_dir: Path`
- Keep `lags` and `alphas` in `RidgeEncodingConfig`.
- Keep CLI parsing and `argparse.Namespace` handling inside
  `brain_region_pipeline/cli.py`; CLI may build `RoiEncodingInput` from parsed
  args.
- Update staged and concurrent pilot encoding callers to construct
  `RoiEncodingInput` directly instead of creating `Namespace(...)`.
- Preserve all existing encoding behavior, including manifest loading,
  manifest-relative path resolution, ROI schema mapping validation, atlas
  parsing, trim/alignment semantics, Ridge fitting, output files, metadata
  shape, logging, and CLI help.
- Do not change the manifest JSONL contract, `roi_schemas.json` contract, H5
  loading semantics, trim defaults, alpha selection logic, or output metric
  schema.
- Do not introduce compatibility overloads that accept both CLI-shaped args and
  typed input; maintained callers are few and should migrate directly.

## Acceptance Criteria

- [ ] `brain_region_pipeline/encoding/runner.py` exposes `RoiEncodingInput`.
- [ ] `fit_roi_encoding_from_manifest(...)` accepts `RoiEncodingInput`, not a
      CLI-shaped args object.
- [ ] `brain_region_pipeline/cli.py` builds `RoiEncodingInput` before dispatching
      `fit-roi-encoding`.
- [ ] `brain_region_pipeline/pilot/runner.py` no longer imports or constructs
      `argparse.Namespace` solely for encoding.
- [ ] `brain_region_pipeline/pilot/concurrent.py` no longer imports or
      constructs `argparse.Namespace` solely for encoding.
- [ ] Encoding CLI behavior and existing output metadata remain compatible.
- [ ] Staged pilot and concurrent pilot regression tests prove encoding calls
      receive `RoiEncodingInput` with correct artifact paths and config-owned
      lags/alphas.
- [ ] A repository search shows no remaining `Namespace(...)` usage in
      `brain_region_pipeline/pilot/*` for this task's maintained stage calls.
- [ ] Standard backend validation passes:
      `uv run python -m unittest tests.test_brain_region_encoding`,
      `uv run python -m unittest tests.test_brain_region_multi_roi`,
      `uv run python -m unittest tests.test_friends_14roi_concurrent_script`,
      `uv run python -m unittest discover -s tests -p 'test_*.py'`,
      `uv run python -m compileall brain_region_pipeline tests scripts`,
      `uv run python -m brain_region_pipeline`,
      `uv run python -m brain_region_pipeline fit-roi-encoding --help`,
      and `git diff --check`.

## Notes

- Out of scope: changing encoding algorithm internals, manifest validation,
  trim/alignment behavior, H5 loading, or Ridge model math.
- Out of scope: changing public CLI flags or pilot config schema.
- Out of scope: changing existing Friends output artifacts under ignored
  `friends/` paths.
