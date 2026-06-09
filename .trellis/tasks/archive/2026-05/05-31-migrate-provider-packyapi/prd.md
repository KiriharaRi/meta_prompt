# brainstorm: migrate LLM provider to PackyAPI

## Goal

Migrate the brain-region prompt pipeline's default OpenAI-compatible generation provider from AIHubMix to PackyAPI while preserving the existing Gemini path and keeping long-running generation commands predictable.

## What I Already Know

* User wants to replace AIHubMix with PackyAPI.
* User expects migration to be relatively small because both providers support OpenAI-compatible APIs.
* Current repo defaults to `generation_provider = "aihubmix"` and `generation_model = "deepseek-v4-pro"`.
* Current OpenAI-compatible path is AIHubMix-specific in names: `AIHUBMIX_API_KEY`, `AIHUBMIX_BASE_URL`, `DEFAULT_AIHUBMIX_BASE_URL`, `create_aihubmix_client`, `_generate_structured_json_aihubmix`.
* Current default base URL is `https://aihubmix.com/v1`.
* Current PackyAPI OpenAI-compatible base URLs are `https://www.packyapi.com/v1` and optional optimized route `https://api-slb.packyapi.com/v1`.
* PackyAPI docs say OpenAI-compatible clients use `/v1/chat/completions`.
* PackyAPI token groups affect available models; using the wrong group can produce "model not found" style failures.
* Existing tests explicitly assert AIHubMix env names, default provider behavior, client base URL, and OpenAI chat-completion request schema.
* Existing `configs/friends_multi_roi_pilot.json` pins `generation_provider` to `aihubmix`.

## Assumptions

* PackyAPI should use the existing `openai` Python SDK dependency.
* Gemini remains as a separate provider because it uses Google GenAI native schema handling.
* The current model `deepseek-v4-pro` may remain valid if the user's PackyAPI token group has access to it, but this must be treated as a deployment choice rather than assumed universally.

## Decisions

* User confirmed the PRD is complete enough and authorized implementation on 2026-05-31.
* Public provider name will be `packyapi`, not `openai_compatible`. The CLI/config contract should clearly identify the service users are configuring, while internal helpers may still keep OpenAI-compatible request logic factored cleanly.
* Environment variables will hard-cut to `PACKYAPI_API_KEY` and `PACKYAPI_BASE_URL`. Do not keep `AIHUBMIX_*` as fallback aliases, so stale local `.env` files fail fast instead of silently using an old provider setup.
* Default model remains `deepseek-v4-pro`. The migration should isolate provider routing changes from model-behavior changes, and docs should note that the PackyAPI token group must have access to this model or the user should override `--model` / config.
* `generation_provider = "aihubmix"` will not remain accepted as a deprecated alias. Old provider names should fail fast and tell users the supported providers.
* Default PackyAPI base URL will be the stable main endpoint `https://www.packyapi.com/v1`. The optimized endpoint `https://api-slb.packyapi.com/v1` should be documented as an optional `PACKYAPI_BASE_URL` override.
* Implementation should use a small OpenAI-compatible helper boundary internally while keeping PackyAPI-specific public config entry points. Use `resolve_packyapi_api_key()` / `create_packyapi_client()` style names for service configuration, and a provider-neutral helper for the OpenAI chat-completion structured JSON request.
* Historical notebooks and prior-code artifacts under `fallen/previous_code/*` are out of scope for this migration. Only maintained pipeline source, tests, README, and active configs should be updated.
* Live PackyAPI testing showed `response_format=json_schema` is rejected with `This response_format type is unavailable now`, while `response_format=json_object` works. PackyAPI should use `json_object`, with the expected schema rendered into the prompt and stage-specific Python validators enforcing contracts after parsing.
* Validation should use offline tests and dry-run checks only. Do not make live PackyAPI calls or require real API credentials during this task.

## Requirements (Evolving)

