# brainstorm: refine annotation dimensions

## Goal

Refine the meta-prompt so generated region-level annotation dimensions are less coarse and more operational for downstream movie-fMRI scoring. In particular, broad affect/emotion dimensions should either be decomposed into concrete scoreable variables or carry explicit emotion-category guidance, so the scorer does not collapse distinct emotional evidence into a generic valence feature.

## What I already know

* The user wants the current meta-prompt-generated annotation dimensions to be more detailed.
* The concrete example is emotion: instead of a coarse "emotion" or "emotional valence" dimension, the generated prompt should specify which emotions or emotion families should be considered.
* The vmPFC test should be the first pilot for this finer-grained schema. Other regions should later use the vmPFC schema as a granularity reference after the vmPFC test quality is acceptable.
* Social and related dimensions should follow the same granularity principle as emotion: more specific than umbrella labels, but not so specific that downstream encoding overfits.
* User prefers concrete subtargets to become multiple independent numeric dimensions rather than being hidden inside one broad dimension definition or rationale.
* Current preferred granularity cap is about 10 dimensions per broad domain.
* Candidate dimensions and active encoding dimensions must be distinguished: candidates are for pilot review; only active dimensions are scored and used for encoding.
* The vmPFC pilot should start with about 20 total active dimensions.
* The meta-prompt should first infer broad domains for the target region, then decide how many active dimensions each domain receives based on vmPFC relevance, scoreability, and non-redundancy.
* Each generated dimension should carry an optional formal `domain` field so active dimensions can be grouped by broad domain in later analysis.
* User prefers a multi-run domain discovery workflow: run the meta-prompt multiple times to propose domains, remove functionally redundant domains, form a curated domain pool, then use the whole domain pool to guide detailed dimension generation and scoring.
* The initial domain pool should be vmPFC-specific. Cross-region domain pools are deferred until the vmPFC pilot is good enough to serve as a reference.
* The curated vmPFC domain pool should be saved as a separate JSON artifact before final module-prompt generation.
* The domain-pool artifact should preserve candidate domains, curated domains, and rejected/merged domains with reasons.
* Domain proposal runs should not be seeded with hand-authored functional lenses. Each run should independently infer vmPFC-relevant domains from the same target-region and atlas context.
* Multiple domain proposal runs are not intended to rely on randomness for diversity. They are used to reduce omission risk and to identify robust domains that appear repeatedly.
* Domain consolidation should prioritize recurring domains while still allowing single-run domains that are theoretically important, scoreable, and non-redundant.
* Generated active dimensions should pass a static quality screen before they are used for scoring or encoding.
* Active dimensions should use a unified 0-5 intensity scale by default.
* Signed valence should not be included in the default active vmPFC schema. If needed, valence can be evaluated later as a separate ablation/baseline feature group.
* Each active dimension should include a `scoreability_note` explaining what text-only evidence should be used to score that dimension from dense descriptions.
* Each active dimension should include an `exclusion_note` explaining nearby concepts that should not be counted toward the dimension.
* Domain consolidation should be LLM-assisted but human-confirmed: the LLM proposes merges/rejections with rationale, then the curated pool is accepted before detailed dimension generation.
* Initial vmPFC domain proposal should run the meta-prompt 5 times before consolidation.
* CLI design should keep domain-pool generation separate from final module-prompt generation.
* Human confirmation can be handled by manually editing the generated domain-pool JSON. No interactive confirmation UI is required for the first implementation.
* The domain-pool JSON should include `curation_status`. Generated pools default to `draft`, and final module-prompt generation should require `confirmed`.
* Final `module_prompt.json` should record domain-pool provenance when generated from a confirmed pool.
* `ModulePromptPool` should gain a backward-compatible top-level `metadata` mapping for provenance such as domain-pool hash, prompt version, and generation parameters.
* The domain pool should not include fixed detailed dimension lists. It should define broad domains only; detailed active dimensions are generated in the later module-prompt stage.
* Current maintained package boundary is `brain_region_pipeline`, with `make-module-prompt` generating `module_prompt.json` and `score-descriptions` consuming it.
* `brain_region_pipeline/module_prompt.py` owns the meta-prompt and response schema for generated dimensions.
* `brain_region_pipeline/models.py` owns the serialized `DimensionSpec` contract.
* `brain_region_pipeline/module_scorer.py` renders generated dimensions and anchors into the scoring prompt.
* Existing docs already identify that coarse vmPFC schemas can drift back to `emotional_valence` and lose reward/self/internal distinctions.

