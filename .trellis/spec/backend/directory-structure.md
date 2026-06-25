# Directory Structure

> How backend code is organized in this project.

---

## Overview

The backend package is one maintained Python workflow package organized by
pipeline domain. Keep package boundaries explicit: `brain_region_pipeline` owns
the maintained brain-region prompt scoring workflow, while older experimental
or validation packages remain separate unless a task explicitly redesigns the
integration.

---

## Directory Layout

```text
brain_region_pipeline/
├── __main__.py              # python -m brain_region_pipeline
├── cli.py                   # CLI argument parsing and stage dispatch only
├── core/
│   ├── config.py            # stage-scoped dataclass configs
│   ├── contracts.py         # serialized contract constants
│   ├── dependencies.py      # dependency injection surface
│   ├── genai.py             # configured LLM structured JSON helper
│   └── io_utils.py          # JSON / JSONL helpers
├── atlas/
│   ├── labels.py            # atlas label parsing and selection-rule expansion
│   ├── models.py            # SelectionRule contract
│   └── roi_config.py        # reusable fixed ROI definitions
├── schema_design/
│   ├── domain_models.py     # domain-pool serialized contracts
│   ├── schema_models.py     # region-schema serialized contracts
│   ├── domain_pool.py       # target-region coarse-domain generation / I/O
│   ├── region_schema.py     # region feature schema generation / validation
│   └── runner.py            # domain-pool and region-schema stage runners
├── scoring/
│   ├── models.py            # description, segment-score, and TR-row contracts
│   ├── description_io.py    # external dense-description parsing
│   ├── summary_generator.py # rolling narrative summaries for scoring context
│   ├── region_schema_scorer.py # segment-level scoring with generated schemas
│   ├── checkpoint.py        # long-run score checkpointing
│   ├── gt_aligner.py        # GT CSV averaging and segment resampling
│   ├── score_aligner.py     # segment scores -> TR feature rows
│   ├── tr_output.py         # readable TR output helpers
│   ├── correlation.py       # segment score / GT Pearson correlation
│   └── runner.py            # score-descriptions orchestration and writes
├── encoding/
│   ├── manifest.py          # unified one-or-more ROI JSONL manifest contract
│   ├── fmri.py              # H5 fMRI target loading and parcel-column checks
│   ├── features.py          # TR feature loading, trimming, lag expansion
│   ├── ridge.py             # Ridge fitting, alpha search, and target metrics
│   └── runner.py            # unified ROI Ridge orchestration and outputs
└── pilot/
    ├── artifacts.py         # Friends pilot artifact graph and encoding inputs
    ├── concurrent.py        # reusable concurrent Friends pilot stage jobs
    └── runner.py            # staged Friends multi-ROI pilot orchestration
```

---

## Module Organization

### `brain_region_pipeline` Boundary

`brain_region_pipeline` currently exposes only these maintained CLI commands:

- `make-domain-pool`
- `make-region-schema`
- `summarize-descriptions`
- `score-descriptions`
- `correlate-scores`
- `fit-roi-encoding`
- `run-multi-roi-pilot`

The maintained data flow is:

```text
atlas labels + target region
  -> domain_pool_v2.json (target-region coarse-domain draft)
  -> region_schema_v1.json
  -> external dense descriptions
  -> summary.json / summary_metadata.json
  -> segment_region_scores.jsonl
  -> tr_features.jsonl / tr_descriptions_readable.jsonl / scoring_metadata.json
  -> optional Pearson correlation against segment_gt_means.jsonl
  -> optional unified ROI H5 fMRI Ridge encoding
```

Do not add video slicing, clip annotation, embedding cache, NIfTI extraction, or
`test_pipeline` adapters back into `brain_region_pipeline` unless a new task
explicitly designs that layer. Ridge encoding is a maintained boundary only for
explicit JSONL manifests, H5 datasets shaped `TR x parcel`, ROI schema
selection rules, and documented train/val/test evaluation. Single-ROI encoding
is represented as a one-entry `roi_features` mapping and must use the same
engine as multi-ROI encoding.

### Responsibilities

