"""Structured JSON generation helpers for configured LLM providers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import (
    AIHUBMIX_GENERATION_PROVIDER,
    DEFAULT_AIHUBMIX_BASE_URL,
    DEFAULT_PACKYAPI_BASE_URL,
    GEMINI_GENERATION_PROVIDER,
    GenerationConfig,
    PACKYAPI_GENERATION_PROVIDER,
    normalize_generation_provider,
)

PACKYAPI_STRICT_JSON_SCHEMA_MODEL_PREFIXES = ("gemini-",)
GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_ATTEMPTS = GEMINI_MAX_RETRIES + 1


def _env_flag(name: str) -> bool:
    """Return whether an environment flag is enabled."""

    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _load_project_env(path: str | Path = ".env") -> None:
    """Load simple KEY=VALUE pairs from a project .env file if present."""

    env_path = Path(path)
    if not env_path.exists():
        return
    with env_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            key = key.strip()
            if key.startswith("export "):
                key = key.removeprefix("export ").strip()
            value = raw_value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def resolve_gemini_api_key() -> str:
    """Resolve Gemini API key from environment."""

    _load_project_env()
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY before running.")
    return key


def resolve_packyapi_api_key() -> str:
    """Resolve PackyAPI API key from environment."""

    _load_project_env()
    key = os.environ.get("PACKYAPI_API_KEY")
    if not key:
        raise RuntimeError("Set PACKYAPI_API_KEY before running with provider='packyapi'.")
    return key


def resolve_aihubmix_api_key() -> str:
    """Resolve AIHubMix API key from environment."""

    _load_project_env()
    key = os.environ.get("AIHUBMIX_API_KEY")
    if not key:
        raise RuntimeError("Set AIHUBMIX_API_KEY before running with provider='aihubmix'.")
    return key


def resolve_api_key() -> str:
    """Resolve the legacy Gemini API key used by older callers."""

    return resolve_gemini_api_key()


def create_genai_client():
    """Create a Google GenAI client for Developer API or Vertex API key mode."""

    from google import genai
    from google.genai import types as genai_types

    _load_project_env()
    http_options = genai_types.HttpOptions(
        # The SDK counts the original request as one attempt; keep the public
        # project setting at three retries while passing four total attempts.
        retry_options=genai_types.HttpRetryOptions(attempts=GEMINI_RETRY_ATTEMPTS),
    )
    if _env_flag("GEMINI_USE_VERTEXAI") or _env_flag("GOOGLE_GENAI_USE_VERTEXAI"):
        return genai.Client(
            vertexai=True,
            api_key=resolve_gemini_api_key(),
            http_options=http_options,
        )

    base_url = os.environ.get("GEMINI_BASE_URL")
    if base_url:
        http_options.base_url = base_url
        return genai.Client(
            api_key=resolve_gemini_api_key(),
            http_options=http_options,
        )
    return genai.Client(api_key=resolve_gemini_api_key(), http_options=http_options)


def create_aihubmix_client():
    """Create an OpenAI SDK client for the AIHubMix-compatible endpoint."""

    from openai import OpenAI

    _load_project_env()
    return OpenAI(
        api_key=resolve_aihubmix_api_key(),
        base_url=os.environ.get("AIHUBMIX_BASE_URL", DEFAULT_AIHUBMIX_BASE_URL),
        max_retries=0,
    )


def create_packyapi_client():
    """Create an OpenAI SDK client for the PackyAPI-compatible endpoint."""

    from openai import OpenAI

    _load_project_env()
    return OpenAI(
        api_key=resolve_packyapi_api_key(),
        base_url=os.environ.get("PACKYAPI_BASE_URL", DEFAULT_PACKYAPI_BASE_URL),
        max_retries=0,
    )


def _contents_to_openai_user_text(contents: list[Any], response_schema: dict[str, Any]) -> str:
    """Flatten prompt contents and expose the expected JSON schema to chat providers."""

    prompt_body = "\n\n".join(str(item) for item in contents)
    schema_text = json.dumps(response_schema, ensure_ascii=False, sort_keys=True)
    return "\n\n".join(
        [
            prompt_body,
            "Response JSON schema:",
            schema_text,
            "Return only one JSON object matching this schema.",
        ],
    )


def _json_object_response_format() -> dict[str, str]:
    """Build the PackyAPI-compatible JSON-object response_format payload."""

    return {"type": "json_object"}


def _packyapi_model_uses_strict_json_schema(model: str) -> bool:
    """Return whether a PackyAPI OpenAI-compatible model supports strict schemas."""

    normalized = model.strip().lower()
    return normalized.startswith(PACKYAPI_STRICT_JSON_SCHEMA_MODEL_PREFIXES)


def _json_schema_response_format(response_schema: dict[str, Any]) -> dict[str, Any]:
    """Build an OpenAI-compatible strict JSON-schema response_format payload."""

    return {
        "type": "json_schema",
        "json_schema": {
            "name": "structured_response",
            "strict": True,
            "schema": response_schema,
        },
    }


def _openai_response_format(model: str, response_schema: dict[str, Any]) -> dict[str, Any]:
    """Select the response format supported by the target OpenAI-compatible model."""

    if _packyapi_model_uses_strict_json_schema(model):
        return _json_schema_response_format(response_schema)
    # Non-Gemini PackyAPI models such as Mimo still use JSON-object mode; their
    # schema contract is enforced by stage validators after parsing.
    return _json_object_response_format()


def _normalize_strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a strict-mode schema copy suitable for OpenAI-compatible providers."""

    def normalize_node(node: Any) -> Any:
        if isinstance(node, list):
            return [normalize_node(item) for item in node]
        if not isinstance(node, dict):
            return node
        normalized = {key: normalize_node(value) for key, value in node.items()}
        schema_type = normalized.get("type")
        is_object = schema_type == "object" or (
            isinstance(schema_type, list) and "object" in schema_type
        )
        if is_object and "additionalProperties" not in normalized:
            normalized["additionalProperties"] = False
        return normalized

    return normalize_node(schema)


