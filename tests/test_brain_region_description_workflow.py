from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from brain_region_pipeline.cli import main
from brain_region_pipeline.core.config import (
    AIHUBMIX_GENERATION_PROVIDER,
    DEFAULT_AIHUBMIX_BASE_URL,
    DEFAULT_AIHUBMIX_MODEL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_GENERATION_PROVIDER,
    DEFAULT_PACKYAPI_BASE_URL,
    DEFAULT_PACKYAPI_MODEL,
    DomainPoolConfig,
    PACKYAPI_GENERATION_PROVIDER,
    RegionSchemaConfig,
    ScoreDescriptionsConfig,
    SummaryDescriptionsConfig,
)
from brain_region_pipeline.core.contracts import (
    CORE_EMOTION_DIMENSION_IDS,
    DOMAIN_POOL_VERSION,
    EMOTION_EXPERIENCE_DOMAIN_ID,
    REGION_SCHEMA_VERSION,
    REQUIRED_EMOTION_EXPERIENCE_SOURCE_ID,
    required_domain_seeds_for_region,
)
from brain_region_pipeline.scoring.description_io import parse_description_text
from brain_region_pipeline.schema_design.domain_pool import (
    _build_domain_consolidation_prompt,
    _build_domain_proposal_prompt,
    build_domain_pool,
    load_domain_pool,
    required_domain_candidates,
    validate_required_domains,
)
from brain_region_pipeline.core.genai import (
    GEMINI_RETRY_ATTEMPTS,
    _generate_structured_json_gemini,
    _generate_structured_json_aihubmix_chat,
    _generate_structured_json_openai_chat,
    _load_project_env,
    _normalize_strict_json_schema,
    create_aihubmix_client,
    create_genai_client,
    create_packyapi_client,
    generate_structured_json,
    resolve_aihubmix_api_key,
    resolve_packyapi_api_key,
)
from brain_region_pipeline.scoring.gt_aligner import average_gt_to_segments, load_averaged_gt_csvs
from brain_region_pipeline.atlas.models import SelectionRule
from brain_region_pipeline.schema_design.domain_models import (
    CandidateDomain,
    CuratedDomain,
    DomainPool,
    RejectedOrMergedDomain,
)
from brain_region_pipeline.schema_design.schema_models import DimensionSpec, RegionFeatureSchema
from brain_region_pipeline.scoring.models import DescriptionSegment, SegmentRegionScore
from brain_region_pipeline.schema_design.region_schema import (
    DIMENSION_ANCHOR_LABELS,
    DIMENSION_SCORE_MAX,
    DIMENSION_SCORE_MIN,
    MAX_DIMENSION_CALIBRATION_EXAMPLES,
    MAX_DIMENSION_TRIGGERS,
    MAX_NON_EMOTION_DIMENSIONS_PER_DOMAIN,
    MIN_DIMENSION_CALIBRATION_EXAMPLES,
    MIN_DIMENSION_TRIGGERS,
    MIN_NON_EMOTION_DIMENSIONS_PER_DOMAIN,
    REGION_SCHEMA_SYSTEM_INSTRUCTION,
    _build_prompt,
    _region_schema_response_schema,
    normalize_schema_dimension_order,
    validate_region_schema_quality,
)
from brain_region_pipeline.scoring.region_schema_scorer import (
    TARGET_SEGMENT_EVIDENCE_INSTRUCTION,
    VIEWER_PERSPECTIVE_INSTRUCTION,
    _schema_prompt_block,
)
from brain_region_pipeline.core.dependencies import PipelineDependencies
from brain_region_pipeline.scoring.summary_generator import summarize_description_segments


def _anchors() -> dict[str, str]:
    return {
        str(score): ("absent" if score == 0 else f"level {score}")
        for score in range(DIMENSION_SCORE_MIN, DIMENSION_SCORE_MAX + 1)
    }


def _dimension(
    dimension_id: str,
    domain: str,
    definition: str | None = None,
    trigger_list: tuple[str, ...] | None = None,
    calibration_examples: tuple[dict[str, object], ...] | None = None,
) -> DimensionSpec:
    return DimensionSpec(
        dimension_id=dimension_id,
        definition=definition or f"Intensity of {dimension_id}.",
        domain=domain,
        score_min=float(DIMENSION_SCORE_MIN),
        score_max=float(DIMENSION_SCORE_MAX),
        trigger_list=trigger_list if trigger_list is not None else (
            f"{dimension_id} trigger A",
            f"{dimension_id} trigger B",
            f"{dimension_id} trigger C",
        ),
        graded_anchors=_anchors(),
        calibration_examples=calibration_examples if calibration_examples is not None else (
            {"scene": "No relevant evidence.", "score": 0},
            {"scene": "Strong relevant evidence.", "score": 8},
        ),
        scoreability_note=f"Use text evidence for {dimension_id}.",
        exclusion_note=f"Do not count nearby concepts for {dimension_id}.",
    )


def _canonical_emotion_seed() -> dict[str, object]:
    return required_domain_seeds_for_region("vmPFC")[EMOTION_EXPERIENCE_DOMAIN_ID]


def _required_candidate() -> CandidateDomain:
    seed = _canonical_emotion_seed()
    return CandidateDomain(
        domain_id=str(seed["domain_id"]),
        definition=str(seed["definition"]),
        region_relevance=str(seed["region_relevance"]),
        scoreability_note=str(seed["scoreability_note"]),
        source_run=int(seed["source_run"]),
    )


def _sample_domain_pool(
    source_model: str = "fake-model",
    curation_status: str = "draft",
    proposal_runs: int = 5,
    target_region: str = "vmPFC",
) -> DomainPool:
    return DomainPool(
        version=DOMAIN_POOL_VERSION,
        target_region=target_region,
        curation_status=curation_status,
        source_model=source_model,
        proposal_runs=proposal_runs,
        metadata={
            "required_domain_ids": [EMOTION_EXPERIENCE_DOMAIN_ID],
            "required_seed_source_run": 0,
        },
        candidate_domains=(
            _required_candidate(),
            CandidateDomain(
                domain_id="run_1_subjective_valuation",
                definition="Subjective reward, loss, and utility.",
                vmpfc_relevance="vmPFC tracks subjective value.",
                scoreability_note="Use goals, gains, losses, and choices.",
                source_run=1,
            ),
        ),
        curated_domains=(
            CuratedDomain(
                domain_id=EMOTION_EXPERIENCE_DOMAIN_ID,
                definition=str(_canonical_emotion_seed()["definition"]),
                vmpfc_relevance="Relevant to vmPFC affective meaning.",
                scoreability_note="Score from description evidence only.",
                source_domain_ids=(REQUIRED_EMOTION_EXPERIENCE_SOURCE_ID,),
                source_runs=(0,),
                proposal_frequency=1,
                consolidation_rationale="Required validation anchor domain.",
            ),
            CuratedDomain(
                domain_id="subjective_valuation",
                definition="Subjective reward, loss, and utility.",
                vmpfc_relevance="vmPFC tracks subjective value.",
                scoreability_note="Score from goals, gains, losses, and choices.",
                source_domain_ids=("run_1_subjective_valuation",),
                source_runs=(1,),
                proposal_frequency=1,
                consolidation_rationale="Retained as a distinct valuation domain.",
            ),
        ),
        rejected_or_merged_domains=(
            RejectedOrMergedDomain(
                domain_id="generic_valence",
                decision="rejected",
                reason="Too expansive and risks becoming signed valence.",
                source_domain_ids=("run_1_generic_valence",),
                source_runs=(1,),
            ),
        ),
    )


def _sample_non_emotion_domain_pool(
    target_region: str = "PCC",
    curation_status: str = "confirmed",
) -> DomainPool:
    return DomainPool(
        version=DOMAIN_POOL_VERSION,
        target_region=target_region,
        curation_status=curation_status,
        source_model="fake-model",
        proposal_runs=5,
        metadata={"required_domain_ids": []},
        candidate_domains=(
            CandidateDomain(
                domain_id="run_1_social_context",
                definition="Social context and relationship-state information.",
                region_relevance="Relevant to posterior default-network social context integration.",
                scoreability_note="Use explicit social and narrative context evidence.",
                source_run=1,
            ),
        ),
        curated_domains=(
            CuratedDomain(
                domain_id="social_context",
                definition="Social context and relationship-state information.",
                region_relevance="Relevant to posterior default-network social context integration.",
                scoreability_note="Use explicit social and narrative context evidence.",
                source_domain_ids=("run_1_social_context",),
                source_runs=(1,),
                proposal_frequency=1,
                consolidation_rationale="Retained as target-region relevant and scoreable.",
            ),
        ),
        rejected_or_merged_domains=(),
    )


def _schema_dimensions() -> tuple[DimensionSpec, ...]:
    emotion = tuple(
        _dimension(dimension_id, EMOTION_EXPERIENCE_DOMAIN_ID)
        for dimension_id in CORE_EMOTION_DIMENSION_IDS
    )
    valuation = tuple(
        _dimension(f"valuation_signal_{idx:02d}", "subjective_valuation")
        for idx in range(1, 5)
    )
    return emotion + valuation


def _non_emotion_schema_dimensions() -> tuple[DimensionSpec, ...]:
    return tuple(
        _dimension(f"social_context_{idx:02d}", "social_context")
        for idx in range(1, 5)
    )


def _sample_region_schema(
    source_model: str = "fake-model",
    metadata: dict | None = None,
    target_region: str = "vmPFC",
) -> RegionFeatureSchema:
    pool = _sample_domain_pool(curation_status="confirmed", target_region=target_region)
    dimensions = _schema_dimensions()
    return RegionFeatureSchema(
        version=REGION_SCHEMA_VERSION,
        target_region=target_region,
        functional_hypothesis="vmPFC tracks affective meaning and subjective value.",
        scoring_instruction="Score all dimensions from dense description evidence only.",
        selection_rules=(
            SelectionRule(label_ids=(1, 2)),
        ),
        domains=pool.curated_domains,
        active_domain_ids=(EMOTION_EXPERIENCE_DOMAIN_ID, "subjective_valuation"),
        dimensions=dimensions,
        metadata={
            **dict(metadata or {}),
            "source_model": source_model,
        },
    )


