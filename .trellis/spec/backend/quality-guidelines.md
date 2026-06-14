# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

Backend changes should preserve the current maintained workflow boundary and
keep tests aligned with documented CLI behavior. Prefer small, focused edits
over broad refactors, especially when the working tree already contains
unrelated changes.

---

## Forbidden Patterns

- Do not make `brain_region_pipeline` import from `test_pipeline`. The current
  package boundary is scoring-only; old validation or experiment code must stay
  separate until a new encoding design is specified.
- Do not expose an incomplete CLI command as a retained feature. If a command is
  deferred, remove the parser entry and add a test that it is unavailable.
- Do not silently change serialized JSON field names, feature vector ordering, or
  region-schema dimension metadata without updating tests and README contracts.
- Do not put stage business logic in `cli.py`; keep it in runner or focused
  modules.
- Do not auto-match H5 fMRI datasets to feature files by filename. Encoding
  sample pairing must come from the JSONL manifest.

---

## Required Patterns

- Use dependency injection in `PipelineDependencies` only for maintained stage
  dependencies. Remove stale fields when a stage is removed so tests do not need
  fake dependencies for unused behavior.
- When removing a workflow stage, update code, tests, README, review docs, and
  dependency metadata together.
- Use `uv` for Python commands in this project.
- Keep generated caches such as `__pycache__/` out of the working tree after
  validation.

---

## Testing Requirements

For changes to `brain_region_pipeline`, run:

```bash
uv run python -m unittest discover -s tests -p 'test_*.py'
uv run python -m compileall brain_region_pipeline tests
```

When a CLI command is removed or added, also check the top-level CLI help and
the command-specific behavior:

```bash
uv run python -m brain_region_pipeline
uv run python -m brain_region_pipeline <command> --help
```

For dependency cleanup, search the affected package, tests, and docs for stale
references:

```bash
rg "<removed_dependency_or_command>" brain_region_pipeline tests README.md docs pyproject.toml
```

---

## Code Review Checklist

- Does the implementation preserve the documented package boundary?
- Are CLI help, README, tests, and dependency metadata consistent?
- Are tests covering removed commands as unavailable when that is the intended
  behavior?
- Did validation avoid leaving `__pycache__/` or other generated artifacts in the
  repo?
- Were unrelated dirty files left intact?

---

## Scenario: LLM Prompt Contract Synchronization

### 1. Scope / Trigger

- Trigger: changes touching LLM prompt rules, structured response schemas, or
  Python validators in generation modules such as `domain_pool.py`,
  `region_schema.py`, `summary_generator.py`, or `region_schema_scorer.py`.

### 2. Signatures

```python
payload = generate_structured_json(
    model=cfg.generation_model,
    system_instruction=SYSTEM_INSTRUCTION,
    contents=[prompt],
    response_schema=response_schema,
    cfg=cfg,
)
```

### 3. Contracts

- Any numeric bound, enum, required field set, or naming rule mentioned in a
  prompt should have one module-level constant or helper that is reused by the
  response schema, Python validator, and tests.
- Prompt sections should be split by responsibility when a generator prompt
  grows beyond a single short rule block: task payload, domain rules,
  dimension/scoring rules, ROI-specific rules, and input data should remain
  separate helpers.
- PackyAPI uses JSON-object mode, so the provider may not enforce JSON Schema
  constraints. Stage-specific Python validators are the final contract gate.

### 4. Validation & Error Matrix

- Prompt says a list accepts `N..M` items but validator checks only the lower
  bound -> add the upper-bound validator check.
- Response schema uses literal bounds that differ from validator constants ->
  replace literals with shared constants.
- A prompt phrase is duplicated in required/optional branches -> extract a
  helper for the shared rule and keep branch-specific text minimal.

### 5. Good/Base/Bad Cases

- Good: `MIN_DIMENSION_TRIGGERS` and `MAX_DIMENSION_TRIGGERS` drive the prompt,
  response schema, validator error text, and tests.
- Base: branch-specific prompt text adds context while shared helper lines hold
  common requirements.
- Bad: tests assert long prompt prose while the schema and validator keep
  separate hard-coded numeric values.

### 6. Tests Required

- Prompt smoke test that checks essential semantic fragments, not every line of
  prose.
- Schema test that checks min/max or enum values come from the shared constants.
- Validator regression tests for both lower and upper bounds when the prompt
  names a bounded range.

### 7. Wrong vs Correct

#### Wrong

```python
"trigger_list": {"minItems": 3, "maxItems": 6}

if len(dimension.trigger_list) < 3:
    errors.append("trigger_list must include at least 3 items")
```

#### Correct

```python
MIN_DIMENSION_TRIGGERS = 3
MAX_DIMENSION_TRIGGERS = 6

"trigger_list": {
    "minItems": MIN_DIMENSION_TRIGGERS,
    "maxItems": MAX_DIMENSION_TRIGGERS,
}

if not MIN_DIMENSION_TRIGGERS <= len(items) <= MAX_DIMENSION_TRIGGERS:
    errors.append("trigger_list must include 3 to 6 items")
```

---

## Scenario: LLM Provider Integration

### 1. Scope / Trigger

- Trigger: changes touching `GenerationConfig`, `genai.py`, model/provider CLI
  flags, `.env` secret names, prompt-generation metadata, or pilot config model
  settings.
- This is a cross-layer contract: config defaults, CLI args, `.env` keys,
  provider SDK calls, output provenance, README, and tests must stay aligned.

### 2. Signatures

