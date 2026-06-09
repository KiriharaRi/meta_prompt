# Switch Default AIHubMix Model To DeepSeek

## Goal

Switch the maintained AIHubMix default generation model from Xiaomi MiMo
(`xiaomi-mimo-v2.5-pro`) to DeepSeek (`deepseek-v4-pro`) because the current
MiMo domain-pool stage can return output that does not satisfy the agreed
`domain_pool_v2` schema.

## What I Already Know

- The user provided the AIHubMix DeepSeek model id: `deepseek-v4-pro`.
- A live probe with `make-domain-pool --provider aihubmix --model deepseek-v4-pro`
  succeeded for `proposal-runs=1`.
- A second live probe with `proposal-runs=5` also succeeded and wrote a valid
  draft domain pool to `/private/tmp/deepseek_domain_pool_probe_5runs.json`.
- The 5-run probe passed field-presence checks for candidate, curated, and
  rejected/merged domain records.
- The existing provider should remain `aihubmix`; only the default model changes.

## Requirements

- Update the default AIHubMix generation model to `deepseek-v4-pro`.
- Keep `generation_provider = "aihubmix"` as the default provider.
- Update the Friends multi-ROI pilot config to use the new default model.
- Update README examples/contracts so documented defaults match the code.
- Update tests that assert or describe the default model.
- Avoid changing provider routing, JSON parsing behavior, prompt content, or
  domain-pool schema contracts in this task.

## Acceptance Criteria

- [ ] `DEFAULT_GENERATION_MODEL` is `deepseek-v4-pro`.
- [ ] `configs/friends_multi_roi_pilot.json` uses `deepseek-v4-pro`.
- [ ] README default model text and `domain_pool_v2` example use
  `deepseek-v4-pro`.
- [ ] Tests no longer refer to Xiaomi MiMo as the default model.
- [ ] Relevant unit tests pass.
- [ ] `uv run python -m compileall brain_region_pipeline tests` passes.

## Definition Of Done

- Minimal code/config/doc/test edits only.
- Existing AIHubMix and Gemini provider boundaries are preserved.
- No generated caches or probe outputs are left in the repo.

## Out Of Scope

- Changing AIHubMix request format or structured-output parsing.
- Adding a model-specific compatibility layer.
- Running the full multi-ROI pilot.
- Committing changes.

## Technical Notes

- Relevant implementation files:
  - `brain_region_pipeline/config.py`
  - `configs/friends_multi_roi_pilot.json`
  - `README.md`
  - `tests/test_brain_region_multi_roi.py`
  - `tests/test_brain_region_description_workflow.py`
- Relevant backend spec:
  - `.trellis/spec/backend/quality-guidelines.md`, especially the LLM Provider
    Integration scenario.
