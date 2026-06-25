"""Rolling narrative-summary generation for dense description files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from ..core.config import SummaryDescriptionsConfig
from ..core.genai import generate_structured_json
from ..core.io_utils import write_json
from .description_io import load_description_segments
from .models import DescriptionSegment

SUMMARY_SYSTEM_INSTRUCTION = """\
# Role
You are an expert film analyst tasked with creating concise narrative summaries.

# Task
You will receive:
1. Previous Summary: A cumulative summary of everything that happened before
   this segment batch. It may be empty for the first batch.
2. Current Descriptions: Timestamped scene descriptions for the current batch.

Your job is to create a batch summary that captures the key events, character
developments, and emotional tone of the current batch.

# Output Format
Return a valid JSON object with exactly these fields:
{
  "batch_summary": "A 50-100 word summary of THIS batch only, capturing key events, character actions, and emotional tone",
  "cumulative_summary": "An updated 100-200 word summary combining the previous summary with the new batch summary, maintaining narrative continuity"
}

# Guidelines
- Focus on narrative-critical events: plot developments, character revelations,
  emotional turning points.
- Preserve character names and their relationships.
- Note emotional atmosphere: tension, humor, sadness, etc.
- Keep summaries concise but informative.
- The cumulative summary should flow naturally as a coherent narrative.
- Do not use information from after the current batch.
- Output JSON only, with no Markdown or explanatory text.
"""


def _log(message: str) -> None:
    print(f"[brain_region_pipeline] {message}", flush=True)


@dataclass(frozen=True)
class SummaryDescriptionsInput:
    """Typed input for the rolling-summary stage runner."""

    descriptions: Path
    output_file: Path


def _format_hms(seconds: float) -> str:
    """Format a timestamp in seconds as HH:MM:SS."""

    total_seconds = max(0, int(round(seconds)))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _timestamp_range(segments: Sequence[DescriptionSegment]) -> str:
    """Return the Fallen-compatible timestamp range for one batch."""

    if not segments:
        raise ValueError("Cannot format timestamp range for an empty batch.")
    return f"{_format_hms(segments[0].start_s)} - {_format_hms(segments[-1].end_s)}"


def _render_description_line(segment: DescriptionSegment) -> str:
    """Render one timestamped description line for the summary prompt."""

    return (
        f"{_format_hms(segment.start_s)} - {_format_hms(segment.end_s)}  "
        f"{segment.description}"
    )


def _summary_response_schema() -> dict[str, Any]:
    """Build the structured response schema for one summary batch."""

    return {
        "type": "object",
        "required": ["batch_summary", "cumulative_summary"],
        "additionalProperties": False,
        "properties": {
            "batch_summary": {"type": "string"},
            "cumulative_summary": {"type": "string"},
        },
    }


def _summary_prompt(
    *,
    previous_summary: str,
    batch_segments: Sequence[DescriptionSegment],
) -> str:
    """Build the user prompt for one rolling summary batch."""

    lines = [
        "# Previous Summary",
        '"""',
        previous_summary or "(Beginning of the movie - no prior context)",
        '"""',
        "",
        "# Current Descriptions",
        '"""',
    ]
    lines.extend(_render_description_line(segment) for segment in batch_segments)
    lines.extend(
        [
            '"""',
            "",
            "# Instruction",
            "Create the batch_summary and updated cumulative_summary for the "
            "Current Descriptions only, using Previous Summary only as prior "
            "narrative context.",
        ],
    )
    return "\n".join(lines)


def _nonempty_summary_field(payload: dict[str, Any], field: str, batch_idx: int) -> str:
    """Read and validate one required summary text field."""

    value = str(payload.get(field, "")).strip()
    if not value:
        raise ValueError(f"Summary batch {batch_idx}: field {field!r} is empty.")
    return value


