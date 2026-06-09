# Region Schema Contract Migration

## Goal

Refactor the brain-region prompt pipeline from the old module-prompt contract into a cleaner `domain_pool_v2 -> region_schema_v1 -> score-descriptions` flow. The new contract removes the `module` abstraction, keeps a clear `domain -> dimension` structure, and adds a required `emotion_experience` domain with a controlled emotion panel that includes `emotion_agitation` for downstream Fallen GT validation without making the schema Fallen-specific.

## What I Already Know

- The current pipeline uses `make-domain-pool -> make-module-prompt -> score-descriptions`.
- Current code stores active dimensions under `ModulePromptPool.modules[].dimensions[]`.
- The user wants to remove the module concept entirely rather than preserve deprecated aliases or old JSON compatibility.
- `make-region-schema` must require a confirmed domain pool.
- `score-descriptions` remains as the command name, but it should accept `--region-schema` instead of `--module-prompt`.
- Old JSON contracts and old CLI aliases do not need compatibility; git history is sufficient.

## Requirements

- Replace `module_prompt_v1` with `region_schema_v1`.
- Upgrade domain pool output to `domain_pool_v2`.
- Inject a required `emotion_experience` domain seed into domain-pool generation with `source_run = 0`.
- Preserve the required seed in `candidate_domains` as `required_emotion_experience`.
- Ensure curated domains include `emotion_experience`.
- Keep `proposal_frequency = len(source_runs)`, including `source_run = 0`, for a simple contract.
- Remove `module_id`, `modules[]`, `display_name`, and `simulation_prompt`.
- Rename `simulation_prompt` semantics to top-level `scoring_instruction`.
- Keep top-level `functional_hypothesis`.
- Remove `name` from dimensions and domains.
- Keep full confirmed domain fields in `region_schema.domains`.
- Add top-level `active_domain_ids`, ordered according to `domains`.
- Use global `dimension_id` as the feature key; keep domain mapping through `dimensions[].domain`.
- Output segment scores with top-level `dimension_scores`, not nested `module_scores`.
- Output TR feature vectors using normalized `region_schema.dimensions` order and save matching `feature_names`.

## Emotion Experience Contract

- `emotion_experience` is a required domain.
- It represents inferred emotional experience of a typical viewer, grounded only in dense-description evidence such as narrative situation, character state, dialogue, actions, consequences, and scene atmosphere.
- `emotion_experience` dimensions must use `emotion_<label>`.
- Allowed labels:
  - `admiration`
  - `amusement`
  - `excitement`
  - `joy`
  - `amazement`
  - `contentment`
  - `relief`
  - `tenderness`
  - `compassion`
  - `confusion`
  - `surprise`
  - `agitation`
  - `anguish`
  - `disappointment`
  - `uneasiness`
  - `disgust`
  - `contempt`
  - `fear`
  - `anger`
  - `sadness`
- Core required labels:
  - `admiration`
  - `amusement`
  - `joy`
  - `tenderness`
  - `confusion`
  - `surprise`
  - `agitation`
  - `sadness`
- `emotion_agitation` is the validation anchor for Fallen GT, but `region_schema` must not include Fallen-specific metadata.
- `emotion_experience` must contain 8 to 12 emotion dimensions.
- No non-`emotion_<label>` dimensions are allowed under `emotion_experience`.
- If a dimension id starts with `emotion_`, its domain must be `emotion_experience`.

## Region Schema Contract

`region_schema_v1` top-level shape:

```json
{
  "version": "region_schema_v1",
  "target_region": "vmPFC",
  "functional_hypothesis": "...",
  "scoring_instruction": "...",
  "selection_rules": [],
  "domains": [],
  "active_domain_ids": [],
  "dimensions": [],
  "metadata": {}
}
```

Dimension shape:

```json
{
  "dimension_id": "emotion_agitation",
  "definition": "...",
  "domain": "emotion_experience",
  "score_min": 0,
  "score_max": 10,
  "trigger_list": [],
  "graded_anchors": {},
  "calibration_examples": [],
  "scoreability_note": "...",
  "exclusion_note": "..."
}
```

## Ordering

- Do not rely on prompt instructions for ordering.
- The LLM should generate semantic content; code should normalize output order.
- Final `region_schema.dimensions`, `feature_names`, and `feature_vector` must use the same normalized order.
- Ordering rule:
  - group dimensions by `domains` order;
  - inside `emotion_experience`, place core emotion dimensions first in code-constant order, then other emotion dimensions in generated order;
  - inside all other domains, preserve generated order.

## Acceptance Criteria

- [ ] CLI help lists `make-domain-pool`, `make-region-schema`, and `score-descriptions`.
- [ ] CLI help no longer lists `make-module-prompt`.
- [ ] `make-region-schema` requires `--domain-pool`.
- [ ] Domain pool generation outputs `domain_pool_v2` with required `emotion_experience` provenance.
- [ ] Confirmed domain pool loading rejects missing required domains.
- [ ] Region schema generation outputs `region_schema_v1` without `modules[]`.
- [ ] Region schema validation enforces the emotion panel contract.
- [ ] Scoring output uses top-level `dimension_scores`.
- [ ] TR output metadata uses `feature_names` / dimension ids, not module/dimension pairs.
- [ ] Unit tests pass with `uv run python -m unittest discover -s tests -p 'test_*.py'`.

## Out of Scope

- Preserve compatibility with old `module_prompt_v1` JSON.
- Preserve `make-module-prompt` as a deprecated alias.
- Add CLI configuration for required domain seeds.
- Add Fallen-specific metadata to `region_schema`.
- Re-run live Gemini scoring or regenerate large demo artifacts unless needed for tests.

## Technical Notes

- Primary files expected to change:
  - `brain_region_pipeline/models.py`
  - `brain_region_pipeline/domain_pool.py`
  - `brain_region_pipeline/module_prompt.py` renamed/reworked as `region_schema.py`
  - `brain_region_pipeline/module_scorer.py` renamed/reworked as `region_schema_scorer.py`
  - `brain_region_pipeline/cli.py`
  - `brain_region_pipeline/runner.py`
  - `brain_region_pipeline/score_aligner.py`
  - `brain_region_pipeline/atlas.py`
  - `brain_region_pipeline/tr_output.py`
  - `tests/*`
  - `README.md`
  - `docs/*`
- Use UV for Python commands.
- This is a data-contract migration; tests should focus on model validation, CLI command shape, scorer schema, and runner output contracts.
