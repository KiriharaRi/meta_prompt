# Add Xiaomi MiMo OpenAI Provider

## Goal

Add OpenAI SDK-based compatibility for Xiaomi MiMo through AIHubMix so the maintained
brain-region prompt pipeline can run its LLM-backed stages with
`xiaomi-mimo-v2.5-pro` by default, while preserving the existing structured JSON
generation contract used by domain-pool, region-schema, summary, and scoring stages.

## What I Already Know

- The current maintained package is `brain_region_pipeline`.
- LLM calls are centralized through `brain_region_pipeline/genai.py`.
- Existing LLM code uses Google GenAI only and reads `GEMINI_API_KEY` or
  `GOOGLE_API_KEY` from `.env` / environment.
- The user wants the new implementation to use the `openai` Python SDK rather
  than raw `httpx`.
- The user wants API key loading to follow the project `.env` convention.
- AIHubMix uses an OpenAI-compatible base URL: `https://aihubmix.com/v1`.
- The new default model should be `xiaomi-mimo-v2.5-pro`.
- The project uses `uv` for Python environment and validation commands.
- `cli.py` must remain CLI parsing and dispatch only; business/provider logic
  belongs in focused modules.

## Assumptions

- The AIHubMix API key environment variable will be `AIHUBMIX_API_KEY`.
- `AIHUBMIX_BASE_URL` may optionally override the default
  `https://aihubmix.com/v1` for debugging or proxy changes.
- Gemini compatibility should remain available as a non-default provider because
  existing users/artifacts may still rely on it.
- The OpenAI SDK will be added to `pyproject.toml`; `uv lock` should be updated
  if dependency resolution is needed in this environment.

## Open Questions

- None blocking at the moment. The implementation can proceed once the user
  confirms starting code changes under the project rule of "方案先行，确认后实施".

## Requirements

- Add a provider choice for structured JSON generation.
- Default generation provider should be AIHubMix/OpenAI-compatible.
- Default generation model should be `xiaomi-mimo-v2.5-pro`.
- Use the `openai` Python SDK for AIHubMix calls.
- Load AIHubMix credentials from `.env` / environment using `AIHUBMIX_API_KEY`.
- Use `https://aihubmix.com/v1` as the default AIHubMix base URL.
- Preserve the existing Gemini path behind an explicit provider setting.
- Keep `generate_structured_json(...)` as the stable call surface used by
  domain-pool, region-schema, summary, and scoring modules.
- Ensure pilot config can select provider/model, with new defaults applying when
  fields are omitted.
- Update CLI help, README, and tests so defaults and provider behavior are clear.

## Acceptance Criteria

- [x] `GenerationConfig` and derived configs can carry provider + model.
- [x] `generate_structured_json(...)` dispatches to AIHubMix/OpenAI SDK by
      default and Gemini when explicitly requested.
- [x] Missing `AIHUBMIX_API_KEY` produces a clear runtime error for the default
      provider.
- [x] AIHubMix requests include the configured model, messages, JSON response
      contract, temperature, timeout, and base URL.
- [x] Existing Gemini structured JSON behavior remains covered by tests.
- [x] `run-multi-roi-pilot` config supports `generation_provider`.
- [x] README documents `.env` settings and how to switch back to Gemini.
- [x] Validation passes:
      `uv run python -m unittest discover -s tests -p 'test_*.py'`
- [x] Compilation passes:
      `uv run python -m compileall brain_region_pipeline tests`

## Definition of Done

- Tests added or updated for provider dispatch, env loading, CLI defaults, and
  pilot config propagation.
- README updated for AIHubMix/MiMo defaults.
- Dependency metadata updated with the OpenAI SDK.
- No unrelated refactor or generated cache left in the working tree.

## Out of Scope

- Live remote API validation against AIHubMix.
- Supporting non-chat completion endpoints.
- Implementing streaming output.
- Changing scoring prompts, schema definitions, fMRI encoding logic, or ROI
  selection behavior.
- Migrating existing generated artifacts to new model metadata.

## Technical Notes

- Relevant files inspected:
  - `brain_region_pipeline/genai.py`
  - `brain_region_pipeline/config.py`
  - `brain_region_pipeline/cli.py`
  - `brain_region_pipeline/pilot_runner.py`
  - `tests/test_brain_region_description_workflow.py`
  - `tests/test_brain_region_runner.py`
  - `README.md`
  - `pyproject.toml`
- Relevant specs:
  - `.trellis/spec/backend/directory-structure.md`
  - `.trellis/spec/backend/quality-guidelines.md`
  - `.trellis/spec/guides/code-reuse-thinking-guide.md`
- AIHubMix documentation reference:
  - `https://docs.aihubmix.com/en/api/Aihubmix-Integration`
  - `https://docs.aihubmix.com/en/quick-start`
  - User-provided model page:
    `https://aihubmix.com/model/xiaomi-mimo-v2.5-pro`