```bash
uv run python -m brain_region_pipeline make-domain-pool \
  --atlas-labels <atlas.csv> \
  --target-region <ROI> \
  --output-file <domain_pool.json> \
  [--provider aihubmix|packyapi|gemini] \
  [--model gemini-3.5-flash]

uv run python -m brain_region_pipeline make-region-schema ... \
  [--provider aihubmix|packyapi|gemini] [--model <model>]

uv run python -m brain_region_pipeline summarize-descriptions ... \
  [--provider aihubmix|packyapi|gemini] [--model <model>]

uv run python -m brain_region_pipeline score-descriptions ... \
  [--provider aihubmix|packyapi|gemini] [--model <model>]
```

Pilot configs may include:

```json
{
  "generation_provider": "aihubmix",
  "generation_model": "gemini-3.5-flash"
}
```

### 3. Contracts

- `GenerationConfig.generation_provider` is the single provider selector.
- Default provider/model are `aihubmix` and `gemini-3.5-flash`.
- AIHubMix uses the OpenAI SDK with `AIHUBMIX_API_KEY` and default
  `AIHUBMIX_BASE_URL=https://aihubmix.com/v1`.
- The AIHubMix OpenAI-compatible chat path always uses
  `response_format={"type": "json_schema", "json_schema": {"strict": true,
  ...}}`. It must not silently fall back to JSON-object mode; unsupported
  AIHubMix models should fail through the provider error.
- AIHubMix strict JSON schemas are normalized in `core/genai.py` before the
  provider request, including recursive object-level
  `additionalProperties: false` where omitted by business schemas.
- AIHubMix strict JSON schemas belong only in the OpenAI-compatible
  `response_format` payload. Do not append a `Response JSON schema:` block to
  the user message on this path; the user message should contain only the task
  prompt content so high-volume scoring does not pay for duplicate schema text.
- PackyAPI uses the OpenAI SDK with `PACKYAPI_API_KEY` and default
  `PACKYAPI_BASE_URL=https://www.packyapi.com/v1`. The optimized
  `https://api-slb.packyapi.com/v1` route may be used only via explicit
  `PACKYAPI_BASE_URL` override.
- The PackyAPI OpenAI-compatible chat path uses `response_format={"type":
  "json_object"}` for default PackyAPI models such as `mimo-v2.5-pro`; the
  expected JSON schema must be rendered in the prompt and stage-specific Python
  validators must enforce the contract after parsing.
- PackyAPI-hosted Gemini models identified by `gemini-*` should use
  `response_format={"type": "json_schema", "json_schema": {"strict": true,
  ...}}` because they accept OpenAI-compatible strict schemas and otherwise tend
  to return truncated JSON, empty payloads, top-level lists, or missing segment
  fields under JSON-object mode.
- Gemini remains available with `generation_provider="gemini"` and
  `GEMINI_API_KEY` or `GOOGLE_API_KEY`.
- Direct Gemini can use Vertex AI Express mode by setting
  `GEMINI_USE_VERTEXAI=true` or `GOOGLE_GENAI_USE_VERTEXAI=true`; this path
  should initialize `genai.Client(vertexai=True, api_key=<Gemini key>)` and
  should not require `GEMINI_BASE_URL`.
- Direct Gemini generation must pass only task prompt content through
  `contents`; JSON output constraints belong in the SDK `config` payload. With
  current `google-genai` releases, use `response_mime_type="application/json"`
  and `response_json_schema=<schema>` rather than rendering the schema into the
  prompt or passing unsupported `response_format` fields.
- Direct Gemini retry belongs in the Google GenAI SDK client configuration,
  not in `generate_structured_json(...)` application loops. The project retry
  setting is three retries after the original request; `HttpRetryOptions.attempts`
  counts the original request, so pass `attempts=4`.
- Provider SDK imports stay inside `genai.py`; domain/schema/summary/scoring
  modules call only `generate_structured_json(...)`.
- Output provenance should record provider and model where stage metadata or
  resume signatures depend on LLM behavior.

### 4. Validation & Error Matrix

- Unknown provider from config or CLI -> `ValueError` naming allowed providers.
- Missing `AIHUBMIX_API_KEY` for AIHubMix -> `RuntimeError` naming the env key.
- AIHubMix structured output request -> must send strict `json_schema` with a
  normalized schema and no JSON-object fallback.
- AIHubMix structured output request -> user message must not include the
  rendered response schema when strict `response_format` already carries it.
- Missing `PACKYAPI_API_KEY` for PackyAPI -> `RuntimeError` naming the env key.
- `AIHUBMIX_API_KEY` without `PACKYAPI_API_KEY` still must not satisfy PackyAPI
  config.
- PackyAPI structured output request for non-Gemini models -> must send
  `response_format={"type": "json_object"}` and include the schema in the
  prompt.
- PackyAPI structured output request for `gemini-*` models -> must send strict
  `response_format={"type": "json_schema"}` with the same response schema.
- Missing Gemini key for Gemini -> `RuntimeError` naming Gemini key choices.
- Direct Gemini retry exhaustion -> propagate the final SDK/API error to the
  caller; scoring batches then use the existing zero-fill warning path.
- Existing score checkpoints with different provider/model -> resume signature
  mismatch and reject resume.
- Provider default changes -> update config constants, CLI help tests, README,
  pilot config, and lockfile together.

### 5. Good/Base/Bad Cases

- Good: default run uses AIHubMix/Gemini 3.5 Flash, writes provider/model
  metadata, can resume only with the same provider/model, and sends strict
  schema once via `response_format` rather than duplicating it in the prompt.
- Base: a PackyAPI run passes `--provider packyapi --model mimo-v2.5-pro` and
  uses JSON-object mode plus Python validators.