* Replace the default OpenAI-compatible provider used by generation-backed stages with PackyAPI.
* Keep the default model as `deepseek-v4-pro`.
* Use `PACKYAPI_API_KEY` and optional `PACKYAPI_BASE_URL` for PackyAPI configuration.
* Do not accept `AIHUBMIX_API_KEY` or `AIHUBMIX_BASE_URL` for the new `packyapi` provider.
* Do not accept `aihubmix` as a provider value after migration.
* Preserve command-line configurability via `--provider` and `--model`.
* Keep the Gemini provider path working.
* Update tests that encode AIHubMix defaults and env conventions.
* Update README and example config so users know which PackyAPI env vars and base URL to set.
* Avoid large unrelated refactors.
* Avoid introducing a full provider registry or plugin system for this migration.

## Acceptance Criteria

* [x] Default provider resolves to `packyapi`.
* [x] Default base URL resolves to `https://www.packyapi.com/v1` unless overridden.
* [x] README mentions `https://api-slb.packyapi.com/v1` as an optional optimized route override.
* [x] Runtime error for missing PackyAPI key names the expected env var.
* [x] Stale `AIHUBMIX_*` env vars do not satisfy PackyAPI configuration.
* [x] Stale `generation_provider = "aihubmix"` configs fail fast with an actionable unsupported-provider error.
* [x] OpenAI SDK chat-completion payload remains compatible with existing structured JSON flow.
* [x] Tests cover provider normalization, API key resolution, client construction, and default dispatch.
* [x] README and pilot config examples no longer point users to AIHubMix as the default.
* [x] README documents the PackyAPI token-group caveat for `deepseek-v4-pro`.
* [x] `uv run python -m unittest discover -s tests -p 'test_*.py'` passes.
* [x] `uv run python -m compileall brain_region_pipeline tests` passes.
* [x] Relevant CLI help and `run-multi-roi-pilot --dry-run` checks pass without live LLM calls.

## Definition of Done

* Tests added/updated for changed behavior.
* `uv` is used for Python commands.
* Docs/notes updated for provider env vars and model caveats.
* No code implementation starts until the user confirms the migration design.

## Out of Scope

* Switching the Gemini path away from Google GenAI.
* Adding a full provider plugin system unless the design discussion explicitly chooses it.
* Adding multi-mode automatic fallback logic for provider-specific structured output modes.
* Validating live PackyAPI credentials or making real paid API calls.
* Changing fMRI encoding, scoring schema, ROI logic, or batching semantics.
* Migrating historical notebooks or prior-code artifacts under `fallen/previous_code/*`.

## Technical Notes

* Relevant code files inspected: `brain_region_pipeline/config.py`, `brain_region_pipeline/genai.py`, `brain_region_pipeline/cli.py`, `brain_region_pipeline/pilot_runner.py`.
* Relevant tests inspected: `tests/test_brain_region_description_workflow.py`, `tests/test_brain_region_multi_roi.py`.
* Relevant docs/config inspected: `README.md`, `configs/friends_multi_roi_pilot.json`.
* Research note: `research/packyapi-openai-compatible.md`.

## Implementation Notes

* Updated maintained provider defaults from AIHubMix to PackyAPI.
* Renamed service-specific key/client helpers to PackyAPI names.
* Renamed the structured OpenAI-compatible chat-completion helper to a provider-neutral internal helper.
* Preserved Gemini dispatch behavior.
* Updated backend LLM provider code-spec so future work uses the PackyAPI contract.
* Updated PackyAPI structured output handling from `json_schema` to `json_object` after live compatibility testing.

## Validation

* `uv run python -m unittest tests.test_brain_region_description_workflow tests.test_brain_region_multi_roi`
* `uv run python -m unittest discover -s tests -p 'test_*.py'`
* `uv run python -m compileall brain_region_pipeline tests`
* `uv run python -m brain_region_pipeline make-domain-pool --help`
* `uv run python -m brain_region_pipeline score-descriptions --help`
* `uv run python -m brain_region_pipeline run-multi-roi-pilot --config configs/friends_multi_roi_pilot.json --stage all --dry-run`