- `cli.py` parses arguments and dispatches to runner functions. It should not
  contain scoring, alignment, file-format, or model logic.
- CLI adapters may receive `argparse.Namespace`, but maintained stage runner
  modules should expose typed input objects rather than accepting CLI-shaped
  `Namespace` directly.
- `core/dependencies.py` defines the dependency injection surface. Keep it
  limited to maintained stage dependencies.
- `atlas/labels.py` owns Brainnetome/Yeo parcel label parsing and selection-rule
  expansion only. It should not depend on downstream model-training code.
- `atlas/models.py`, `schema_design/domain_models.py`,
  `schema_design/schema_models.py`, and `scoring/models.py` define serialized
  contracts near the workflow that owns them. Changing JSON field names or
  feature ordering requires synchronized test and README updates.
- `schema_design/domain_pool.py` owns coarse-domain proposal, consolidation,
  confirmation-gate loading, content hashing, and domain-pool rendering only. It
  should not create active scoring dimensions, selection rules, or segment
  scores.
- `schema_design/region_schema.py` owns active-dimension generation. It requires
  a confirmed domain pool, uses it as coarse-domain guidance, snapshots the
  confirmed domains, and records provenance in region-schema metadata.
- `scoring/summary_generator.py` owns rolling narrative summary generation from
  timestamped dense descriptions. It writes Fallen-compatible `summary.json`
  arrays for `score-descriptions --summary-file` and keeps provenance in a
  sidecar metadata file.
- `encoding/manifest.py` owns JSONL manifest validation and path resolution for
  unified ROI Ridge encoding samples. Do not infer feature/fMRI matches from
  filenames. Every row must expose the same `roi_features` keys.
- `encoding/fmri.py` owns H5 dataset loading and the hard check that H5 parcel
  columns match atlas label rows.
- `encoding/features.py` owns explicit feature/fMRI trimming and feature-lag
  expansion. It should not fit models.
- `encoding/ridge.py` owns standardization, Ridge fitting, alpha search, and
  parcel-wise metrics. It should not read or write project files.
- `encoding/runner.py` coordinates unified ROI encoding stages and writes
  outputs. It concatenates ROI features, de-duplicates target parcels, and
  reports `roi_memberships`. Keep file writes here rather than in model
  utilities.
- `atlas/roi_config.py` owns reusable ROI definitions and atlas-rule validation.
- `pilot/artifacts.py` owns Friends pilot artifact paths, confirmed domain-pool
  lookup, and the encoding input sidecars generated from scored ROI outputs:
  `roi_encoding_manifest.jsonl` and `roi_schemas.json`.
- `pilot/concurrent.py` owns reusable Friends pilot concurrency behavior:
  independent job execution, concurrent summary/domain/schema/scoring stage
  jobs, failed-batch retry orchestration, manifest/encoding refresh, and output
  validation. Script adapters should call this module instead of importing
  private helpers from another run-specific script.
- `pilot/runner.py` orchestrates staged Friends multi-ROI runs from config. It
  should call maintained stage runners and `pilot/artifacts.py` rather than
  reimplementing scoring, encoding, path-layout, or manifest-writing logic.
- `core/genai.py` owns provider-specific structured JSON generation only.
  Business modules pass `GenerationConfig` plus prompts/schemas and must not
  import provider SDKs directly.

---

## Scenario: Concurrent Pilot Scripts

### 1. Scope / Trigger

- Trigger: adding or changing a script under `scripts/` that wraps the Friends
  pilot workflow with concurrency, retries, or run-specific defaults.
- These scripts are allowed to improve run ergonomics, but they must not become
  a second implementation of summary generation, scoring, manifest writing, or
  Ridge encoding.

### 2. Signatures

Maintained staged interface:

```bash
uv run python -m brain_region_pipeline run-multi-roi-pilot \
  --config <pilot-config.json> \
  --stage summaries|domain-pools|schemas|scoring|manifest|encoding|all
```

Concurrent full-run script pattern:

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config <pilot-config.json> \
  [--dry-run] \
  [--stage summaries|domain-pools|schemas|scoring|manifest|encoding|all] \
  [--summary-workers N] [--domain-workers N] \
  [--schema-workers N] [--scoring-workers N] \
  [--skip-existing-summaries] [--retry-failed-batches] \
  [--overwrite-scoring]