- Base: a legacy run passes `--provider gemini --model gemini-3-flash-preview`
  and uses the existing Google GenAI path.
- Bad: a module imports `openai` or `google.genai` directly outside `genai.py`,
  bypassing shared provider selection, `.env`, and JSON parsing behavior.

### 6. Tests Required

- Unit tests for provider defaults, API key resolution, base URL default, and
  provider dispatch.
- Unit tests for AIHubMix strict schema request payload and schema normalization.
- Unit tests for AIHubMix strict schema request payload should assert that the
  user message omits rendered schema text while `response_format` keeps the
  normalized strict schema.
- CLI help tests for `--provider` and `--model` on each LLM-backed command.
- Pilot config tests for default provider/model and explicit provider parsing.
- Regression tests that Gemini dispatch remains available.
- Regression tests that Gemini client creation passes SDK retry options and
  `generate_structured_json(...)` does not add a second application-level retry
  loop.
- Standard validation:
  `uv run python -m unittest discover -s tests -p 'test_*.py'` and
  `uv run python -m compileall brain_region_pipeline tests`.

### 7. Wrong vs Correct

#### Wrong

```python
from openai import OpenAI

# Inside region_schema_scorer.py
client = OpenAI(...)
```

#### Correct

```python
payload = generate_structured_json(
    model=cfg.generation_model,
    system_instruction=system_instruction,
    contents=[prompt],
    response_schema=response_schema,
    cfg=cfg,
)
```

---

## Scenario: Score-Descriptions Checkpointing

### 1. Scope / Trigger

- Trigger: changes touching `score-descriptions`, `runner.py`,
  `region_schema_scorer.py`, `scoring_checkpoint.py`, segment-score JSONL
  contracts, or long-running scoring recovery behavior.
- This is a cross-layer contract: CLI flags, runner orchestration, scorer batch
  IDs, JSONL rows, progress metadata, README, and tests must stay aligned.

### 2. Signatures

```bash
uv run python -m brain_region_pipeline score-descriptions \
  --descriptions <timestamped_descriptions.txt> \
  --region-schema <region_schema.json> \
  --output-dir <scored_dir> \
  [--summary-file <summary.json>] \
  [--scoring-batch-size 40] \
  [--local-buffer-size 10] \
  [--resume] \
  [--overwrite]
```

`--resume` and `--overwrite` are mutually exclusive.

### 3. Contracts

- `cli.py` parses only flags and validates direct argument constraints. It must
  not own checkpoint or scoring logic.
- `runner.py` owns stage orchestration, checkpoint writes, resume decisions, and
  final output generation.
- `region_schema_scorer.py` owns LLM prompts and batch scoring only. It should
  return `SegmentRegionScore` rows with stable `segment_id` and `batch_idx`, but
  must not write checkpoint files.
- `scoring_checkpoint.py` owns output-policy checks, input signatures, progress
  payloads, and resume validation.
- During scoring, only `segment_region_scores.jsonl`,
  `scoring_warnings.jsonl`, and `scoring_progress.json` are written
  incrementally.
- `tr_features.jsonl`, `tr_descriptions_readable.jsonl`,
  `segment_gt_means.jsonl`, and `scoring_metadata.json` are final derived
  outputs and are written only after complete segment scores are available.
- `segment_region_scores.jsonl` rows must keep the legacy score fields and add
  `segment_id` and `batch_idx` for audit/resume validation.
- `scoring_progress.json` must record `status`, `total_segments`,
  `completed_segments`, `next_segment_id`, `completed_batches`, scoring config,
  source paths, `run_signature`, and warning summary.

### 4. Validation & Error Matrix

- Existing score-descriptions outputs without `--resume` or `--overwrite` ->
  `ValueError` telling the caller to choose one explicitly.
- `--resume` plus `--overwrite` -> `ValueError`.
- Resume with mismatched descriptions/schema/summary hash, model, batch size,
  local buffer, TR config, alignment, or GT args -> `ValueError`.
- Resume with missing `scoring_progress.json` but existing scoring outputs ->
  `ValueError`.
- Resume score rows missing `segment_id` or `batch_idx` -> `ValueError`.
- Resume score rows that are non-contiguous, duplicated, out of order, have a
  partial batch, or do not match the current descriptions/schema -> `ValueError`.
- Complete score rows but missing final derived outputs -> resume skips Gemini
  and regenerates only final outputs.

### 5. Good/Base/Bad Cases

- Good: a 1,200-segment run with batch size 40 commits each completed batch to
  `segment_region_scores.jsonl`; after interruption at segment 800, rerunning
  the same command with `--resume` starts at batch 20 and writes final outputs
  after all scores are complete.
- Base: all segment scores are already committed, but final TR files are absent
  because alignment crashed; `--resume` skips Gemini and regenerates derived
  outputs from committed scores.
- Bad: an output dir contains old score rows and the user reruns without
  `--resume` or `--overwrite`. Silent overwrite or mixed output is forbidden.

### 6. Tests Required

- CLI help exposes `--resume` and `--overwrite`.
- Existing output dir rejects a rerun unless `--resume` or `--overwrite` is
  explicit.
- Interrupted run resumes from committed batches and does not rescore earlier
  rows.
- Resume rejects changed scoring config or input signature.
- Complete score rows with missing final outputs skip Gemini and finalize from
  disk.
- Required validation still passes:
  `uv run python -m unittest discover -s tests -p 'test_*.py'` and
  `uv run python -m compileall brain_region_pipeline tests`.

### 7. Wrong vs Correct

#### Wrong

```text
score-descriptions
# runner holds all scores in memory and writes segment_region_scores.jsonl only
# after the last Gemini batch returns
```