def _generate_summary_payload(
    *,
    batch_idx: int,
    previous_summary: str,
    batch_segments: Sequence[DescriptionSegment],
    cfg: SummaryDescriptionsConfig,
) -> dict[str, str]:
    """Generate and validate one summary payload."""

    try:
        payload = generate_structured_json(
            model=cfg.generation_model,
            system_instruction=SUMMARY_SYSTEM_INSTRUCTION,
            contents=[
                _summary_prompt(
                    previous_summary=previous_summary,
                    batch_segments=batch_segments,
                ),
            ],
            response_schema=_summary_response_schema(),
            cfg=cfg,
        )
    except Exception as exc:
        raise RuntimeError(
            "Summary generation failed for batch "
            f"{batch_idx} with {len(batch_segments)} segment(s).",
        ) from exc
    return {
        "batch_summary": _nonempty_summary_field(payload, "batch_summary", batch_idx),
        "cumulative_summary": _nonempty_summary_field(
            payload,
            "cumulative_summary",
            batch_idx,
        ),
    }


def summarize_description_segments(
    segments: Sequence[DescriptionSegment],
    cfg: SummaryDescriptionsConfig,
) -> list[dict[str, Any]]:
    """Generate Fallen-compatible rolling summary rows for description segments."""

    if not segments:
        raise ValueError("Cannot summarize descriptions because no segments were parsed.")
    rows: list[dict[str, Any]] = []
    previous_summary = ""
    batch_size = cfg.summary_batch_size
    if batch_size < 1:
        raise ValueError("summary_batch_size must be at least 1.")
    for batch_idx, batch_start in enumerate(range(0, len(segments), batch_size)):
        batch_end = min(batch_start + batch_size, len(segments))
        batch_segments = list(segments[batch_start:batch_end])
        payload = _generate_summary_payload(
            batch_idx=batch_idx,
            previous_summary=previous_summary,
            batch_segments=batch_segments,
            cfg=cfg,
        )
        rows.append(
            {
                "batch_idx": batch_idx,
                "segment_start": batch_start,
                "segment_end": batch_end - 1,
                "timestamp_range": _timestamp_range(batch_segments),
                "batch_summary": payload["batch_summary"],
                "cumulative_summary": payload["cumulative_summary"],
            },
        )
        previous_summary = payload["cumulative_summary"]
    return rows


def _write_summary_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write the Fallen-compatible summary JSON array."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, ensure_ascii=False, indent=2)


def _metadata_path(summary_path: Path) -> Path:
    """Return the metadata sidecar path for a summary output file."""

    return summary_path.with_name("summary_metadata.json")


def summarize_descriptions_from_file(
    inputs: SummaryDescriptionsInput,
    cfg: SummaryDescriptionsConfig,
) -> None:
    """Run stage: dense descriptions -> rolling narrative summary JSON."""

    output_file = inputs.output_file
    _log("Step 1/3: Load dense descriptions")
    segments = load_description_segments(inputs.descriptions)
    if not segments:
        raise ValueError("Cannot summarize descriptions because no segments were parsed.")
    _log(f"  Loaded {len(segments)} description segment(s) from {inputs.descriptions}")

    _log("Step 2/3: Generate rolling summaries")
    rows = summarize_description_segments(segments, cfg)
    _log(f"  Generated {len(rows)} summary batch row(s)")

    _log("Step 3/3: Write summary outputs")
    _write_summary_rows(output_file, rows)
    metadata_file = _metadata_path(output_file)
    write_json(
        metadata_file,
        {
            "command": "summarize-descriptions",
            "descriptions": str(inputs.descriptions),
            "summary_file": str(output_file),
            "metadata_file": str(metadata_file),
            "provider": cfg.generation_provider,
            "model": cfg.generation_model,
            "summary_batch_size": cfg.summary_batch_size,
            "n_segments": len(segments),
            "n_batches": len(rows),
            "generated_at": datetime.now(UTC).isoformat(),
            "prompt_contract": {
                "batch_summary_words": "50-100",
                "cumulative_summary_words": "100-200",
                "summary_schema": "fallen_notebook_batch_summary_array",
            },
        },
    )
    _log(f"  Wrote summary JSON to {output_file}")
    _log(f"  Wrote summary metadata to {metadata_file}")
    _log("Description-summary stage complete.")