```

### 3. Contracts

- Episode sets, splits, description paths, H5 file, H5 datasets, ROI ids, and
  output root come from the pilot config, not from hard-coded script constants.
- Relative filesystem paths in pilot configs are resolved relative to the config
  file location, not the current working directory. For configs under
  `configs/`, a value such as `../friends/...` resolves to the repository
  root's ignored `friends/...` data/output tree.
- Concurrent scripts may provide dry-run, full-run, and failed-batch retry
  modes. They may expose the same single-value `--stage` choices as
  `run-multi-roi-pilot` only as a thin concurrent dispatch layer; stage
  internals remain owned by maintained runners.
- For concurrent script stage dispatch, `--stage all` remains the default full
  run, single-stage runs execute only the named stage, and failed-batch retry
  remains an independent recovery mode rather than a non-`all` stage variant.
- Workers control only independent jobs. Setting all workers to `1` must be a
  valid non-concurrent execution mode.
- Cross-output-root artifact copying is a run-specific behavior. Do not include
  it in general-purpose concurrent scripts unless a task explicitly designs the
  provenance and overwrite contract.
- Scripts should call existing functions from `brain_region_pipeline.pilot`,
  `schema_design`, `scoring`, and `encoding` rather than reimplementing stage
  internals.
- General concurrent stage behavior belongs in
  `brain_region_pipeline.pilot.concurrent`. A script may keep run-specific
  defaults, smoke paths, artifact-copying, and environment checks, but it should
  not import private stage/concurrency helpers from another run-specific script.

### 4. Validation & Error Matrix

- Worker value `< 1` -> raise `ValueError` naming the offending flag.
- Missing description file or H5 dataset -> fail during config/input
  validation before any LLM call.
- Existing summary output without explicit skip behavior -> raise a clear
  error instead of overwriting silently.
- Failed scoring batch retry with no recorded failed batches -> log and exit
  without mutating encoding outputs.

### 5. Good/Base/Bad Cases

- Good: `run_friends_14roi_concurrent_pilot.py` reads all episodes from config,
  delegates domain/schema/scoring/encoding to maintained runners, and uses
  workers only for independent jobs.
- Base: a one-off script may reuse known-good artifacts when its filename and
  manifest clearly identify that run-specific behavior.
- Bad: a script hard-codes a season-specific episode set while being documented
  as a general runner.

### 6. Tests Required

- `--help` or parser smoke coverage for every new script-level flag.
- Dry-run coverage using a temporary config that proves episode ids come from
  config and no LLM calls are made.
- Single-stage dispatch coverage should prove a selected stage does not fall
  through to full-run or downstream stages.
- Project CLI regression tests should continue to show `run-multi-roi-pilot` as
  the staged standard interface.

### 7. Wrong vs Correct

#### Wrong

```python
S02_EPISODES = {"s02e01a", "s02e02a"}
episodes = [episode for episode in config.episodes if episode.episode_id in S02_EPISODES]
```

#### Correct

```python
for episode in config.episodes:
    schedule_summary_and_scoring_jobs(episode)
```

---

## Naming Conventions

- Use short, role-specific module names.
- Keep command names stable once documented.
- Use ASCII `snake_case` IDs for serialized `domain_id` and `dimension_id`
  values. Region schemas do not use module identifiers.

---

## Examples

- `scoring/description_io.py`: one responsibility, external dense-description parsing.
- `scoring/summary_generator.py`: one responsibility, causal batch-level narrative
  summaries for scorer Story Context.
- `schema_design/domain_pool.py`: one responsibility, coarse-domain pool
  generation and validation before region-schema generation.
- `scoring/score_aligner.py`: one responsibility, segment scores to TR feature rows.
- `scoring/gt_aligner.py`: one responsibility, notebook-style GT CSV averaging
  to description segments.
- `scoring/tr_output.py`: output helper kept separate from alignment logic.
- `scoring/correlation.py`: one responsibility, segment score / GT Pearson
  correlation with explicit lag semantics.