#### Correct

```text
score-descriptions --resume
# runner appends each completed batch to segment_region_scores.jsonl, updates
# scoring_progress.json atomically, and resumes only when checkpoint validation
# proves the current command matches the committed rows
```

---

## Scenario: ROI H5 fMRI Ridge Encoding

### 1. Scope / Trigger

- Trigger: changes touching `fit-roi-encoding`, `encoding/manifest.py`,
  `encoding/fmri.py`, `encoding/features.py`, `encoding/ridge.py`,
  `encoding/runner.py`, `atlas/roi_config.py`, `pilot/runner.py`, fixed ROI
  definition JSON, or ROI output contracts.
- This is a cross-layer contract: ROI schemas, per-episode ROI feature files,
  H5 datasets, atlas label rows, target parcel membership, CLI help, README,
  and tests must stay aligned. Single-ROI encoding is the one-entry
  `roi_features` case of the same manifest and runner.

### 2. Signatures

```bash
uv run python -m brain_region_pipeline fit-roi-encoding \
  --manifest <roi_encoding_manifest.jsonl> \
  --roi-schemas <roi_schemas.json> \
  --atlas-labels atlas/subregion_func_network_Yeo_updated.csv \
  --output-dir <out_dir> \
  [--lags 2,3,4,5,6] \
  [--alphas 0.01,0.03,0.1,0.3,1,3,10,30,100,300,1000,3000,10000]
```

```bash
uv run python -m brain_region_pipeline run-multi-roi-pilot \
  --config <pilot_config.json> \
  [--stage summaries|domain-pools|schemas|scoring|manifest|encoding|all] \
  [--dry-run]
```

### 3. Contracts

- ROI encoding manifest is JSONL, one sample per line. Each row must include
  `sample_id`, `subject_id`, `feature_set_name`, `split`, `roi_features`,
  `h5_file`, and `h5_dataset`.
- `roi_features` is an object mapping ROI id to that ROI's `tr_features.jsonl`
  for the same sample. Single-ROI runs use exactly one mapping entry. Every
  manifest row must contain the same ROI ids.
- `--roi-schemas` is a JSON object, or an object with `roi_schemas`, mapping ROI
  ids to `region_schema_v1.json` files. Mapping keys must match each schema's
  `target_region`.
- The runner concatenates ROI feature matrices in schema-mapping order, prefixing
  feature names as `<roi_id>::<dimension_id>`.
- Before concatenation, all ROI feature files for one sample must have identical
  `tr_index`, `tr_start_s`, and `tr_end_s` sequences.
- Target parcels are the union of all ROI schema selection rules. Duplicate
  parcel indices are predicted once, and parcel metadata records
  `roi_memberships`.
- Subject outputs include `roi_summaries.json` and parcel rows include
  `roi_memberships`, even for single-ROI runs. Do not average parcels before
  fitting.
- `run-multi-roi-pilot --stage all` writes `domain_pool_draft.json` plus a
  separate `domain_pool_auto_confirmed.json` with
  `confirmation_mode=auto_pilot`; final claims still require manual review.

### 4. Validation & Error Matrix

- Manifest line is not valid JSON -> `ValueError` with manifest line number.
- Manifest row missing a required field -> `ValueError` with line number.
- `split` not in `train|val|test` -> `ValueError`.
- Duplicate `sample_id` -> `ValueError`.
- More than one `feature_set_name` in one run -> `ValueError`.
- Any subject missing `train`, `val`, or `test` rows -> `ValueError`.
- Manifest rows contain different ROI ids -> `ValueError`.
- `--roi-schemas` keys differ from manifest ROI ids -> `ValueError`.
- ROI schema mapping key mismatches schema `target_region` -> `ValueError`.
- Per-sample ROI feature TR axes differ -> `ValueError`.
- H5 dataset absent, non-2D, or with parcel columns not equal to atlas label row
  count -> `ValueError`.
- ROI schema selection rules select no parcels -> `ValueError`.
- Feature vector length differs from the corresponding ROI schema dimensions ->
  `ValueError`.
- Feature/fMRI lengths differ after explicit trimming -> `ValueError`.
- A sample has no rows left after trimming or too few rows for `max(lags)` ->
  `ValueError`.
- All train X columns or all train Y parcels are constant -> `ValueError`.
- ROI definition selects no atlas parcels -> `ValueError`.
- Pilot config missing train, val, or test episodes -> `ValueError`.
- Pilot config H5 file or requested dataset is missing -> `ValueError`.

### 5. Good/Base/Bad Cases

- Good: one subject has five train episodes, one val episode, and one test
  episode. Each sample row points to all ROI feature files and one explicit H5
  dataset. The command fits one model and reports overall, ROI-level, and
  parcel-level metrics.
- Base: one ROI schema and one feature file per sample use the exact same
  command and output contract as multi-ROI runs.
- Base: two ROI schemas select one overlapping parcel; target Y keeps that
  parcel once and records both ROI ids in `roi_memberships`.
- Bad: silently concatenating ROI feature files with different TR axes. This can
  mix episodes or shift time and is forbidden.

### 6. Tests Required

- Manifest validation rejects inconsistent ROI sets.
- Tiny H5 fixture verifies duplicate target parcels are de-duplicated and
  `roi_memberships` are reported.
- Tiny H5 fixture verifies the one-ROI manifest case goes through the unified
  runner and writes `roi_summaries.json`.
- CLI help exposes `fit-roi-encoding` and `run-multi-roi-pilot`.
- Pilot dry-run validates ROI definitions, episode paths, H5 datasets, and
  prints scoring job scale without calling Gemini.
