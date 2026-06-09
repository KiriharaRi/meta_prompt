# PackyAPI OpenAI-Compatible Notes

Source URLs:

* https://docs.packyapi.com/docs/register/
* https://docs.packyapi.com/docs/cli/codex
* https://docs.packyapi.com/docs/token/
* https://docs.packyapi.com/docs/advanced/DeepSeekClaudeCode.html

Access date: 2026-05-31.

## Findings

* PackyAPI provides OpenAI-compatible endpoints. For OpenAI-compatible clients, the base URL should include `/v1`.
* Documented stable endpoint: `https://www.packyapi.com/v1`.
* Documented optimized endpoint: `https://api-slb.packyapi.com/v1`.
* The quick-start docs explicitly mention OpenAI SDK and OpenAI-compatible clients.
* The Codex docs use an API key beginning with `sk-` and show `OPENAI_API_KEY` in Codex auth, but repo-local pipeline code should avoid colliding with the user's global OpenAI/Codex env unless the design intentionally chooses generic OpenAI env names.
* Token group selection matters. PackyAPI docs emphasize that available models depend on the token group, and wrong grouping can cause missing-model failures.
* PackyAPI docs mention `deepseek-v4-pro` in the DeepSeek-to-Claude-Code guide, but this repo should not assume every PackyAPI token can call that model unless the user confirms the intended group/model.

## Design Implications

* A minimal migration can reuse the existing `openai.OpenAI` SDK call path and swap env names plus base URL defaults.
* The most important design choice is provider naming: a literal `packyapi` provider is smaller, while a generic OpenAI-compatible provider abstraction avoids future repeated provider renames.
* The default model should be treated as a user-visible contract because tests and pilot configs currently assert `deepseek-v4-pro`.