## Assumptions

* The user wants a design proposal first and does not want code changed until explicit confirmation.
* The intended change should preserve the current single-region module design and avoid reintroducing old video annotation or embedding pipeline code.
* More detailed dimensions should remain scoreable from text-only dense descriptions.

## Requirements

* Improve granularity of generated annotation dimensions.
* Preserve high cohesion and low coupling: schema contract, meta-prompt text, scorer rendering, tests, and docs should be updated in the modules that own those responsibilities.
* Do not hard-code one universal emotion list as the only output; the generated dimensions should still be brain-region-aware.
* Provide enough guidance that broad emotion-related variables can be decomposed into concrete categories such as fear/anxiety, sadness/loss, anger/frustration, joy/relief, affection/warmth, guilt/shame, surprise/tension, etc., when they are relevant.
* Use vmPFC as the first schema calibration target. The schema should balance interpretability, evidence coverage, and feature count before generalizing this granularity to other regions.
* Refine non-emotion domains with comparable granularity, for example splitting broad social/value/internal-state labels into a small number of scoreable subdimensions when they represent distinct vmPFC-relevant variables.
* Represent accepted fine-grained subtargets as separate numeric dimensions, so downstream encoding can use them as distinct feature columns.
* Keep scoring outputs numeric and compatible with `ordered_feature_keys()` unless a deliberate contract change is accepted.
* Avoid excessive feature proliferation because later fMRI encoding may overfit if many sparse or highly correlated fine-grained dimensions are added.
* Treat 10 dimensions per broad domain as the current upper-bound candidate unless later clarified as a fixed target.
* Do not encode inactive candidate dimensions as zero-valued columns. A zero score means an active dimension is absent in a segment; it must not mean a candidate was never scored.
* The first vmPFC active schema should target about 20 total dimensions after candidate review.
* Do not pre-assign a fixed quota for each broad domain. The meta-prompt should output broad domains first, then allocate active dimensions across domains according to the target region's functional hypothesis.
* Extend the dimension JSON contract with a backward-compatible optional `domain` field. Existing prompt JSON files without `domain` should still load.
* Add a domain-pool workflow concept:
  * domain proposal: run the meta-prompt multiple times to generate candidate broad domains for vmPFC;
  * domain consolidation: merge or remove functionally redundant domains and keep distinct, scoreable, vmPFC-relevant domains;
  * dimension generation: generate detailed active dimensions conditioned on the curated domain pool.
* Treat the domain pool as a controlled intermediate artifact, not as direct encoding features. Encoding still uses active dimensions generated from the pool.
* Build only a vmPFC-specific domain pool in this task. Do not generalize it into a global cross-region pool yet.
* Persist the vmPFC domain pool separately from `module_prompt.json`. The final `module_prompt.json` should be generated from, or explicitly absorb, the active domains in that pool.
* The separate domain-pool artifact should make the multi-run domain proposal and consolidation process auditable before detailed dimensions are generated.
* The domain-pool JSON should include at least `candidate_domains`, `curated_domains`, and `rejected_or_merged_domains`.
* Each rejected or merged domain should keep a short reason explaining redundancy, weak vmPFC relevance, poor scoreability, or excessive overlap.
* Domain consolidation should not be fully automatic. The LLM can cluster overlapping domains and propose the curated pool, but a human confirmation step should approve or edit the pool before active dimensions are generated.
* Use 5 domain-proposal runs as the initial default for vmPFC. This should provide diversity without creating excessive consolidation burden.
* Keep domain proposal discovery-driven: do not pre-assign lenses such as value, emotion, social, self, or moral before running the meta-prompt. Diversity should come from multiple independent generations, not from manual category prompts.
* Do not deliberately increase randomness just to force diverse domains. Repeated domain appearances across runs should be treated as evidence that a domain is important and should usually be retained.
* Domain-pool consolidation should track proposal frequency or source run references for each curated domain so repeated findings remain visible.
* Consolidation retention rules:
  * prioritize domains that appear across multiple proposal runs;
  * keep single-run domains when they are vmPFC-relevant, scoreable from dense descriptions, and not redundant with stronger domains;
  * merge domains with highly overlapping functional meaning or evidence requirements;
  * reject domains that are too broad, too narrow, weakly vmPFC-relevant, or not reliably scoreable from text.