- Required validation still passes:
  `uv run python -m unittest discover -s tests -p 'test_*.py'` and
  `uv run python -m compileall brain_region_pipeline tests`.

### 7. Wrong vs Correct

#### Wrong

```text
fit-roi-encoding
# ROI_A s01e01a features and ROI_B s01e05a features are both length 468, so
# code silently hstacks them by row number.
```

#### Correct

```text
fit-roi-encoding
# code checks tr_index/tr_start_s/tr_end_s for every ROI feature file in the
# sample before hstacking, then fails if the axes differ.
```

---

## Scenario: Brainnetome Atlas ROI Selection

### 1. Scope / Trigger

- Trigger: changes touching `atlas/labels.py`, `atlas/models.py`,
  `atlas/roi_config.py`, fixed ROI definition JSON, `--atlas-labels`, or any
  Brainnetome246 fMRI target H5.
- This is a cross-layer contract: atlas label tables, ROI definitions,
  region-schema selection rules, H5 parcel-column order, README, and tests must
  stay aligned.

### 2. Signatures

```bash
uv run python -m brain_region_pipeline fit-roi-encoding \
  --manifest <roi_encoding_manifest.jsonl> \
  --roi-schemas <roi_schemas.json> \
  --atlas-labels atlas/subregion_func_network_Yeo_updated.csv \
  --output-dir <out_dir>
```

Fixed ROI definitions may use 1-based Brainnetome label ids:

```json
{"selection_rules":[{"label_ids":[135,136],"networks":[],"sub_regions":[],"hemispheres":[]}]}
```

### 3. Contracts

- `parse_atlas_labels` is the maintained entry point for atlas tables. It is
  Brainnetome-only and must reject non-CSV atlas tables instead of silently
  falling back to older atlas formats.
- Brainnetome parcels use `idx_0based = Label - 1`; H5 datasets for those runs
  must be shaped `TR x 246` in the same row order as the CSV.
- `SelectionRule.label_ids` are positive 1-based atlas labels. They are exact
  selectors and may be combined with `networks`, `sub_regions`, and
  `hemispheres` as additional filters.
- Brainnetome parser metadata must include at least `label`, `hemisphere`,
  `network`, and `sub_region` so existing encoding metadata and summaries keep
  working.
- Fixed Brainnetome ROI definitions should prefer `label_ids` when the target
  ROI comes from a curated Brainnetome table; this avoids fragile string matches
  over abbreviations.

### 4. Validation & Error Matrix

- Brainnetome CSV missing required columns -> `ValueError`.
- Brainnetome CSV contains no numeric `Label` rows -> `ValueError`.
- `SelectionRule.label_ids` contains zero or negative values -> `ValueError`.
- ROI definition selects no atlas parcels -> `ValueError`.
- Brainnetome H5 has a parcel-column count other than 246 when paired with the
  Brainnetome CSV -> existing H5/atlas count check must fail.

### 5. Good/Base/Bad Cases

- Good: `configs/roi_definitions_brainnetome246_yeo.json` uses exact
  Brainnetome label ids; validation reports a nonzero count for every ROI.
- Base: ROI definitions may combine `label_ids` with Brainnetome metadata
  filters such as `networks`, `sub_regions`, and `hemispheres`.
- Bad: selecting Brainnetome ROIs by broad Yeo network strings alone. That can
  over-select unrelated parcels or fail when network names change.

### 6. Tests Required

- Atlas unit test parses a Brainnetome/Yeo CSV with its title row plus second
  row header and verifies `label_ids` expansion.
- Pilot dry-run test validates a Brainnetome ROI definition using
  `label_ids`.
- Encoding tests must use Brainnetome/Yeo CSV fixtures, not legacy atlas txt
  fixtures.
- Required validation still passes:
  `uv run python -m unittest discover -s tests -p 'test_*.py'` and
  `uv run python -m compileall brain_region_pipeline tests`.

### 7. Wrong vs Correct

#### Wrong

```text
--atlas-labels atlas/subregion_func_network_Yeo_updated.csv
# parser accepts a legacy atlas txt file or uses only Yeo network ids to define
# TPJ/IPL targets.
```

#### Correct

```text
--atlas-labels atlas/subregion_func_network_Yeo_updated.csv
# parser returns 246 Brainnetome parcel rows, and fixed ROI definitions use
# curated 1-based label_ids such as TPJ=[75,76,79,80,121,...,146].
```

---

## Scenario: Domain-Pool Guided Region-Schema Generation

### 1. Scope / Trigger

- Trigger: changes touching `make-domain-pool`,
  `make-region-schema --domain-pool`, domain-pool JSON, region-schema JSON, or
  active-dimension validation.
- This is a cross-layer contract: CLI args, model serialization, prompt
  generation, scorer prompt rendering, README/docs, and tests must stay aligned.

### 2. Signatures

- `uv run python -m brain_region_pipeline make-domain-pool --atlas-labels <labels.txt> --target-region <region> --output-file <domain_pool.json> [--model <model>] [--proposal-runs <n>]`
- `uv run python -m brain_region_pipeline make-region-schema --atlas-labels <labels.txt> --target-region <region> --domain-pool <confirmed_domain_pool.json> --output-file <region_schema.json> [--model <model>]`
- `score-descriptions` consumes `region_schema_v1.json`; domain pools never flow
  directly into scoring or encoding.

### 3. Contracts

`domain_pool.json` must include:

- `version`, currently `domain_pool_v2`
- `target_region`
- `curation_status`, either `draft` or `confirmed`
- `source_model`
- `proposal_runs`
- `candidate_domains`
- `curated_domains`
- `rejected_or_merged_domains`
- optional `metadata`

