# Design: Remove CLI-shaped encoding interface

## Boundary

This task changes only the Python runner boundary for the maintained encoding
stage. It does not change the public CLI contract, pilot config schema, manifest
contract, or encoding output files.

Desired flow:

```text
argparse.Namespace
  -> brain_region_pipeline.cli adapter
  -> RoiEncodingInput + RidgeEncodingConfig
  -> brain_region_pipeline.encoding.runner.fit_roi_encoding_from_manifest
```

Pilot callers should bypass the CLI-shaped layer:

```text
PilotConfig + PilotArtifacts
  -> RoiEncodingInput + RidgeEncodingConfig
  -> brain_region_pipeline.encoding.runner.fit_roi_encoding_from_manifest
```

## Contract

### RoiEncodingInput

Owned by `brain_region_pipeline/encoding/runner.py`.

Fields:

- `manifest: Path`
- `roi_schemas: Path`
- `atlas_labels: Path`
- `output_dir: Path`

The runner should continue to use `RidgeEncodingConfig` for model/search
hyperparameters:

- `lags`
- `alphas`

This matches the backend spec decision that typed runner inputs carry the
file/resource inputs a stage consumes, while config dataclasses own tunable
settings and hyperparameters.

## Call Sites

### CLI

Add a CLI adapter parallel to the existing typed stage adapters:

```python
def _build_roi_encoding_input(args: argparse.Namespace) -> RoiEncodingInput:
    return RoiEncodingInput(
        manifest=Path(args.manifest),
        roi_schemas=Path(args.roi_schemas),
        atlas_labels=Path(args.atlas_labels),
        output_dir=Path(args.output_dir),
    )
```

Dispatch:

```python
fit_roi_encoding_from_manifest(
    _build_roi_encoding_input(args),
    _build_ridge_encoding_config(args),
)
```

### Staged Pilot Runner

`brain_region_pipeline/pilot/runner.py` should import `RoiEncodingInput` and
pass artifact graph paths directly in `_run_encoding(...)`. After this, the
module should no longer need `from argparse import Namespace`.

### Concurrent Pilot Runner

`brain_region_pipeline/pilot/concurrent.py` should do the same in
`ConcurrentPilotStages.run_encoding(...)`. After this, the module should no
longer need `from argparse import Namespace`.

## Metadata Compatibility

`encoding_metadata.json` should keep existing fields and values:

- `command`
- `manifest`
- `roi_schemas`
- `atlas_labels`
- `feature_set_name`
- `roi_order`
- `lags`
- `alphas`
- downstream summaries and subject rows

The implementation should replace `args.<field>` reads with `inputs.<field>`
without changing serialization semantics.

## Testing Strategy

- Keep existing CLI integration tests for `fit-roi-encoding` outputs.
- Add/extend direct call assertions for staged pilot and concurrent pilot so
  both paths prove they pass `RoiEncodingInput` and `RidgeEncodingConfig`.
- Use an `rg` check for `Namespace(` in `brain_region_pipeline/pilot` to confirm
  the leftover CLI-shaped pilot stage interface is gone.
- Run the standard backend validation from the PRD.

## Trade-offs

No compatibility overload is added. Accepting both typed input and arbitrary
`args` would preserve the shallow interface this task removes.

No shared builder module is added. CLI and pilot adapters have different source
objects, and the conversion is small enough to keep near each boundary.

## Rollback

Rollback is a normal git revert of the work commit. No output artifact migration
is needed because manifest and metadata contracts are unchanged.