* Add a first-pass static active-dimension quality screen. Each active dimension should have a clear domain, non-overlapping definition, 0-baseline score range, clear low/high anchors, text-only scoreability, and the total active dimension count should stay near the vmPFC target of about 20.
* Use `score_min=0` and `score_max=5` for active dimensions unless a future explicitly justified exception is added. `0` means the psychological/emotional component is absent or cannot be judged from the text; `5` means it is strongly present.
* Do not use signed valence as a default active emotion dimension because its neutral midpoint conflates absence, mixed affect, and unknown evidence. Prefer concrete 0-5 intensity dimensions such as anxiety/threat, sadness/loss, anger/frustration, warmth/affection, joy/relief, guilt/shame, or similar categories inferred from the confirmed domain pool.
* If signed valence is useful later, treat it as an explicit comparison feature group outside the main active schema, not as one of the default approximately 20 active dimensions.
* Extend the dimension JSON contract with a backward-compatible optional `scoreability_note` field. The note should specify concrete dense-description cues such as character actions, dialogue content, inferred internal state evidence, social interaction patterns, reward/loss events, or narrative consequences that justify the score.
* Extend the dimension JSON contract with a backward-compatible optional `exclusion_note` field. The note should define boundaries against adjacent dimensions so the scorer does not double-count conceptually overlapping evidence.
* The scorer prompt should show `scoreability_note` with each dimension so the scoring model uses the intended evidence and does not free-associate beyond the input description.
* The scorer prompt should also show `exclusion_note` with each dimension when available.
* Do not add complex statistical or encoding-result-based dimension selection in the first implementation. Distribution/correlation checks can be added after pilot scoring outputs exist.
* Add a dedicated `make-domain-pool` command that reads atlas labels and target region, runs domain proposal/consolidation, and writes the vmPFC domain-pool JSON.
* Keep `make-module-prompt` as the final active-dimension generator, with an optional `--domain-pool <domain_pool.json>` argument to condition generation on curated domains.
* Do not turn `make-module-prompt` into a single all-in-one multi-stage command.
* After `make-domain-pool`, the user can manually edit `curated_domains` and `rejected_or_merged_domains` in the JSON before passing it to `make-module-prompt --domain-pool`.
* Do not build an interactive review UI or prompt-by-prompt approval flow in the first implementation.
* `make-domain-pool` should write `"curation_status": "draft"` by default.
* `make-module-prompt --domain-pool` should reject draft domain pools by default and require `"curation_status": "confirmed"` before generating active dimensions.
* A bypass flag such as `--allow-draft-domain-pool` can be considered later, but should not be part of the default safe path unless explicitly needed.
* When `make-module-prompt --domain-pool` is used, the saved module prompt should include provenance metadata such as domain-pool version, source path, or content hash so schema comparisons remain auditable.
* Add a generic top-level `metadata` field to module-prompt output rather than adding one-off provenance fields. Old module-prompt JSON files without metadata should still load.
* Keep domain-pool responsibilities narrow: store broad domain IDs, names, definitions, vmPFC relevance, scoreability notes, source proposal references, and consolidation rationale. Do not store fixed candidate dimension lists in the domain pool.
* Detailed dimension generation belongs to `make-module-prompt --domain-pool`, which reads the confirmed broad-domain pool and then creates the approximately 20 active dimensions.

## Acceptance Criteria