Each `candidate_domain` must include `domain_id`, `definition`,
`region_relevance`, `scoreability_note`, and `source_run`. `domain_id` is the
canonical human-readable label; do not add a separate coarse-domain `name`.
Legacy vmPFC artifacts containing `vmpfc_relevance` may be read for backward
compatibility, but new outputs must write `region_relevance`.

Domain-pool entries are coarse-domain organizational units, not maximally
expansive categories. They should organize multiple possible active dimensions
while staying concrete enough for later text-scoreable variables; reject domains
that are too expansive or underspecified, too fine-grained, weakly relevant, or
redundant.

Domain-pool prompts and generated domains must use a viewer-centric perspective.
The LLM is simulating what a typical viewer watching the movie can infer,
appraise, track, or integrate from a described segment. Character states,
dialogue, actions, facial expressions, outcomes, and scene atmosphere are
evidence available to the viewer; they are not automatically the subject of the
domain. Emotion-related domains must not be defined as the emotion a character
experiences unless a future task explicitly changes the scientific contract.

Each `curated_domain` must include `domain_id`, `definition`,
`region_relevance`, `scoreability_note`, `source_domain_ids`, `source_runs`,
`proposal_frequency`, and `consolidation_rationale`. `proposal_frequency` must
equal `len(source_runs)`.

The required `emotion_experience` curated domain is vmPFC-specific. For vmPFC
domain pools, it must preserve the `required_emotion_experience` seed in
`source_domain_ids`, source run `0` in `source_runs`, and the canonical
viewer-centric seed definition exactly. Proposal prompts must show the complete
required anchor definition before candidate generation; consolidation prompts
must treat the anchor as a contract rather than ordinary candidate wording.
Other ROIs must not receive this seed or validation requirement automatically;
they may retain an emotion-related domain only when discovery and human review
keep it as target-region relevant. The `emotion_*` prefix must belong to
`emotion_experience` only for vmPFC's required core emotion panel; non-vmPFC
schemas may place emotion-related dimensions under the most specific confirmed
domain that defines the scoreable variable.

Each `rejected_or_merged_domain` must include `domain_id`, `decision`,
`reason`, and `source_domain_ids`; `merged_into` is optional.

`region_schema_v1.json` is the active-dimension contract for scoring. It has no
module layer. It must contain region-level `functional_hypothesis`,
`scoring_instruction`, `selection_rules`, full confirmed `domains`,
`active_domain_ids`, and active `dimensions`. Active dimensions should include
`domain`, `trigger_list`, `graded_anchors`, `calibration_examples`,
`scoreability_note`, and `exclusion_note`. New active dimensions use a unified
0-10 scale and should not write legacy `low_anchor`, `high_anchor`, display
`name`, or module fields.

Confirmed domain IDs are coarse grouping labels, not direct score columns.
Schema generation must infer concrete, text-scoreable sub-variables under each
retained domain. A generated `dimension_id` must not repeat its own `domain`
value or reuse any confirmed `domain_id`; each retained non-emotion domain must
contribute 3 to 8 active dimensions, while `emotion_experience` follows the
separate emotion-panel cardinality contract.

For vmPFC schemas, prompts should use `emotion_experience` as the reference
granularity for active dimensions. For non-vmPFC schemas, do not mention or
force the vmPFC emotion panel unless `emotion_experience` is present in the
confirmed domain pool. Non-emotion domains should split broad umbrella
constructs into a small number of discrete, text-scoreable, non-redundant
numeric dimensions when the split captures distinct target-region variables.

### 4. Validation & Error Matrix

- `DomainPool.curation_status` not in `draft|confirmed` -> `ValueError`
- empty `candidate_domains` or `curated_domains` -> `ValueError`
- duplicate curated `domain_id` -> `ValueError`
- curated domain missing `source_domain_ids`, `source_runs`,
  `proposal_frequency >= 1`, or `consolidation_rationale` -> `ValueError`
- curated domain `proposal_frequency != len(source_runs)` -> `ValueError`
- vmPFC required `emotion_experience` missing `required_emotion_experience`
  source evidence or source run `0` -> `ValueError`
- vmPFC required `emotion_experience` definition differs from the canonical
  viewer-centric seed definition -> `RuntimeError` naming the
  canonical-definition violation
- rejected/merged domain missing `reason` or `source_domain_ids` -> `ValueError`
- `make-region-schema --domain-pool` with non-confirmed pool -> `ValueError`
- domain-pool `target_region` mismatches CLI `--target-region` -> `ValueError`
- generated active dimension missing `domain`, `trigger_list`,
  `graded_anchors`, `calibration_examples`, `scoreability_note`, or
  `exclusion_note` -> `ValueError`
- generated active dimension reuses a confirmed `domain_id` as `dimension_id`
  -> `ValueError`
- generated non-emotion domain contributes fewer than 3 or more than 8 active
  dimensions -> `ValueError`
- generated active dimension not using `score_min=0` and `score_max=10` ->
  `ValueError`
- generated active dimension missing any `graded_anchors` key from `0` through
  `10` -> `ValueError`
- generated target-region schema total active-dimension count -> not a
  validation error; review the actual dimension count in the schema artifact
- vmPFC schema missing required `emotion_experience` or core `emotion_*`
  dimensions -> `ValueError`
- non-vmPFC schema missing `emotion_experience` or core emotion dimensions ->
  allowed unless that ROI-specific contract is explicitly added later
- non-vmPFC schema uses an `emotion_*` dimension under a non-`emotion_experience`
  domain -> allowed when that domain is confirmed for the ROI