def _aihubmix_response_format(response_schema: dict[str, Any]) -> dict[str, Any]:
    """Build the AIHubMix strict JSON-schema response_format payload."""

    return _json_schema_response_format(_normalize_strict_json_schema(response_schema))


def _extract_openai_text(response: Any) -> str:
    """Extract assistant text from an OpenAI SDK chat completion response."""

    choices = getattr(response, "choices", None)
    if not choices:
        raise RuntimeError(f"OpenAI-compatible provider returned no choices: {response!r}")
    message = getattr(choices[0], "message", None)
    text = getattr(message, "content", None)
    if text is None:
        raise RuntimeError(f"OpenAI-compatible provider returned no message content: {response!r}")
    if isinstance(text, list):
        return "".join(str(part) for part in text)
    return str(text)


def _loads_json_object(text: str) -> dict[str, Any]:
    """Parse provider text and require the structured response to be an object."""

    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise RuntimeError(
            "OpenAI-compatible provider returned "
            f"{type(payload).__name__}; expected a JSON object matching the schema.",
        )
    return payload


def _generate_structured_json_openai_chat(
    *,
    client: Any,
    model: str,
    system_instruction: str,
    contents: list[Any],
    response_schema: dict[str, Any],
    cfg: GenerationConfig,
    response_format: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate JSON through an OpenAI-compatible chat completion."""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": _contents_to_openai_user_text(contents, response_schema)},
        ],
        temperature=cfg.temperature,
        response_format=response_format or _openai_response_format(model, response_schema),
    )
    return _loads_json_object(_extract_openai_text(response))


def _generate_structured_json_aihubmix_chat(
    *,
    client: Any,
    model: str,
    system_instruction: str,
    contents: list[Any],
    response_schema: dict[str, Any],
    cfg: GenerationConfig,
) -> dict[str, Any]:
    """Generate JSON through AIHubMix with strict OpenAI-compatible schemas."""

    return _generate_structured_json_openai_chat(
        client=client,
        model=model,
        system_instruction=system_instruction,
        contents=contents,
        response_schema=response_schema,
        cfg=cfg,
        response_format=_aihubmix_response_format(response_schema),
    )


def _generate_structured_json_gemini(
    *,
    client: Any,
    model: str,
    system_instruction: str,
    contents: list[Any],
    response_schema: dict[str, Any],
    cfg: GenerationConfig,
) -> dict[str, Any]:
    """Generate JSON through Google GenAI with native schema enforcement."""

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=_gemini_structured_output_config(
            system_instruction=system_instruction,
            response_schema=response_schema,
            cfg=cfg,
        ),
    )
    text = getattr(response, "text", None)
    if text is None:
        raise RuntimeError(f"Gemini returned no text: {response!r}")
    return _loads_json_object(text)


def _gemini_structured_output_config(
    *,
    system_instruction: str,
    response_schema: dict[str, Any],
    cfg: GenerationConfig,
) -> dict[str, Any]:
    """Build Gemini SDK config while keeping schema out of prompt contents."""

    return {
        "temperature": cfg.temperature,
        "system_instruction": system_instruction,
        "response_mime_type": "application/json",
        "response_json_schema": response_schema,
    }


def generate_structured_json(
    *,
    model: str,
    system_instruction: str,
    contents: list[Any],
    response_schema: dict[str, Any],
    cfg: GenerationConfig,
) -> dict[str, Any]:
    """Generate JSON once through the configured LLM provider."""

    provider = normalize_generation_provider(cfg.generation_provider)
    if provider == AIHUBMIX_GENERATION_PROVIDER:
        client = create_aihubmix_client()
        generate_once = _generate_structured_json_aihubmix_chat
    elif provider == PACKYAPI_GENERATION_PROVIDER:
        client = create_packyapi_client()
        generate_once = _generate_structured_json_openai_chat
    elif provider == GEMINI_GENERATION_PROVIDER:
        client = create_genai_client()
        generate_once = _generate_structured_json_gemini
    else:  # Defensive guard for type checkers and future provider additions.
        raise ValueError(f"Unsupported generation_provider: {cfg.generation_provider!r}")
    return generate_once(
        client=client,
        model=model,
        system_instruction=system_instruction,
        contents=contents,
        response_schema=response_schema,
        cfg=cfg,
    )