def _sample_non_emotion_region_schema(
    target_region: str = "PCC",
) -> RegionFeatureSchema:
    pool = _sample_non_emotion_domain_pool(target_region=target_region)
    return RegionFeatureSchema(
        version=REGION_SCHEMA_VERSION,
        target_region=target_region,
        functional_hypothesis="Posterior default network tracks social context and narrative state.",
        scoring_instruction="Score all dimensions from dense description evidence only.",
        selection_rules=(
            SelectionRule(label_ids=(1, 2)),
        ),
        domains=pool.curated_domains,
        active_domain_ids=("social_context",),
        dimensions=_non_emotion_schema_dimensions(),
        metadata={"source_model": "fake-model"},
    )


def _fake_domain_pool(parcels, cfg):
    return _sample_domain_pool(
        source_model=cfg.generation_model,
        proposal_runs=cfg.proposal_runs,
        target_region=cfg.target_region,
    )


def _fake_region_schema(parcels, cfg, domain_pool, metadata=None):
    return _sample_region_schema(
        source_model=cfg.generation_model,
        metadata=metadata or {},
        target_region=cfg.target_region,
    )


def _score_dict(base: float) -> dict[str, float]:
    return {
        dimension.dimension_id: base + idx
        for idx, dimension in enumerate(_sample_region_schema().dimensions)
    }


def _fake_score_description_segments(segments, schema, cfg, summaries=None, warnings=None):
    rows = []
    for idx, segment in enumerate(segments):
        rows.append(
            SegmentRegionScore(
                start_s=segment.start_s,
                end_s=segment.end_s,
                description=segment.description,
                dimension_scores=_score_dict(0.2 + idx),
                rationale=f"Segment {idx} has vmPFC-relevant value cues.",
            ),
        )
    return rows


def _fake_score_description_segment_batch(
    batch_idx,
    batch_start,
    segments,
    schema,
    cfg,
    summaries=None,
    warnings=None,
):
    rows = []
    batch_end = min(batch_start + cfg.scoring_batch_size, len(segments))
    for idx in range(batch_start, batch_end):
        segment = segments[idx]
        rows.append(
            SegmentRegionScore(
                start_s=segment.start_s,
                end_s=segment.end_s,
                description=segment.description,
                dimension_scores=_score_dict(0.2 + idx),
                rationale=f"Segment {idx} has vmPFC-relevant value cues.",
                segment_id=idx,
                batch_idx=batch_idx,
            ),
        )
    return rows