### 5. Good/Base/Bad Cases

- Good: `make-domain-pool` writes a `draft` pool; user reviews and edits it to
  `confirmed`; `make-region-schema --domain-pool` generates a region schema with
  `metadata.domain_pool` provenance and valid active dimensions.
- Base: `make-region-schema` requires `--domain-pool`; no free-generation path
  exists.
- Bad: passing an unreviewed `draft` pool into `make-region-schema` succeeds;
  this must be rejected before any active dimensions are generated.
- Bad: generated `dimensions` are a 1:1 copy of confirmed `domain_id` values;
  this must be rejected because it scores coarse domains directly instead of
  concrete sub-variables.
- Bad: generated non-emotion domains each receive only 1-2 dimensions; this is
  too coarse for the intended vmPFC-aligned scoring granularity.

### 6. Tests Required

- CLI help exposes `make-domain-pool`, `make-region-schema --domain-pool`, and
  existing `score-descriptions` behavior.
- Domain-pool serialization rejects missing audit fields and preserves
  candidate/curated/rejected records.
- Domain-pool prompt tests assert viewer-centric perspective, required-anchor
  rendering, and that candidate JSON is treated as evidence rather than hidden
  rules.
- Domain-pool generation rejects consolidation when the required
  `emotion_experience` canonical definition drifts.
- `make-region-schema --domain-pool` rejects draft pools and region mismatches.
- Confirmed-pool generation records provenance metadata, including content hash
  and curated domain IDs.
- Dimension metadata round-trips through `DimensionSpec`.
- Scorer prompt renders `domain`, `trigger_list`, `graded_anchors`,
  `calibration_examples`, `scoreability_note`, and `exclusion_note`.
- Required validation still passes:
  `uv run python -m unittest discover -s tests -p 'test_*.py'` and
  `uv run python -m compileall brain_region_pipeline tests`.

### 7. Wrong vs Correct

#### Wrong

```text
make-region-schema --domain-pool vmpfc_domain_pool.json
# vmpfc_domain_pool.json still has "curation_status": "draft"
# command silently generates active dimensions
```

#### Correct

```text
make-domain-pool -> draft domain_pool_v2.json
human review/edit -> "curation_status": "confirmed"
make-region-schema --domain-pool confirmed_domain_pool.json
score-descriptions --region-schema region_schema.json
```

Domain pools are audit/control artifacts. They are not direct encoding features,
and inactive candidate domains must not be encoded as zero-valued feature
columns.

## Scenario: Rolling Summary Generation

### 1. Scope / Trigger

- Trigger: changes touching `summarize-descriptions`,
  `summary_generator.py`, dense-description parsing for summary inputs, or
  `summary.json` / `summary_metadata.json` contracts.
- This is a cross-layer contract: CLI args, description parser behavior,
  prompt structure, structured JSON schema, generated summary rows, scoring
  Story Context consumption, README, and tests must stay aligned.

### 2. Signatures

- `uv run python -m brain_region_pipeline summarize-descriptions --descriptions <description.md> --output-file <summary.json>`

### 3. Contracts

- The first version processes one description file per invocation. It does not
  perform directory batch generation or resume partial summaries.
- The CLI does not expose `--model` or batch-size flags. It uses the pipeline
  default Gemini model from `GenerationConfig` and a fixed summary batch size of
  40 description segments.
- `description_io.py` must parse both blank-line separated timestamp blocks and
  Friends-style Markdown files where timestamped segments appear on consecutive
  lines after metadata such as `**Movie:**` and `---`.
- Summary generation is causal. Batch 0 uses a beginning-of-movie placeholder;
  batch N receives only the previous batch's `cumulative_summary` plus the
  current batch's timestamped descriptions. It must not use future batch text.
- `summary.json` is a JSON array compatible with the Fallen notebook contract.
  Each row must include `batch_idx`, `segment_start`, `segment_end`,
  `timestamp_range`, `batch_summary`, and `cumulative_summary`.
- `summary_metadata.json` is written beside `summary.json` and records command
  provenance, input/output paths, model, summary batch size, segment count, batch
  count, generation timestamp, and prompt contract notes.
- Writes happen after all batches succeed. Do not leave a partial `summary.json`
  after a mid-run model failure.

### 4. Validation & Error Matrix

- no parsed description segments -> `ValueError`
- `summary_batch_size < 1` -> `ValueError`
- Gemini generation failure for any batch -> `RuntimeError` with batch context
- missing or empty `batch_summary` -> `ValueError`
- missing or empty `cumulative_summary` -> `ValueError`

### 5. Good/Base/Bad Cases

- Good: a Friends `refined_description.md` with Markdown metadata and 333
  timestamp lines produces nine Fallen-compatible summary rows when using the
  fixed 40-segment batch size.
- Base: a legacy blank-line separated description file still parses and
  summarizes without format conversion.
- Bad: using an episode-global summary as Story Context for every scoring batch;
  that leaks future narrative context into early segments.
- Bad: zero-filling or skipping a failed summary batch and continuing; all later
  cumulative summaries would be contaminated.

### 6. Tests Required

- Parser regression covers Friends Markdown metadata and consecutive timestamp
  lines without blank separators.
- Summary generator test covers rolling use of prior `cumulative_summary`, row
  indexes, and `timestamp_range`.
- CLI test covers `summary.json`, `summary_metadata.json`, fixed batch size of
  40, and absence of `--model` in help.
- Empty input test verifies fail-fast behavior.

### 7. Wrong vs Correct

#### Wrong

```text
score-descriptions --summary-file friends/.../running_summary.json
# running_summary.json is an episode-global {"summary": "..."} object, so early
# scoring batches see future plot events.
```