* [ ] `_build_prompt()` instructs the model to avoid overly broad catch-all dimensions and prefer concrete scoreable subdimensions when a category is heterogeneous.
* [ ] Emotion-related dimensions are guided to name concrete emotion families or subtargets, not only signed valence.
* [ ] The vmPFC schema has an explicit target granularity range that can later guide other brain regions.
* [ ] Non-emotion dimensions are also reviewed for overly broad labels and decomposed only when the split creates distinct, scoreable predictors.
* [ ] Generated dimensions are independent numeric feature columns, not only textual sublabels inside a coarse dimension.
* [ ] The workflow distinguishes candidate dimensions from active dimensions used for scoring and encoding.
* [ ] The vmPFC pilot active schema targets about 20 total dimensions.
* [ ] The generated schema includes broad domains and a justified active-dimension allocation across those domains.
* [ ] Each active dimension can include a formal `domain` field, and older JSON files without `domain` remain compatible.
* [ ] The workflow supports domain-pool discovery and consolidation before detailed dimension generation.
* [ ] The vmPFC domain pool is persisted as a separate JSON artifact before final active-dimension generation.
* [ ] The domain-pool artifact preserves candidates, curated domains, and rejected/merged domains with rationale.
* [ ] Domain consolidation is LLM-assisted and requires human confirmation before detailed dimension generation.
* [ ] The vmPFC domain proposal stage defaults to 5 meta-prompt runs.
* [ ] Domain proposal runs infer domains without pre-seeded functional lenses.
* [ ] Domain proposal runs are used for omission control and recurrence evidence, not randomness-driven diversity.
* [ ] Curated domains preserve occurrence/source-run evidence from the proposal stage.
* [ ] Domain consolidation follows explicit retain/merge/reject rules based on recurrence, relevance, scoreability, and redundancy.
* [ ] Generated active dimensions pass a static quality screen before downstream scoring/encoding use.
* [ ] Active dimensions use a unified 0-5 intensity scale with a true zero baseline.
* [ ] Signed valence is excluded from the default active schema and reserved for optional ablation/baseline comparison.
* [ ] Each active dimension can include `scoreability_note`, and the scorer sees it when assigning scores.
* [ ] Each active dimension can include `exclusion_note`, and the scorer sees it when assigning scores.
* [ ] CLI exposes a separate `make-domain-pool` stage and an optional `--domain-pool` input for `make-module-prompt`.
* [ ] Human confirmation is supported through manual JSON editing, without adding an interactive UI.
* [ ] Domain-pool JSON has a `curation_status` gate, and final prompt generation refuses unconfirmed pools by default.
* [ ] Module-prompt output records provenance for the confirmed domain pool used to generate active dimensions.
* [ ] `ModulePromptPool` supports a backward-compatible top-level `metadata` field.
* [ ] Domain-pool JSON stores broad-domain structure only and does not fix detailed dimension lists.
* [ ] If the serialized dimension contract is extended, `DimensionSpec`, JSON schema, scorer rendering, README, and tests are updated together.
* [ ] Unit tests cover the new prompt/schema expectations.
* [ ] Validation uses `uv run python -m unittest discover -s tests -p 'test_*.py'` and `uv run python -m compileall brain_region_pipeline tests`.

## Out of Scope

* Reintroducing old `test_pipeline` video slicing, clip annotation, embedding cache, or local LLM embedding code into `brain_region_pipeline`.
* Running live Gemini generation unless explicitly requested.
* Changing fMRI encoding logic or adding ROI model training in this task.
* Automatically applying the finalized vmPFC granularity to all other brain regions before the vmPFC pilot is accepted.
* Building a cross-region/global domain pool before the vmPFC-specific pool is validated.

## Technical Notes

* Relevant code files inspected:
  * `brain_region_pipeline/module_prompt.py`
  * `brain_region_pipeline/models.py`
  * `brain_region_pipeline/module_scorer.py`
  * `tests/test_brain_region_description_workflow.py`
  * `README.md`
  * `docs/brain_region_pipeline_vmpfc_review.md`
  * `docs/vmpfc_demo_results_summary_20260508.md`
* Backend spec says serialized JSON field names and feature ordering changes must be synchronized with tests and README.
* Prior project notes recommend keeping appraisal/emotion distributions as numeric features and using rationale text only as an auxiliary explanation.