class DescriptionWorkflowTests(unittest.TestCase):
    def test_project_env_loader_sets_missing_keys_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "GEMINI_API_KEY=from_file",
                        'export GEMINI_BASE_URL="https://example.test"',
                        "AIHUBMIX_API_KEY=aihubmix_from_file",
                        "PACKYAPI_API_KEY=packyapi_from_file",
                        "EXISTING_KEY=from_file",
                    ],
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"EXISTING_KEY": "already_set"}, clear=True):
                _load_project_env(env_file)

                self.assertEqual(os.environ["GEMINI_API_KEY"], "from_file")
                self.assertEqual(os.environ["GEMINI_BASE_URL"], "https://example.test")
                self.assertEqual(os.environ["AIHUBMIX_API_KEY"], "aihubmix_from_file")
                self.assertEqual(os.environ["PACKYAPI_API_KEY"], "packyapi_from_file")
                self.assertEqual(os.environ["EXISTING_KEY"], "already_set")

    def test_aihubmix_api_key_uses_project_env_convention(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("AIHUBMIX_API_KEY=from_file\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                _load_project_env(env_file)

                with patch("brain_region_pipeline.core.genai._load_project_env"):
                    self.assertEqual(resolve_aihubmix_api_key(), "from_file")

    def test_aihubmix_api_key_error_is_actionable(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("brain_region_pipeline.core.genai._load_project_env"):
            with self.assertRaisesRegex(RuntimeError, "AIHUBMIX_API_KEY"):
                resolve_aihubmix_api_key()

    def test_packyapi_api_key_uses_project_env_convention(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text("PACKYAPI_API_KEY=from_file\n", encoding="utf-8")

            with patch.dict(os.environ, {}, clear=True):
                _load_project_env(env_file)

                with patch("brain_region_pipeline.core.genai._load_project_env"):
                    self.assertEqual(resolve_packyapi_api_key(), "from_file")

    def test_packyapi_api_key_error_is_actionable(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("brain_region_pipeline.core.genai._load_project_env"):
            with self.assertRaisesRegex(RuntimeError, "PACKYAPI_API_KEY"):
                resolve_packyapi_api_key()

    def test_aihubmix_api_key_does_not_satisfy_packyapi_config(self) -> None:
        with patch.dict(os.environ, {"AIHUBMIX_API_KEY": "legacy-key"}, clear=True), patch(
            "brain_region_pipeline.core.genai._load_project_env",
        ):
            with self.assertRaisesRegex(RuntimeError, "PACKYAPI_API_KEY"):
                resolve_packyapi_api_key()

    def test_aihubmix_client_uses_default_base_url(self) -> None:
        created: list[dict] = []

        class FakeOpenAI:
            def __init__(self, **kwargs):
                created.append(kwargs)

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = FakeOpenAI

        with patch.dict(sys.modules, {"openai": fake_openai}), patch.dict(
            os.environ,
            {"AIHUBMIX_API_KEY": "test-key"},
            clear=True,
        ), patch("brain_region_pipeline.core.genai._load_project_env"):
            create_aihubmix_client()

        self.assertEqual(created[0]["api_key"], "test-key")
        self.assertEqual(created[0]["base_url"], DEFAULT_AIHUBMIX_BASE_URL)
        self.assertEqual(created[0]["max_retries"], 0)

    def test_gemini_client_can_use_vertex_api_key_mode(self) -> None:
        created: list[dict] = []

        class FakeGenaiClient:
            def __init__(self, **kwargs):
                created.append(kwargs)

        fake_google = types.ModuleType("google")
        fake_genai = types.ModuleType("google.genai")
        fake_genai.Client = FakeGenaiClient
        fake_genai_types = types.ModuleType("google.genai.types")
        fake_genai_types.HttpOptions = lambda **kwargs: types.SimpleNamespace(**kwargs)
        fake_genai_types.HttpRetryOptions = lambda **kwargs: types.SimpleNamespace(**kwargs)
        fake_google.genai = fake_genai

        with patch.dict(
            sys.modules,
            {
                "google": fake_google,
                "google.genai": fake_genai,
                "google.genai.types": fake_genai_types,
            },
        ), patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "vertex-key",
                "GEMINI_USE_VERTEXAI": "true",
                "GEMINI_BASE_URL": "https://proxy.example.test",
            },
            clear=True,
        ), patch("brain_region_pipeline.core.genai._load_project_env"):
            create_genai_client()

        self.assertEqual(created[0]["vertexai"], True)
        self.assertEqual(created[0]["api_key"], "vertex-key")
        http_options = created[0]["http_options"]
        self.assertFalse(hasattr(http_options, "base_url"))
        self.assertEqual(http_options.retry_options.attempts, GEMINI_RETRY_ATTEMPTS)

    def test_gemini_client_base_url_mode_preserves_retry_options(self) -> None:
        created: list[dict] = []

        class FakeGenaiClient:
            def __init__(self, **kwargs):
                created.append(kwargs)

        fake_google = types.ModuleType("google")
        fake_genai = types.ModuleType("google.genai")
        fake_genai.Client = FakeGenaiClient
        fake_genai_types = types.ModuleType("google.genai.types")
        fake_genai_types.HttpOptions = lambda **kwargs: types.SimpleNamespace(**kwargs)
        fake_genai_types.HttpRetryOptions = lambda **kwargs: types.SimpleNamespace(**kwargs)
        fake_google.genai = fake_genai

        with patch.dict(
            sys.modules,
            {
                "google": fake_google,
                "google.genai": fake_genai,
                "google.genai.types": fake_genai_types,
            },
        ), patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "gemini-key",
                "GEMINI_BASE_URL": "https://proxy.example.test",
            },
            clear=True,
        ), patch("brain_region_pipeline.core.genai._load_project_env"):
            create_genai_client()

        self.assertEqual(created[0]["api_key"], "gemini-key")
        http_options = created[0]["http_options"]
        self.assertEqual(http_options.base_url, "https://proxy.example.test")
        self.assertEqual(http_options.retry_options.attempts, GEMINI_RETRY_ATTEMPTS)

    def test_packyapi_client_uses_default_base_url(self) -> None:
        created: list[dict] = []

        class FakeOpenAI:
            def __init__(self, **kwargs):
                created.append(kwargs)

        fake_openai = types.ModuleType("openai")
        fake_openai.OpenAI = FakeOpenAI

        with patch.dict(sys.modules, {"openai": fake_openai}), patch.dict(
            os.environ,
            {"PACKYAPI_API_KEY": "test-key"},
            clear=True,
        ), patch("brain_region_pipeline.core.genai._load_project_env"):
            create_packyapi_client()

        self.assertEqual(created[0]["api_key"], "test-key")
        self.assertEqual(created[0]["base_url"], DEFAULT_PACKYAPI_BASE_URL)
        self.assertEqual(created[0]["max_retries"], 0)

    def test_openai_chat_structured_generation_uses_json_object_payload(self) -> None:
        class FakeCompletions:
            def __init__(self):
                self.kwargs: dict | None = None

            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content='{"ok": true}')
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        completions = FakeCompletions()
        client = types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=completions,
            ),
        )
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }
        cfg = SummaryDescriptionsConfig(
            generation_provider=PACKYAPI_GENERATION_PROVIDER,
            generation_model=DEFAULT_PACKYAPI_MODEL,
            temperature=0.1,
        )

        payload = _generate_structured_json_openai_chat(
            client=client,
            model=cfg.generation_model,
            system_instruction="Return JSON.",
            contents=["Prompt body."],
            response_schema=schema,
            cfg=cfg,
        )

        self.assertEqual(payload, {"ok": True})
        self.assertIsNotNone(completions.kwargs)
        request = completions.kwargs or {}
        self.assertEqual(request["model"], DEFAULT_PACKYAPI_MODEL)
        self.assertEqual(request["temperature"], 0.1)
        self.assertNotIn("timeout", request)
        self.assertEqual(request["messages"][0]["role"], "system")
        self.assertIn("Prompt body.", request["messages"][1]["content"])
        self.assertIn("Response JSON schema:", request["messages"][1]["content"])
        self.assertIn('"ok"', request["messages"][1]["content"])
        self.assertEqual(request["response_format"], {"type": "json_object"})

    def test_packyapi_gemini_structured_generation_uses_strict_json_schema(self) -> None:
        class FakeCompletions:
            def __init__(self):
                self.kwargs: dict | None = None

            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content='{"ok": true}')
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        completions = FakeCompletions()
        client = types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=completions,
            ),
        )
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        cfg = SummaryDescriptionsConfig(
            generation_provider=PACKYAPI_GENERATION_PROVIDER,
            generation_model=DEFAULT_GEMINI_MODEL,
            temperature=0.1,
        )

        payload = _generate_structured_json_openai_chat(
            client=client,
            model=cfg.generation_model,
            system_instruction="Return JSON.",
            contents=["Prompt body."],
            response_schema=schema,
            cfg=cfg,
        )

        self.assertEqual(payload, {"ok": True})
        self.assertIsNotNone(completions.kwargs)
        request = completions.kwargs or {}
        self.assertEqual(
            request["response_format"],
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_response",
                    "strict": True,
                    "schema": schema,
                },
            },
        )

    def test_strict_schema_normalization_adds_object_additional_properties(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                "outer": {
                    "type": "object",
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"label": {"type": "string"}},
                                "required": ["label"],
                            },
                        },
                    },
                    "required": ["items"],
                },
            },
            "required": ["outer"],
        }

        normalized = _normalize_strict_json_schema(schema)

        self.assertNotIn("additionalProperties", schema)
        self.assertFalse(normalized["additionalProperties"])
        outer_schema = normalized["properties"]["outer"]
        item_schema = outer_schema["properties"]["items"]["items"]
        self.assertFalse(outer_schema["additionalProperties"])
        self.assertFalse(item_schema["additionalProperties"])

    def test_aihubmix_structured_generation_always_uses_normalized_strict_json_schema(self) -> None:
        class FakeCompletions:
            def __init__(self):
                self.kwargs: dict | None = None

            def create(self, **kwargs):
                self.kwargs = kwargs
                message = types.SimpleNamespace(content='{"ok": true}')
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        completions = FakeCompletions()
        client = types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=completions,
            ),
        )
        schema = {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "nested": {
                    "type": "object",
                    "properties": {"label": {"type": "string"}},
                    "required": ["label"],
                },
            },
            "required": ["ok"],
        }
        cfg = SummaryDescriptionsConfig(
            generation_provider=AIHUBMIX_GENERATION_PROVIDER,
            generation_model="non_gemini_test_model",
            temperature=0.1,
        )

        payload = _generate_structured_json_aihubmix_chat(
            client=client,
            model=cfg.generation_model,
            system_instruction="Return JSON.",
            contents=["Prompt body."],
            response_schema=schema,
            cfg=cfg,
        )

        self.assertEqual(payload, {"ok": True})
        self.assertIsNotNone(completions.kwargs)
        request = completions.kwargs or {}
        response_format = request["response_format"]
        strict_schema = response_format["json_schema"]["schema"]
        self.assertEqual(request["messages"][1]["content"], "Prompt body.")
        self.assertNotIn("Response JSON schema:", request["messages"][1]["content"])
        self.assertNotIn('"nested"', request["messages"][1]["content"])
        self.assertEqual(response_format["type"], "json_schema")
        self.assertTrue(response_format["json_schema"]["strict"])
        self.assertFalse(strict_schema["additionalProperties"])
        self.assertFalse(strict_schema["properties"]["nested"]["additionalProperties"])

    def test_openai_chat_structured_generation_rejects_non_object_json(self) -> None:
        class FakeCompletions:
            def create(self, **kwargs):
                message = types.SimpleNamespace(content="[]")
                choice = types.SimpleNamespace(message=message)
                return types.SimpleNamespace(choices=[choice])

        client = types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=FakeCompletions(),
            ),
        )
        cfg = SummaryDescriptionsConfig(
            generation_provider=PACKYAPI_GENERATION_PROVIDER,
            generation_model=DEFAULT_GEMINI_MODEL,
        )

        with self.assertRaisesRegex(RuntimeError, "expected a JSON object"):
            _generate_structured_json_openai_chat(
                client=client,
                model=cfg.generation_model,
                system_instruction="Return JSON.",
                contents=["Prompt body."],
                response_schema={"type": "object", "properties": {}, "required": []},
                cfg=cfg,
            )

    def test_gemini_structured_generation_sends_schema_in_config_only(self) -> None:
        class FakeModels:
            def __init__(self):
                self.kwargs: dict | None = None

            def generate_content(self, **kwargs):
                self.kwargs = kwargs
                return types.SimpleNamespace(text='{"ok": true}')

        models = FakeModels()
        client = types.SimpleNamespace(models=models)
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }
        cfg = SummaryDescriptionsConfig(
            generation_provider="gemini",
            generation_model=DEFAULT_GEMINI_MODEL,
            temperature=0.1,
        )

        payload = _generate_structured_json_gemini(
            client=client,
            model=cfg.generation_model,
            system_instruction="Return JSON.",
            contents=["Prompt body."],
            response_schema=schema,
            cfg=cfg,
        )

        self.assertEqual(payload, {"ok": True})
        self.assertIsNotNone(models.kwargs)
        request = models.kwargs or {}
        config = request["config"]
        self.assertEqual(request["model"], DEFAULT_GEMINI_MODEL)
        self.assertEqual(request["contents"], ["Prompt body."])
        self.assertNotIn("Response JSON schema:", request["contents"][0])
        self.assertEqual(config["temperature"], 0.1)
        self.assertEqual(config["system_instruction"], "Return JSON.")
        self.assertEqual(config["response_mime_type"], "application/json")
        self.assertIs(config["response_json_schema"], schema)

    def test_generate_structured_json_defaults_to_aihubmix_provider(self) -> None:
        cfg = SummaryDescriptionsConfig()
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }

        with patch("brain_region_pipeline.core.genai.create_aihubmix_client") as create_client, patch(
            "brain_region_pipeline.core.genai._generate_structured_json_aihubmix_chat",
            return_value={"ok": True},
        ) as generate:
            payload = generate_structured_json(
                model=cfg.generation_model,
                system_instruction="Return JSON.",
                contents=["Prompt body."],
                response_schema=schema,
                cfg=cfg,
            )

        self.assertEqual(cfg.generation_provider, DEFAULT_GENERATION_PROVIDER)
        self.assertEqual(cfg.generation_model, DEFAULT_GENERATION_MODEL)
        self.assertEqual(cfg.generation_provider, AIHUBMIX_GENERATION_PROVIDER)
        self.assertEqual(cfg.generation_model, DEFAULT_AIHUBMIX_MODEL)
        self.assertEqual(payload, {"ok": True})
        create_client.assert_called_once()
        generate.assert_called_once()

    def test_generate_structured_json_does_not_retry_provider_errors(self) -> None:
        cfg = SummaryDescriptionsConfig()
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }

        with patch("brain_region_pipeline.core.genai.create_aihubmix_client") as create_client, patch(
            "brain_region_pipeline.core.genai._generate_structured_json_aihubmix_chat",
            side_effect=RuntimeError("provider failed"),
        ) as generate:
            with self.assertRaisesRegex(RuntimeError, "provider failed"):
                generate_structured_json(
                    model=cfg.generation_model,
                    system_instruction="Return JSON.",
                    contents=["Prompt body."],
                    response_schema=schema,
                    cfg=cfg,
                )

        create_client.assert_called_once()
        generate.assert_called_once()

    def test_generate_structured_json_keeps_gemini_retry_inside_sdk_client(self) -> None:
        cfg = SummaryDescriptionsConfig(
            generation_provider="gemini",
            generation_model=DEFAULT_GEMINI_MODEL,
        )
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }

        with patch("brain_region_pipeline.core.genai.create_genai_client") as create_client, patch(
            "brain_region_pipeline.core.genai._generate_structured_json_gemini",
            side_effect=RuntimeError("provider failed"),
        ) as generate:
            with self.assertRaisesRegex(RuntimeError, "provider failed"):
                generate_structured_json(
                    model=cfg.generation_model,
                    system_instruction="Return JSON.",
                    contents=["Prompt body."],
                    response_schema=schema,
                    cfg=cfg,
                )

        create_client.assert_called_once()
        generate.assert_called_once()

    def test_generate_structured_json_can_dispatch_to_aihubmix_provider(self) -> None:
        cfg = SummaryDescriptionsConfig(
            generation_provider=AIHUBMIX_GENERATION_PROVIDER,
            generation_model=DEFAULT_AIHUBMIX_MODEL,
        )
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }

        with patch("brain_region_pipeline.core.genai.create_aihubmix_client") as create_client, patch(
            "brain_region_pipeline.core.genai._generate_structured_json_aihubmix_chat",
            return_value={"ok": True},
        ) as generate:
            payload = generate_structured_json(
                model=cfg.generation_model,
                system_instruction="Return JSON.",
                contents=["Prompt body."],
                response_schema=schema,
                cfg=cfg,
            )

        self.assertEqual(payload, {"ok": True})
        create_client.assert_called_once()
        generate.assert_called_once()

    def test_generate_structured_json_can_dispatch_to_packyapi_provider(self) -> None:
        cfg = SummaryDescriptionsConfig(
            generation_provider=PACKYAPI_GENERATION_PROVIDER,
            generation_model=DEFAULT_PACKYAPI_MODEL,
        )
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }

        with patch("brain_region_pipeline.core.genai.create_packyapi_client") as create_client, patch(
            "brain_region_pipeline.core.genai._generate_structured_json_openai_chat",
            return_value={"ok": True},
        ) as generate:
            payload = generate_structured_json(
                model=cfg.generation_model,
                system_instruction="Return JSON.",
                contents=["Prompt body."],
                response_schema=schema,
                cfg=cfg,
            )

        self.assertEqual(payload, {"ok": True})
        create_client.assert_called_once()
        generate.assert_called_once()

    def test_generate_structured_json_can_dispatch_to_gemini_provider(self) -> None:
        cfg = SummaryDescriptionsConfig(
            generation_provider="gemini",
            generation_model="gemini-3-flash-preview",
        )
        schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
        }

        with patch("brain_region_pipeline.core.genai.create_genai_client") as create_client, patch(
            "brain_region_pipeline.core.genai._generate_structured_json_gemini",
            return_value={"ok": True},
        ) as generate:
            payload = generate_structured_json(
                model=cfg.generation_model,
                system_instruction="Return JSON.",
                contents=["Prompt body."],
                response_schema=schema,
                cfg=cfg,
            )

        self.assertEqual(payload, {"ok": True})
        create_client.assert_called_once()
        generate.assert_called_once()

    def test_region_schema_meta_prompt_requests_region_feature_schema(self) -> None:
        parcels: list[dict[str, str | int]] = [
            {"network": "Yeo7_7_Default", "sub_region": "A8m", "hemisphere": "LH", "idx_0based": 0, "idx_1based": 1},
            {"network": "Yeo7_6_Frontoparietal", "sub_region": "A8m", "hemisphere": "RH", "idx_0based": 1, "idx_1based": 2},
        ]
        cfg = RegionSchemaConfig(target_region="vmPFC")
        pool = _sample_domain_pool(curation_status="confirmed")

        prompt = _build_prompt(parcels, cfg, pool)
        schema = _region_schema_response_schema()
        dimension_schema = schema["properties"]["dimensions"]["items"]
        dimension_required = dimension_schema["required"]
        trigger_schema = dimension_schema["properties"]["trigger_list"]
        example_schema = dimension_schema["properties"]["calibration_examples"]
        anchor_schema = dimension_schema["properties"]["graded_anchors"]

        self.assertIn("region-level feature schema", REGION_SCHEMA_SYSTEM_INSTRUCTION)
        required_fragments = (
            "Confirmed coarse-domain pool",
            "emotion_experience",
            "reference granularity",
            "Do not force the same",
            "label count as emotion_experience",
            "grouping labels only",
            "Do not score a domain directly",
            "Do not copy a domain_id into dimension_id",
            "finer-grained, text-scoreable variable",
            f"{MIN_NON_EMOTION_DIMENSIONS_PER_DOMAIN} to {MAX_NON_EMOTION_DIMENSIONS_PER_DOMAIN} concrete",
            "local quality gate rejects",
            "only 1 or 2",
            f"{MIN_DIMENSION_TRIGGERS} to {MAX_DIMENSION_TRIGGERS} concise",
            f"{MIN_DIMENSION_CALIBRATION_EXAMPLES} to {MAX_DIMENSION_CALIBRATION_EXAMPLES} calibration_examples",
            "emotion_<label>",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, prompt)
        self.assertNotIn("module_id", prompt)
        self.assertNotIn("display_name", prompt)
        self.assertNotIn("simulation_prompt", prompt)
        self.assertNotIn("output order", prompt)
        self.assertEqual(trigger_schema["minItems"], MIN_DIMENSION_TRIGGERS)
        self.assertEqual(trigger_schema["maxItems"], MAX_DIMENSION_TRIGGERS)
        self.assertEqual(example_schema["minItems"], MIN_DIMENSION_CALIBRATION_EXAMPLES)
        self.assertEqual(example_schema["maxItems"], MAX_DIMENSION_CALIBRATION_EXAMPLES)
        self.assertEqual(anchor_schema["required"], list(DIMENSION_ANCHOR_LABELS))
        self.assertIn("functional_hypothesis", schema["required"])
        self.assertIn("scoring_instruction", schema["required"])
        self.assertIn("dimension_id", dimension_required)
        self.assertIn("domain", dimension_required)
        self.assertNotIn("name", dimension_required)

    def test_region_schema_metadata_and_dimensions_round_trip(self) -> None:
        schema = _sample_region_schema(
            metadata={"domain_pool": {"content_sha256": "abc123"}},
        )
        loaded = RegionFeatureSchema.from_dict(schema.to_dict())

        self.assertEqual(loaded.version, REGION_SCHEMA_VERSION)
        self.assertEqual(loaded.metadata["domain_pool"]["content_sha256"], "abc123")
        self.assertEqual(loaded.active_domain_ids, ("emotion_experience", "subjective_valuation"))
        dimension = loaded.dimensions[0]
        self.assertEqual(dimension.dimension_id, "emotion_admiration")
        self.assertEqual(dimension.domain, EMOTION_EXPERIENCE_DOMAIN_ID)
        self.assertNotIn("name", dimension.to_dict())

    def test_scorer_prompt_renders_dimension_metadata(self) -> None:
        block = _schema_prompt_block(_sample_region_schema())

        self.assertIn("target_region: vmPFC", block)
        self.assertIn("scoring_instruction:", block)
        self.assertIn("domain: emotion_experience", block)
        self.assertIn("trigger_list:", block)
        self.assertIn("graded_anchors:", block)
        self.assertIn("calibration_examples:", block)
        self.assertIn("scoreability_note:", block)
        self.assertIn("exclusion_note:", block)

    def test_region_schema_quality_requires_core_emotion_panel(self) -> None:
        schema = _sample_region_schema()
        validate_region_schema_quality(schema, _sample_domain_pool(curation_status="confirmed"))

        missing_core = tuple(
            dimension for dimension in schema.dimensions
            if dimension.dimension_id != "emotion_agitation"
        )
        bad_schema = replace(
            schema,
            dimensions=missing_core,
            active_domain_ids=(EMOTION_EXPERIENCE_DOMAIN_ID, "subjective_valuation"),
        )

        with self.assertRaisesRegex(ValueError, "missing core emotion"):
            validate_region_schema_quality(bad_schema, _sample_domain_pool(curation_status="confirmed"))

    def test_region_schema_quality_does_not_force_emotion_panel_for_non_vmpfc(self) -> None:
        pool = _sample_non_emotion_domain_pool()
        schema = _sample_non_emotion_region_schema()

        prompt = _build_prompt([], RegionSchemaConfig(target_region="PCC"), pool)
        validate_region_schema_quality(schema, pool)

        self.assertNotIn("Emotion-experience requirements", prompt)
        self.assertNotIn("emotion_<label>", prompt)
        self.assertNotIn("core labels", prompt)

    def test_region_schema_quality_allows_valid_per_domain_dimension_count(self) -> None:
        pool = _sample_non_emotion_domain_pool()
        schema = _sample_non_emotion_region_schema()

        self.assertGreaterEqual(len(schema.dimensions), MIN_NON_EMOTION_DIMENSIONS_PER_DOMAIN)
        self.assertLessEqual(len(schema.dimensions), MAX_NON_EMOTION_DIMENSIONS_PER_DOMAIN)
        validate_region_schema_quality(schema, pool)

    def test_region_schema_quality_rejects_too_many_dimension_triggers(self) -> None:
        pool = _sample_domain_pool(curation_status="confirmed")
        schema = _sample_region_schema()
        too_many_triggers = tuple(
            f"trigger {idx}" for idx in range(MAX_DIMENSION_TRIGGERS + 1)
        )
        bad_schema = replace(
            schema,
            dimensions=(
                replace(schema.dimensions[0], trigger_list=too_many_triggers),
                *schema.dimensions[1:],
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            f"trigger_list must include {MIN_DIMENSION_TRIGGERS} to "
            f"{MAX_DIMENSION_TRIGGERS} items",
        ):
            validate_region_schema_quality(bad_schema, pool)

    def test_region_schema_quality_rejects_too_many_calibration_examples(self) -> None:
        pool = _sample_domain_pool(curation_status="confirmed")
        schema = _sample_region_schema()
        too_many_examples = tuple(
            {"scene": f"Example {idx}.", "score": idx % (DIMENSION_SCORE_MAX + 1)}
            for idx in range(MAX_DIMENSION_CALIBRATION_EXAMPLES + 1)
        )
        bad_schema = replace(
            schema,
            dimensions=(
                replace(schema.dimensions[0], calibration_examples=too_many_examples),
                *schema.dimensions[1:],
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            f"calibration_examples must include "
            f"{MIN_DIMENSION_CALIBRATION_EXAMPLES} to "
            f"{MAX_DIMENSION_CALIBRATION_EXAMPLES} items",
        ):
            validate_region_schema_quality(bad_schema, pool)

    def test_region_schema_quality_rejects_too_few_dimensions_per_non_emotion_domain(self) -> None:
        pool = _sample_non_emotion_domain_pool()
        schema = _sample_non_emotion_region_schema()
        too_small_schema = replace(
            schema,
            dimensions=schema.dimensions[: MIN_NON_EMOTION_DIMENSIONS_PER_DOMAIN - 1],
            active_domain_ids=("social_context",),
        )

        with self.assertRaisesRegex(
            ValueError,
            f"{MIN_NON_EMOTION_DIMENSIONS_PER_DOMAIN} to "
            f"{MAX_NON_EMOTION_DIMENSIONS_PER_DOMAIN} active dimensions",
        ):
            validate_region_schema_quality(too_small_schema, pool)

    def test_region_schema_quality_rejects_too_many_dimensions_per_non_emotion_domain(self) -> None:
        pool = _sample_non_emotion_domain_pool()
        schema = _sample_non_emotion_region_schema()
        too_many_dimensions = tuple(
            _dimension(f"social_context_extra_{idx:02d}", "social_context")
            for idx in range(MAX_NON_EMOTION_DIMENSIONS_PER_DOMAIN + 1)
        )
        too_large_schema = replace(
            schema,
            dimensions=too_many_dimensions,
            active_domain_ids=("social_context",),
        )

        with self.assertRaisesRegex(
            ValueError,
            f"{MIN_NON_EMOTION_DIMENSIONS_PER_DOMAIN} to "
            f"{MAX_NON_EMOTION_DIMENSIONS_PER_DOMAIN} active dimensions",
        ):
            validate_region_schema_quality(too_large_schema, pool)

    def test_region_schema_quality_rejects_domain_as_dimension(self) -> None:
        pool = _sample_non_emotion_domain_pool()
        schema = _sample_non_emotion_region_schema()
        domain_dimension = _dimension("social_context", "social_context")
        bad_schema = replace(
            schema,
            dimensions=(domain_dimension,),
            active_domain_ids=("social_context",),
        )

        with self.assertRaisesRegex(ValueError, "not repeat the domain_id"):
            validate_region_schema_quality(bad_schema, pool)

    def test_region_schema_quality_rejects_any_domain_id_as_dimension_id(self) -> None:
        pool = _sample_domain_pool(curation_status="confirmed")
        schema = _sample_region_schema()
        copied_domain_id = _dimension("subjective_valuation", EMOTION_EXPERIENCE_DOMAIN_ID)
        bad_schema = replace(
            schema,
            dimensions=(*schema.dimensions, copied_domain_id),
        )

        with self.assertRaisesRegex(ValueError, "must not reuse a confirmed domain_id"):
            validate_region_schema_quality(bad_schema, pool)

    def test_region_schema_quality_rejects_vmpfc_emotion_prefix_outside_emotion_experience(self) -> None:
        pool = _sample_domain_pool(curation_status="confirmed")
        schema = _sample_region_schema()
        bad_schema = replace(
            schema,
            dimensions=(*schema.dimensions, _dimension("emotion_inference", "subjective_valuation")),
        )

        with self.assertRaisesRegex(ValueError, "emotion_\\* dimensions must use domain"):
            validate_region_schema_quality(bad_schema, pool)

    def test_region_schema_quality_allows_non_vmpfc_emotion_prefix_in_specific_domain(self) -> None:
        pool = _sample_non_emotion_domain_pool()
        schema = _sample_non_emotion_region_schema()
        dimensions = (
            _dimension("emotion_inference", "social_context"),
            *(
                _dimension(f"social_context_{idx:02d}", "social_context")
                for idx in range(1, MIN_NON_EMOTION_DIMENSIONS_PER_DOMAIN)
            ),
        )
        adjusted_schema = replace(
            schema,
            dimensions=dimensions,
            active_domain_ids=("social_context",),
        )

        validate_region_schema_quality(adjusted_schema, pool)

    def test_region_schema_normalizes_dimension_order_in_code(self) -> None:
        schema = _sample_region_schema()
        moved = replace(
            schema,
            dimensions=(
                schema.dimensions[8],
                schema.dimensions[2],
                schema.dimensions[0],
                *schema.dimensions[1:2],
                *schema.dimensions[3:8],
                *schema.dimensions[9:],
            ),
        )

        normalized = normalize_schema_dimension_order(moved)

        self.assertEqual(
            normalized.ordered_dimension_ids()[:8],
            list(CORE_EMOTION_DIMENSION_IDS),
        )
        self.assertEqual(normalized.ordered_dimension_ids()[8], "valuation_signal_01")

    def test_domain_pool_requires_auditable_curated_source_evidence(self) -> None:
        candidate = _sample_domain_pool().candidate_domains[0]

        with self.assertRaisesRegex(ValueError, "source_domain_ids"):
            DomainPool(
                target_region="vmPFC",
                candidate_domains=(candidate,),
                curated_domains=(
                    CuratedDomain(
                        domain_id=EMOTION_EXPERIENCE_DOMAIN_ID,
                        definition="Concrete emotional subtargets.",
                        vmpfc_relevance="Relevant to vmPFC affective appraisal.",
                        scoreability_note="Use affective evidence from text.",
                        consolidation_rationale="Retained as a coarse domain.",
                    ),
                ),
            )

    def test_domain_pool_validation_requires_required_domain(self) -> None:
        pool = _sample_domain_pool()
        without_required = replace(
            pool,
            curated_domains=(pool.curated_domains[1],),
        )

        with self.assertRaisesRegex(ValueError, "emotion_experience"):
            validate_required_domains(without_required)

    def test_domain_pool_validation_does_not_force_required_domain_for_non_vmpfc(self) -> None:
        pool = _sample_non_emotion_domain_pool()

        validate_required_domains(pool)

        self.assertEqual(required_domain_candidates("PCC"), [])

    def test_domain_pool_validation_requires_required_seed_evidence(self) -> None:
        pool = _sample_domain_pool()
        without_seed_evidence = replace(
            pool,
            curated_domains=(
                replace(
                    pool.curated_domains[0],
                    source_domain_ids=("run_1_emotion_experience",),
                    source_runs=(1,),
                    proposal_frequency=1,
                ),
                pool.curated_domains[1],
            ),
        )

        with self.assertRaisesRegex(ValueError, REQUIRED_EMOTION_EXPERIENCE_SOURCE_ID):
            validate_required_domains(without_seed_evidence)

    def test_domain_pool_requires_frequency_to_match_source_runs(self) -> None:
        pool = _sample_domain_pool()

        with self.assertRaisesRegex(ValueError, "proposal_frequency"):
            replace(
                pool,
                curated_domains=(
                    replace(pool.curated_domains[0], proposal_frequency=2),
                    pool.curated_domains[1],
                ),
            )

    def test_domain_pool_json_requires_curated_proposal_frequency(self) -> None:
        payload = _sample_domain_pool().to_dict()
        del payload["curated_domains"][0]["proposal_frequency"]

        with self.assertRaisesRegex(ValueError, "proposal_frequency"):
            DomainPool.from_dict(payload)

    def test_domain_pool_writes_region_relevance_and_reads_legacy_vmpfc_relevance(self) -> None:
        payload = _sample_domain_pool().to_dict()
        self.assertIn("region_relevance", payload["candidate_domains"][0])
        self.assertNotIn("vmpfc_relevance", payload["candidate_domains"][0])

        payload["candidate_domains"][0]["vmpfc_relevance"] = payload["candidate_domains"][0].pop("region_relevance")
        payload["curated_domains"][0]["vmpfc_relevance"] = payload["curated_domains"][0].pop("region_relevance")
        loaded = DomainPool.from_dict(payload)

        self.assertEqual(
            loaded.candidate_domains[0].region_relevance,
            str(_canonical_emotion_seed()["region_relevance"]),
        )
        self.assertEqual(
            loaded.curated_domains[0].region_relevance,
            "Relevant to vmPFC affective meaning.",
        )

    def test_domain_pool_requires_rejected_or_merged_reason(self) -> None:
        sample = _sample_domain_pool()

        with self.assertRaisesRegex(ValueError, "must include a reason"):
            DomainPool(
                target_region="vmPFC",
                candidate_domains=sample.candidate_domains,
                curated_domains=sample.curated_domains,
                rejected_or_merged_domains=(
                    RejectedOrMergedDomain(
                        domain_id="generic_valence",
                        decision="rejected",
                        reason="",
                        source_domain_ids=("run_1_generic_valence",),
                        source_runs=(1,),
                    ),
                ),
            )

    def test_domain_pool_proposal_prompt_renders_viewer_perspective_and_required_anchor(self) -> None:
        parcels: list[dict[str, str | int]] = [
            {
                "network": "Yeo7_7_Default",
                "sub_region": "Frontal_Med_Orb",
                "hemisphere": "LH",
                "idx_0based": 0,
                "idx_1based": 1,
            },
        ]

        prompt = _build_domain_proposal_prompt(
            parcels,
            DomainPoolConfig(target_region="vmPFC", proposal_runs=1),
            run_index=1,
        )

        self.assertIn("Viewer-Centric Perspective", prompt)
        self.assertIn("typical viewer watching the movie", prompt)
        self.assertIn("not the subject of the domain", prompt)
        self.assertIn(str(_canonical_emotion_seed()["definition"]), prompt)
        self.assertIn("keep this definition exactly unchanged", prompt)

    def test_domain_pool_consolidation_prompt_treats_candidates_as_evidence(self) -> None:
        candidates = [
            _required_candidate(),
            CandidateDomain(
                domain_id="run_1_emotion_experience",
                definition="The emotion a character experiences.",
                region_relevance="VMPFC is relevant to affective appraisal.",
                scoreability_note="Use character emotion evidence.",
                source_run=1,
            ),
        ]

        prompt = _build_domain_consolidation_prompt(
            candidates,
            DomainPoolConfig(target_region="vmPFC", proposal_runs=1),
        )

        self.assertIn("Required Anchors", prompt)
        self.assertIn("keep this definition exactly unchanged", prompt)
        self.assertIn("Candidate domains are provided below as JSON", prompt)
        self.assertIn("Do not treat candidate definitions as automatically authoritative", prompt)
        self.assertIn(REQUIRED_EMOTION_EXPERIENCE_SOURCE_ID, prompt)

    def test_domain_pool_validation_requires_required_canonical_definition(self) -> None:
        pool = _sample_domain_pool()
        character_centric = replace(
            pool,
            curated_domains=(
                replace(
                    pool.curated_domains[0],
                    definition="The subjective feeling state that a character experiences.",
                ),
                pool.curated_domains[1],
            ),
        )

        with self.assertRaisesRegex(ValueError, "canonical definition"):
            validate_required_domains(character_centric)

    def test_build_domain_pool_rejects_invalid_consolidated_source_ids_without_retry(self) -> None:
        parcels: list[dict[str, str | int]] = [
            {"network": "Yeo7_7_Default", "sub_region": "PCC", "hemisphere": "LH", "idx_0based": 0, "idx_1based": 1},
        ]
        proposal = {
            "candidate_domains": [
                {
                    "domain_id": "social_context",
                    "definition": "Social context and relationship state.",
                    "region_relevance": "Relevant to narrative social integration.",
                    "scoreability_note": "Use explicit social evidence in descriptions.",
                },
            ],
        }
        invalid_consolidation = {
            "curated_domains": [
                {
                    "domain_id": "social_context",
                    "definition": "Social context and relationship state.",
                    "region_relevance": "Relevant to narrative social integration.",
                    "scoreability_note": "Use explicit social evidence in descriptions.",
                    "source_domain_ids": ["coarse_1"],
                    "consolidation_rationale": "Retained as target-region relevant.",
                },
            ],
            "rejected_or_merged_domains": [],
        }
        with patch("brain_region_pipeline.schema_design.domain_pool.generate_structured_json") as generate:
            generate.side_effect = [proposal, invalid_consolidation]
            with self.assertRaisesRegex(RuntimeError, "unknown source_domain_ids"):
                build_domain_pool(
                    parcels,
                    DomainPoolConfig(
                        target_region="PCC",
                        proposal_runs=1,
                    ),
                )

        self.assertEqual(generate.call_count, 2)

    def test_build_domain_pool_rejects_malformed_candidate_payload_without_retry(self) -> None:
        parcels: list[dict[str, str | int]] = [
            {"network": "Yeo7_7_Default", "sub_region": "PCC", "hemisphere": "LH", "idx_0based": 0, "idx_1based": 1},
        ]
        malformed_proposal = {
            "candidate_domains": [
                {
                    "domain_id": "social_context",
                    "region_relevance": "Relevant to narrative social integration.",
                    "scoreability_note": "Use explicit social evidence in descriptions.",
                },
            ],
        }
        with patch("brain_region_pipeline.schema_design.domain_pool.generate_structured_json") as generate:
            generate.side_effect = [malformed_proposal]
            with self.assertRaisesRegex(RuntimeError, "malformed candidate_domains"):
                build_domain_pool(
                    parcels,
                    DomainPoolConfig(
                        target_region="PCC",
                        proposal_runs=1,
                    ),
                )

        self.assertEqual(generate.call_count, 1)

    def test_build_domain_pool_rejects_required_definition_drift_without_retry(self) -> None:
        parcels: list[dict[str, str | int]] = [
            {
                "network": "Yeo7_7_Default",
                "sub_region": "Frontal_Med_Orb",
                "hemisphere": "LH",
                "idx_0based": 0,
                "idx_1based": 1,
            },
        ]
        proposal = {
            "candidate_domains": [
                {
                    "domain_id": "subjective_value",
                    "definition": "Viewer inference about subjective value.",
                    "region_relevance": "Relevant to vmPFC value integration.",
                    "scoreability_note": "Use goals, outcomes, and choices.",
                },
            ],
        }
        drifted_consolidation = {
            "curated_domains": [
                {
                    "domain_id": EMOTION_EXPERIENCE_DOMAIN_ID,
                    "definition": "The emotion a character experiences in the scene.",
                    "region_relevance": "Relevant to vmPFC affective appraisal.",
                    "scoreability_note": "Use character emotion evidence.",
                    "source_domain_ids": [REQUIRED_EMOTION_EXPERIENCE_SOURCE_ID],
                    "consolidation_rationale": "Retained as required anchor.",
                },
            ],
            "rejected_or_merged_domains": [],
        }
        with patch("brain_region_pipeline.schema_design.domain_pool.generate_structured_json") as generate:
            generate.side_effect = [proposal, drifted_consolidation]
            with self.assertRaisesRegex(RuntimeError, "canonical definition"):
                build_domain_pool(
                    parcels,
                    DomainPoolConfig(
                        target_region="vmPFC",
                        proposal_runs=1,
                    ),
                )

        self.assertEqual(generate.call_count, 2)

    def test_build_domain_pool_fails_when_required_definition_drifts(self) -> None:
        parcels: list[dict[str, str | int]] = [
            {
                "network": "Yeo7_7_Default",
                "sub_region": "Frontal_Med_Orb",
                "hemisphere": "LH",
                "idx_0based": 0,
                "idx_1based": 1,
            },
        ]
        proposal = {
            "candidate_domains": [
                {
                    "domain_id": "subjective_value",
                    "definition": "Viewer inference about subjective value.",
                    "region_relevance": "Relevant to vmPFC value integration.",
                    "scoreability_note": "Use goals, outcomes, and choices.",
                },
            ],
        }
        drifted_consolidation = {
            "curated_domains": [
                {
                    "domain_id": EMOTION_EXPERIENCE_DOMAIN_ID,
                    "definition": "The emotion a character experiences in the scene.",
                    "region_relevance": "Relevant to vmPFC affective appraisal.",
                    "scoreability_note": "Use character emotion evidence.",
                    "source_domain_ids": [REQUIRED_EMOTION_EXPERIENCE_SOURCE_ID],
                    "consolidation_rationale": "Retained as required anchor.",
                },
            ],
            "rejected_or_merged_domains": [],
        }

        with patch("brain_region_pipeline.schema_design.domain_pool.generate_structured_json") as generate:
            generate.side_effect = [
                proposal,
                drifted_consolidation,
            ]
            with self.assertRaisesRegex(RuntimeError, "canonical definition"):
                build_domain_pool(
                    parcels,
                    DomainPoolConfig(
                        target_region="vmPFC",
                        proposal_runs=1,
                    ),
                )

        self.assertEqual(generate.call_count, 2)

    def test_parse_description_text_reads_timestamped_blocks(self) -> None:
        text = """
00:00 - 00:01  In a kitchen area, Ross stands holding a white phone.

00:01 - 00:09  Ross raises the phone and says he will order another pizza.
He promises to show Chandler how well he can flirt.
"""

        segments = parse_description_text(text)

        self.assertEqual(
            segments,
            [
                DescriptionSegment(
                    start_s=0.0,
                    end_s=1.0,
                    description="In a kitchen area, Ross stands holding a white phone.",
                ),
                DescriptionSegment(
                    start_s=1.0,
                    end_s=9.0,
                    description=(
                        "Ross raises the phone and says he will order another pizza. "
                        "He promises to show Chandler how well he can flirt."
                    ),
                ),
            ],
        )

    def test_parse_description_text_skips_markdown_segment_header(self) -> None:
        text = """
# Segment 4
**Time Range:** 00:09:11-00:11:04

00:00 - 00:01  In a kitchen area with shelves of food, Ross stands holding a white cordless phone.

00:01 - 00:09  Ross raises the phone to chest level and says, "right."
"""

        segments = parse_description_text(text)

        self.assertEqual(len(segments), 2)
        self.assertEqual(
            segments[0],
            DescriptionSegment(
                start_s=0.0,
                end_s=1.0,
                description="In a kitchen area with shelves of food, Ross stands holding a white cordless phone.",
            ),
        )
        self.assertEqual(segments[1].start_s, 1.0)
        self.assertEqual(segments[1].end_s, 9.0)

    def test_parse_description_text_reads_friends_markdown_lines(self) -> None:
        text = """
# Complete Video Description

**Movie:** mv_friends_s01e01a

---

00:00 - 00:05  A black screen displays opening credits.
00:05 - 00:10  The setting changes to a city skyline.
00:10 - 00:14  The view holds on tall buildings.
Continuation sentence for the same shot.
"""

        segments = parse_description_text(text)

        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0].start_s, 0.0)
        self.assertEqual(segments[0].end_s, 5.0)
        self.assertEqual(
            segments[2].description,
            "The view holds on tall buildings. Continuation sentence for the same shot.",
        )

    def test_summarize_description_segments_builds_rolling_rows(self) -> None:
        segments = [
            DescriptionSegment(0.0, 1.0, "Opening scene."),
            DescriptionSegment(1.0, 2.0, "The group jokes together."),
            DescriptionSegment(2.0, 3.0, "A friend enters with news."),
        ]
        cfg = SummaryDescriptionsConfig(
            generation_model="fake-model",
            summary_batch_size=2,
        )
        payloads = [
            {
                "batch_summary": "The first batch introduces the friends and their playful tone.",
                "cumulative_summary": "The story opens with friends sharing a light comic rhythm.",
            },
            {
                "batch_summary": "A new arrival changes the conversation.",
                "cumulative_summary": "The friends begin in a comic setting before a new arrival shifts the scene.",
            },
        ]

        with patch("brain_region_pipeline.scoring.summary_generator.generate_structured_json") as generate:
            generate.side_effect = payloads
            rows = summarize_description_segments(segments, cfg)

        prompts = [call.kwargs["contents"][0] for call in generate.call_args_list]
        self.assertIn("Beginning of the movie", prompts[0])
        self.assertIn(payloads[0]["cumulative_summary"], prompts[1])
        self.assertEqual(rows[0]["batch_idx"], 0)
        self.assertEqual(rows[0]["segment_start"], 0)
        self.assertEqual(rows[0]["segment_end"], 1)
        self.assertEqual(rows[0]["timestamp_range"], "00:00:00 - 00:00:02")
        self.assertEqual(rows[1]["segment_start"], 2)
        self.assertEqual(rows[1]["segment_end"], 2)

    def test_summarize_descriptions_cli_writes_summary_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            descriptions = root / "description.md"
            description_lines = [
                "# Complete Video Description",
                "**Movie:** mv_friends_s01e01a",
                "---",
            ]
            description_lines.extend(
                f"00:{idx:02d} - 00:{idx + 1:02d}  Segment {idx}."
                for idx in range(41)
            )
            descriptions.write_text("\n".join(description_lines), encoding="utf-8")
            output_file = root / "summary" / "summary.json"
            payloads = [
                {
                    "batch_summary": "The first forty segments establish the opening situation.",
                    "cumulative_summary": "The story begins by establishing the opening situation.",
                },
                {
                    "batch_summary": "The final segment closes this small test batch.",
                    "cumulative_summary": "The story begins with an opening situation and closes the test batch.",
                },
            ]

            with patch("brain_region_pipeline.scoring.summary_generator.generate_structured_json") as generate:
                generate.side_effect = payloads
                stdout = self._run_main(
                    [
                        "summarize-descriptions",
                        "--descriptions",
                        str(descriptions),
                        "--output-file",
                        str(output_file),
                    ],
                    self._deps(),
                )

            summary_rows = json.loads(output_file.read_text(encoding="utf-8"))
            metadata = json.loads(
                (output_file.parent / "summary_metadata.json").read_text(encoding="utf-8"),
            )

        self.assertIn("Generate rolling summaries", stdout)
        self.assertEqual(len(summary_rows), 2)
        self.assertEqual(summary_rows[0]["segment_start"], 0)
        self.assertEqual(summary_rows[0]["segment_end"], 39)
        self.assertEqual(summary_rows[1]["segment_start"], 40)
        self.assertEqual(summary_rows[1]["segment_end"], 40)
        self.assertEqual(metadata["command"], "summarize-descriptions")
        self.assertEqual(metadata["summary_batch_size"], 40)
        self.assertEqual(metadata["n_segments"], 41)
        self.assertEqual(metadata["n_batches"], 2)

    def test_summarize_description_segments_rejects_empty_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "no segments"):
            summarize_description_segments([], SummaryDescriptionsConfig())

    def test_make_region_schema_writes_schema(self) -> None:
        deps = self._deps()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            atlas = self._write_atlas(root)
            domain_pool_file = root / "vmpfc_domain_pool.json"
            domain_pool_file.write_text(
                json.dumps(_sample_domain_pool(curation_status="confirmed").to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            output_file = root / "vmpfc_region_schema.json"
            stdout = self._run_main(
                [
                    "make-region-schema",
                    "--atlas-labels",
                    str(atlas),
                    "--target-region",
                    "vmPFC",
                    "--domain-pool",
                    str(domain_pool_file),
                    "--output-file",
                    str(output_file),
                ],
                deps,
            )
            payload = json.loads(output_file.read_text(encoding="utf-8"))

        self.assertIn("Build region feature schema", stdout)
        self.assertEqual(payload["version"], REGION_SCHEMA_VERSION)
        self.assertNotIn("modules", payload)
        self.assertEqual(payload["dimensions"][0]["dimension_id"], "emotion_admiration")
        self.assertIn("active_domain_ids", payload)

    def test_make_domain_pool_writes_draft_pool(self) -> None:
        deps = self._deps()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            atlas = self._write_atlas(root)
            output_file = root / "vmpfc_domain_pool.json"
            stdout = self._run_main(
                [
                    "make-domain-pool",
                    "--atlas-labels",
                    str(atlas),
                    "--target-region",
                    "vmPFC",
                    "--proposal-runs",
                    "2",
                    "--output-file",
                    str(output_file),
                ],
                deps,
            )
            pool = load_domain_pool(output_file)

        self.assertIn("Build draft domain pool from 2 proposal run", stdout)
        self.assertEqual(pool.version, DOMAIN_POOL_VERSION)
        self.assertEqual(pool.curation_status, "draft")
        self.assertEqual(pool.proposal_runs, 2)
        self.assertEqual(pool.curated_domains[0].domain_id, EMOTION_EXPERIENCE_DOMAIN_ID)
        self.assertEqual(pool.candidate_domains[0].source_run, 0)

    def test_make_region_schema_rejects_draft_domain_pool(self) -> None:
        deps = self._deps()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            atlas = self._write_atlas(root)
            domain_pool_file = root / "vmpfc_domain_pool.json"
            domain_pool_file.write_text(
                json.dumps(_sample_domain_pool(curation_status="draft").to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "curation_status='confirmed'"):
                self._run_main(
                    [
                        "make-region-schema",
                        "--atlas-labels",
                        str(atlas),
                        "--target-region",
                        "vmPFC",
                        "--domain-pool",
                        str(domain_pool_file),
                        "--output-file",
                        str(root / "vmpfc_region_schema.json"),
                    ],
                    deps,
                )

    def test_make_region_schema_rejects_target_region_mismatch(self) -> None:
        deps = self._deps()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            atlas = self._write_atlas(root)
            domain_pool_file = root / "other_region_domain_pool.json"
            domain_pool_file.write_text(
                json.dumps(
                    _sample_domain_pool(
                        curation_status="confirmed",
                        target_region="amygdala",
                    ).to_dict(),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "target_region must match"):
                self._run_main(
                    [
                        "make-region-schema",
                        "--atlas-labels",
                        str(atlas),
                        "--target-region",
                        "vmPFC",
                        "--domain-pool",
                        str(domain_pool_file),
                        "--output-file",
                        str(root / "vmpfc_region_schema.json"),
                    ],
                    deps,
                )

    def test_make_region_schema_records_confirmed_domain_pool_provenance(self) -> None:
        deps = self._deps()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            atlas = self._write_atlas(root)
            domain_pool_file = root / "vmpfc_domain_pool.json"
            domain_pool_file.write_text(
                json.dumps(_sample_domain_pool(curation_status="confirmed").to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            output_file = root / "vmpfc_region_schema.json"

            stdout = self._run_main(
                [
                    "make-region-schema",
                    "--atlas-labels",
                    str(atlas),
                    "--target-region",
                    "vmPFC",
                    "--domain-pool",
                    str(domain_pool_file),
                    "--output-file",
                    str(output_file),
                ],
                deps,
            )
            payload = json.loads(output_file.read_text(encoding="utf-8"))

        metadata = payload["metadata"]["domain_pool"]
        self.assertIn("Load confirmed domain pool", stdout)
        self.assertEqual(metadata["source_path"], str(domain_pool_file))
        self.assertEqual(metadata["target_region"], "vmPFC")
        self.assertEqual(metadata["curation_status"], "confirmed")
        self.assertEqual(metadata["curated_domain_ids"], ["emotion_experience", "subjective_valuation"])
        self.assertRegex(metadata["content_sha256"], r"^[0-9a-f]{64}$")

    def test_score_descriptions_writes_segment_scores_and_tr_features(self) -> None:
        deps = self._deps()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            descriptions = root / "description.txt"
            descriptions.write_text(
                "\n".join(
                    [
                        "00:00 - 00:01  Ross holds a phone in the kitchen.",
                        "",
                        "00:01 - 00:03  Ross says he will get the pizza woman's phone number.",
                    ],
                ),
                encoding="utf-8",
            )
            schema_file = root / "vmpfc_region_schema.json"
            schema_file.write_text(
                json.dumps(_sample_region_schema().to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            output_dir = root / "scored"

            stdout = self._run_main(
                [
                    "score-descriptions",
                    "--descriptions",
                    str(descriptions),
                    "--region-schema",
                    str(schema_file),
                    "--output-dir",
                    str(output_dir),
                    "--tr-s",
                    "1.0",
                    "--total-trs",
                    "3",
                ],
                deps,
            )

            score_rows = self._read_jsonl(output_dir / "segment_region_scores.jsonl")
            tr_rows = self._read_jsonl(output_dir / "tr_features.jsonl")
            metadata = json.loads((output_dir / "scoring_metadata.json").read_text(encoding="utf-8"))
            progress = json.loads((output_dir / "scoring_progress.json").read_text(encoding="utf-8"))

        self.assertIn("Score 2 description segments", stdout)
        self.assertEqual(score_rows[1]["segment_id"], 1)
        self.assertEqual(score_rows[1]["batch_idx"], 0)
        self.assertEqual(score_rows[1]["dimension_scores"]["emotion_admiration"], 1.2)
        self.assertEqual(metadata["feature_names"][0], "emotion_admiration")
        self.assertEqual(progress["status"], "complete")
        self.assertEqual(progress["completed_segments"], 2)
        self.assertEqual(metadata["feature_metadata"][0]["domain"], "emotion_experience")
        self.assertEqual(tr_rows[0]["feature_vector"][0], 0.2)
        self.assertEqual(tr_rows[2]["feature_vector"][0], 1.2)

    def test_score_descriptions_rejects_existing_outputs_without_resume_or_overwrite(self) -> None:
        deps = self._deps()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            descriptions = root / "description.txt"
            descriptions.write_text("00:00 - 00:01  Ross holds a phone.", encoding="utf-8")
            schema_file = root / "vmpfc_region_schema.json"
            schema_file.write_text(
                json.dumps(_sample_region_schema().to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            output_dir = root / "scored"
            argv = [
                "score-descriptions",
                "--descriptions",
                str(descriptions),
                "--region-schema",
                str(schema_file),
                "--output-dir",
                str(output_dir),
                "--tr-s",
                "1.0",
            ]

            self._run_main(argv, deps)
            with self.assertRaisesRegex(ValueError, "Use --resume to continue or --overwrite"):
                self._run_main(argv, deps)
            self._run_main([*argv, "--overwrite"], deps)

            score_rows = self._read_jsonl(output_dir / "segment_region_scores.jsonl")

        self.assertEqual(len(score_rows), 1)
        self.assertEqual(score_rows[0]["segment_id"], 0)

    def test_score_descriptions_resume_skips_committed_batches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            descriptions = root / "description.txt"
            descriptions.write_text(
                "\n".join(
                    [
                        "00:00 - 00:01  Opening scene.",
                        "00:01 - 00:02  A character looks nervous.",
                        "00:02 - 00:03  The danger continues.",
                    ],
                ),
                encoding="utf-8",
            )
            schema_file = root / "vmpfc_region_schema.json"
            schema_file.write_text(
                json.dumps(_sample_region_schema().to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            output_dir = root / "scored"
            argv = [
                "score-descriptions",
                "--descriptions",
                str(descriptions),
                "--region-schema",
                str(schema_file),
                "--output-dir",
                str(output_dir),
                "--scoring-batch-size",
                "2",
                "--tr-s",
                "1.0",
            ]
            partial_calls: list[int] = []

            def fail_after_first_batch(batch_idx, batch_start, segments, schema, cfg, summaries=None, warnings=None):
                partial_calls.append(batch_idx)
                if batch_idx > 0:
                    raise RuntimeError("stop after first batch")
                return _fake_score_description_segment_batch(
                    batch_idx,
                    batch_start,
                    segments,
                    schema,
                    cfg,
                    summaries,
                    warnings,
                )

            partial_deps = PipelineDependencies(
                build_domain_pool=_fake_domain_pool,
                build_region_schema=_fake_region_schema,
                score_description_segment_batch=fail_after_first_batch,
            )
            with self.assertRaisesRegex(RuntimeError, "stop after first batch"):
                self._run_main(argv, partial_deps)

            partial_rows = self._read_jsonl(output_dir / "segment_region_scores.jsonl")
            progress = json.loads((output_dir / "scoring_progress.json").read_text(encoding="utf-8"))
            self.assertEqual(partial_calls, [0, 1])
            self.assertEqual(len(partial_rows), 2)
            self.assertEqual(progress["completed_segments"], 2)

            with self.assertRaisesRegex(ValueError, "does not match the current inputs"):
                self._run_main([*argv, "--scoring-batch-size", "1", "--resume"], self._deps())

            resume_calls: list[int] = []

            def resume_batch(batch_idx, batch_start, segments, schema, cfg, summaries=None, warnings=None):
                resume_calls.append(batch_idx)
                return _fake_score_description_segment_batch(
                    batch_idx,
                    batch_start,
                    segments,
                    schema,
                    cfg,
                    summaries,
                    warnings,
                )

            resume_deps = PipelineDependencies(
                build_domain_pool=_fake_domain_pool,
                build_region_schema=_fake_region_schema,
                score_description_segment_batch=resume_batch,
            )
            stdout = self._run_main([*argv, "--resume"], resume_deps)
            score_rows = self._read_jsonl(output_dir / "segment_region_scores.jsonl")
            final_progress = json.loads((output_dir / "scoring_progress.json").read_text(encoding="utf-8"))

        self.assertIn("Resuming from 2 committed segment score row", stdout)
        self.assertEqual(resume_calls, [1])
        self.assertEqual(len(score_rows), 3)
        self.assertEqual(score_rows[2]["segment_id"], 2)
        self.assertEqual(final_progress["status"], "complete")

    def test_score_descriptions_resume_finalizes_complete_scores_without_llm(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            descriptions = root / "description.txt"
            descriptions.write_text(
                "\n".join(
                    [
                        "00:00 - 00:01  Opening scene.",
                        "00:01 - 00:02  The threat resolves.",
                    ],
                ),
                encoding="utf-8",
            )
            schema_file = root / "vmpfc_region_schema.json"
            schema_file.write_text(
                json.dumps(_sample_region_schema().to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            output_dir = root / "scored"
            argv = [
                "score-descriptions",
                "--descriptions",
                str(descriptions),
                "--region-schema",
                str(schema_file),
                "--output-dir",
                str(output_dir),
                "--scoring-batch-size",
                "2",
                "--tr-s",
                "1.0",
            ]

            with patch("brain_region_pipeline.scoring.runner.align_scores_to_trs", side_effect=RuntimeError("alignment crashed")):
                with self.assertRaisesRegex(RuntimeError, "alignment crashed"):
                    self._run_main(argv, self._deps())

            def fail_if_called(batch_idx, batch_start, segments, schema, cfg, summaries=None, warnings=None):
                raise AssertionError("LLM scoring should not be called")

            resume_deps = PipelineDependencies(
                build_domain_pool=_fake_domain_pool,
                build_region_schema=_fake_region_schema,
                score_description_segment_batch=fail_if_called,
            )
            stdout = self._run_main([*argv, "--resume"], resume_deps)
            tr_rows = self._read_jsonl(output_dir / "tr_features.jsonl")
            progress = json.loads((output_dir / "scoring_progress.json").read_text(encoding="utf-8"))

        self.assertIn("skipping LLM scoring", stdout)
        self.assertEqual(len(tr_rows), 2)
        self.assertEqual(progress["status"], "complete")

    def test_batch_scorer_uses_story_context_buffer_and_targets(self) -> None:
        from brain_region_pipeline.scoring.region_schema_scorer import score_description_segments

        segments = [
            DescriptionSegment(0.0, 1.0, "Opening landscape."),
            DescriptionSegment(1.0, 2.0, "A character looks nervous."),
            DescriptionSegment(2.0, 3.0, "The danger continues."),
        ]
        summaries = [{"cumulative_summary": "Earlier story context."}]
        payloads = [
            {
                "segment_scores": [
                    {"segment_id": 0, "timestamp": "0", "dimension_scores": _score_dict(1.0)},
                    {"segment_id": 1, "timestamp": "1", "dimension_scores": _score_dict(2.0)},
                ],
            },
            {
                "segment_scores": [
                    {"segment_id": 2, "timestamp": "2", "dimension_scores": _score_dict(3.0)},
                ],
            },
        ]
        cfg = ScoreDescriptionsConfig(
            generation_model="fake-model",
            scoring_batch_size=2,
            local_buffer_size=1,
        )

        with patch("brain_region_pipeline.scoring.region_schema_scorer.generate_structured_json") as generate:
            generate.side_effect = payloads
            rows = score_description_segments(
                segments,
                _sample_region_schema(),
                cfg,
                summaries=summaries,
                warnings=[],
            )

        prompts = [call.kwargs["contents"][0] for call in generate.call_args_list]
        self.assertIn("# Story Context", prompts[0])
        self.assertIn("Beginning of the movie", prompts[0])
        self.assertIn("# Local Buffer", prompts[1])
        self.assertIn("[segment_id=1]", prompts[1])
        self.assertIn("Earlier story context.", prompts[1])
        self.assertIn("# Target Segments", prompts[1])
        self.assertIn("[segment_id=2]", prompts[1])
        self.assertIn(TARGET_SEGMENT_EVIDENCE_INSTRUCTION, prompts[1])
        self.assertIn("only direct scoring evidence", prompts[1])
        self.assertIn("must not raise or lower any Target Segment score", prompts[1])
        self.assertIn(VIEWER_PERSPECTIVE_INSTRUCTION, prompts[1])
        self.assertIn("Use evidence and anchors internally", prompts[1])
        self.assertIn("Do not include rationales", prompts[1])
        self.assertEqual(rows[2].dimension_scores["emotion_admiration"], 3.0)
        self.assertEqual(rows[2].rationale, "")

    def test_single_segment_scorer_includes_viewer_perspective(self) -> None:
        from brain_region_pipeline.scoring.region_schema_scorer import score_description_segments

        segments = [DescriptionSegment(0.0, 1.0, "A character looks relieved.")]
        cfg = ScoreDescriptionsConfig(
            generation_model="fake-model",
            scoring_batch_size=1,
        )

        with patch("brain_region_pipeline.scoring.region_schema_scorer.generate_structured_json") as generate:
            generate.return_value = {"dimension_scores": _score_dict(1.0)}
            score_description_segments(
                segments,
                _sample_region_schema(),
                cfg,
            )

        prompt = generate.call_args.kwargs["contents"][0]
        self.assertIn(VIEWER_PERSPECTIVE_INSTRUCTION, prompt)

    def test_batch_scorer_zero_fills_failed_batch(self) -> None:
        from brain_region_pipeline.scoring.region_schema_scorer import score_description_segments

        segments = [
            DescriptionSegment(0.0, 1.0, "A calm scene."),
            DescriptionSegment(1.0, 2.0, "A tense scene."),
        ]
        warnings: list[dict] = []
        cfg = ScoreDescriptionsConfig(
            generation_model="fake-model",
            scoring_batch_size=40,
            local_buffer_size=10,
        )

        with patch(
            "brain_region_pipeline.scoring.region_schema_scorer.generate_structured_json",
            side_effect=RuntimeError("API unavailable"),
        ):
            rows = score_description_segments(
                segments,
                _sample_region_schema(),
                cfg,
                summaries=None,
                warnings=warnings,
            )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].dimension_scores["emotion_admiration"], 0.0)
        self.assertEqual(warnings[0]["reason"], "batch_generation_failed_zero_filled")
        self.assertEqual(warnings[0]["zero_filled_segments"], 2)

    def test_gt_csvs_average_subjects_before_segment_resampling(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "坠落_焦虑_A.csv").write_text(
                "\n".join(
                    [
                        "视频时间(s),情绪值",
                        "0.00,0",
                        "1.00,2",
                        "2.00,4",
                        "3.00,6",
                    ],
                ),
                encoding="utf-8",
            )
            (root / "坠落_焦虑_B.csv").write_text(
                "\n".join(
                    [
                        "视频时间(s),情绪值",
                        "0.00,10",
                        "1.00,14",
                        "2.00,18",
                        "3.00,22",
                    ],
                ),
                encoding="utf-8",
            )
            gt_by_emotion, metadata = load_averaged_gt_csvs(root)
            rows = average_gt_to_segments(
                [
                    DescriptionSegment(0.0, 2.0, "First segment."),
                    DescriptionSegment(2.0, 4.0, "Second segment."),
                ],
                gt_by_emotion,
            )

        self.assertEqual(metadata["subject_counts"]["agitation"], 2)
        self.assertEqual(rows[0]["gt_emotions"]["agitation"], 6.5)
        self.assertEqual(rows[1]["gt_emotions"]["agitation"], 12.5)
        self.assertEqual(rows[0]["point_counts"]["agitation"], 2)

    def test_score_descriptions_writes_segment_gt_means_when_gt_dir_is_given(self) -> None:
        deps = self._deps()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            descriptions = root / "description.txt"
            descriptions.write_text(
                "\n".join(
                    [
                        "00:00 - 00:02  Ross holds a phone in the kitchen.",
                        "",
                        "00:02 - 00:04  Ross says he will get the pizza woman's phone number.",
                    ],
                ),
                encoding="utf-8",
            )
            gt_dir = root / "gt"
            gt_dir.mkdir()
            (gt_dir / "坠落_焦虑_A.csv").write_text(
                "\n".join(["视频时间(s),情绪值", "0.00,0", "1.00,2", "2.00,4", "3.00,6"]),
                encoding="utf-8",
            )
            (gt_dir / "坠落_焦虑_B.csv").write_text(
                "\n".join(["视频时间(s),情绪值", "0.00,10", "1.00,14", "2.00,18", "3.00,22"]),
                encoding="utf-8",
            )
            schema_file = root / "vmpfc_region_schema.json"
            schema_file.write_text(
                json.dumps(_sample_region_schema().to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            output_dir = root / "scored"

            self._run_main(
                [
                    "score-descriptions",
                    "--descriptions",
                    str(descriptions),
                    "--region-schema",
                    str(schema_file),
                    "--output-dir",
                    str(output_dir),
                    "--gt-dir",
                    str(gt_dir),
                    "--tr-s",
                    "1.0",
                ],
                deps,
            )
            gt_rows = self._read_jsonl(output_dir / "segment_gt_means.jsonl")
            metadata = json.loads((output_dir / "scoring_metadata.json").read_text(encoding="utf-8"))

        self.assertEqual(gt_rows[0]["gt_emotions"]["agitation"], 6.5)
        self.assertEqual(metadata["gt"]["subject_counts"]["agitation"], 2)

    def _deps(self) -> PipelineDependencies:
        return PipelineDependencies(
            build_domain_pool=_fake_domain_pool,
            build_region_schema=_fake_region_schema,
            score_description_segment_batch=_fake_score_description_segment_batch,
        )

    def _run_main(self, argv: list[str], deps: PipelineDependencies) -> str:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            main(argv, deps=deps)
        return stdout.getvalue()

    def _write_atlas(self, root: Path) -> Path:
        atlas = root / "brainnetome.csv"
        atlas.write_text(
            "\n".join(
                [
                    "subregion_func_network_Yeo_updated",
                    "Label,subregion_name,region,Yeo_7network,Yeo_17network,,,,,,,",
                    "1,A8m,SFG_L_7_1,6,17,,,,,,Yeo  7 Network,",
                    "2,A8m,SFG_R_7_1,4,8,,,,,,ID,Network name",
                ],
            ),
            encoding="utf-8",
        )
        return atlas

    def _read_jsonl(self, path: Path) -> list[dict]:
        with path.open("r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]


if __name__ == "__main__":
    unittest.main()