#### Correct

```bash
uv run python -m brain_region_pipeline summarize-descriptions \
  --descriptions friends/.../descriptions/refined_description.md \
  --output-file friends/.../summary.json

uv run python -m brain_region_pipeline score-descriptions \
  --descriptions friends/.../descriptions/refined_description.md \
  --summary-file friends/.../summary.json \
  --region-schema vmpfc_region_schema.json \
  --output-dir friends/.../scored
```

## Scenario: Context-Enhanced Batch Description Scoring

### 1. Scope / Trigger

- Trigger: changes touching `score-descriptions`, `region_schema_scorer.py`,
  GT CSV alignment, `segment_region_scores.jsonl`, `segment_gt_means.jsonl`, or
  `scoring_metadata.json`.
- This is a cross-layer contract: CLI args, generation prompt structure,
  structured JSON schema, failure behavior, GT CSV averaging, docs, and tests
  must stay aligned.

### 2. Signatures

- `uv run python -m brain_region_pipeline score-descriptions --descriptions <description.txt> --region-schema <region_schema.json> --output-dir <out_dir> [--summary-file <summary.json>] [--scoring-batch-size 40] [--local-buffer-size 10] [--gt-dir <csv_dir>] [--gt-file-pattern '*.csv'] [--gt-time-column '视频时间(s)'] [--gt-emotion-column '情绪值'] [--model <model>] [--tr-s 1.49] [--total-trs <n>] [--alignment overlap_weighted|repeat]`

### 3. Contracts

- Batch scoring prompt has three sections:
  - `Story Context`: previous batch `cumulative_summary` from notebook-style
    `summary.json`, or a beginning-of-movie placeholder for batch 0.
  - `Local Buffer`: prior description segments for continuity only; they must
    not receive output scores.
  - `Target Segments`: the only segments that must receive scores.
- Default batch settings replicate the Fallen notebook: 40 target segments per
  request and 10 prior local-buffer segments.
- Batch responses must be a JSON object with `segment_scores`; each item must
  include `segment_id`, `timestamp`, and flat `dimension_scores`.
- The LLM response schema must require numeric `dimension_scores` keyed by the
  fixed dimension IDs from `region_schema.json`, but must not require or ask for
  `rationale`. Scoring prompts should tell the model to use evidence and anchors
  internally while outputting scores only.
- `SegmentRegionScore.rationale` remains a local field for failure zero-fill
  reasons; new successful LLM scoring responses should leave it empty.
- `segment_region_scores.jsonl` remains one row per original description
  segment; batch scoring must not merge target segments into coarse windows.
- Partial or resumed scoring must preserve original segment indexes and original
  batch boundaries. Do not slice the remaining descriptions into a fresh input
  file unless the reset of Story Context / Local Buffer semantics is intentional.
  If a resume start index is divisible by `--scoring-batch-size`, resume at
  `batch_idx = start_index / scoring_batch_size` against the full segment list
  so prior segments still serve as Local Buffer reference context.
- When `--gt-dir` is supplied, GT CSVs are averaged using the notebook scheme:
  infer emotion from filename, average raw values across subjects at each time
  point, then average the resulting time series over each segment's
  `[start_s, end_s)` interval. This writes `segment_gt_means.jsonl`.

### 4. Validation & Error Matrix

- `--scoring-batch-size < 1` -> `ValueError`
- `--local-buffer-size < 0` -> `ValueError`
- `--summary-file` not containing a JSON array -> `ValueError`
- missing or unusable `--gt-dir` CSV files -> `ValueError`
- full batch generation failure -> zero-fill all target segments, append a
  `batch_generation_failed_zero_filled` warning, continue the run
- response missing a target `segment_id` -> zero-fill that segment, append a
  `missing_segment_zero_filled` warning, continue the run
- response missing a required dimension -> zero-fill that dimension, append a
  `missing_dimensions_zero_filled` warning, continue the run

### 5. Good/Base/Bad Cases

- Good: `summary.json` plus dense descriptions produce 40 target segment scores
  per request, with the previous 10 segments as context and multi-dimensional
  vmPFC scores preserved per original segment.
- Base: omit `--summary-file` and `--gt-dir`; scoring still runs with batch
  prompt context placeholders and writes the existing score/TR outputs.
- Bad: concatenate 40 target descriptions into one coarse segment score; this
  destroys segment-level GT comparison and must not be done.
- Bad: score Local Buffer segments or include them in `segment_region_scores`;
  they are reference context only.

### 6. Tests Required

- Batch scorer prompt includes Story Context, Local Buffer, Target Segments, and
  renders region-schema dimensions with `domain`, `scoreability_note`, and
  `exclusion_note`.
- Batch scorer prompt and schema do not request rationale, while preserving
  dimension-id keyed scores.
- Batch scorer maps returned `segment_id` values back to original description
  segments and preserves per-dimension scores.
- Failed batch and missing segment/dimension cases zero-fill and record warning
  metadata instead of aborting the whole run.
- GT CSV averaging test covers raw cross-subject averaging before segment
  resampling.
- CLI/runner test covers `--gt-dir` writing `segment_gt_means.jsonl` and GT
  metadata.

### 7. Wrong vs Correct

#### Wrong

```text
Target Segments 0-39 are merged into one request and the response contains one
single agitation score for the whole block.
```

#### Correct

```text
Story Context: summary for batches before 0-39
Local Buffer: previous 10 segments, reference only
Target Segments: segment_id 0 ... 39
Response: one flat dimension_scores object per target segment_id; no generated
          rationale
```
