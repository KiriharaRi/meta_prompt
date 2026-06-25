# Design: Friends round3 next10 scoring and encoding

## Architecture and Boundaries

This task uses the existing Friends pilot orchestration and does not change
pipeline source code. The work is an experiment configuration and run-control
task:

- Config boundary: create a new round3 config from the round2 config.
- Scoring boundary: use `scripts/run_friends_14roi_concurrent_pilot.py` with
  `--stage scoring` and `--scoring-workers 6`.
- Encoding boundary: use the existing manifest and encoding stages after
  scoring validation passes.
- Output boundary: new scoring artifacts are written under the existing full
  run output root. Round3 encoding will refresh the configured encoding output
  unless a baseline snapshot is made first.

## Episode Selection Contract

The selected episodes are the next conservative train additions after
`s02e15a`, excluding validation-adjacent `s02e01b` through `s02e05b`.

Each selected episode must satisfy:

1. `friends/description/downloaded_refine_descriptions/mv_friends_<episode>/descriptions/refined_description.md`
   exists and parses into timestamped segments.
2. `friends/BN/sub-01/BN_246.h5` contains exactly one dataset ending in
   `task-<episode>`.
3. `ceil(max_description_end_s / 1.49) >= h5_trs - 5`, matching the default
   encoding fMRI end trim.
4. `friends/full_runs/friends_full_scoring_start_14roi_gemini35_20260612/summaries/<episode>/summary.json`
   exists.
5. Existing new-round scoring outputs are absent or resumable. Partial outputs
   require resume-compatible metadata, otherwise the job should be inspected
   before continuing.

## Data Flow

1. Round3 config adds 10 `train` rows to the round2 episode list.
2. Dry-run validates config paths, ROI definitions, atlas labels, description
   files, and H5 dataset names.
3. Scoring stage creates 140 ROI/episode outputs:
   `rois/<ROI>/scores/<episode>/`.
4. Per scoring output, the scorer writes segment scores, TR-aligned features,
   readable TR descriptions, progress, metadata, and warnings if any.
5. Manifest stage writes `encoding/roi_encoding_manifest.jsonl` linking every
   sample to all 14 ROI feature files.
6. Encoding stage fits Ridge encoding with the configured lags and alphas and
   writes group and subject-level result artifacts.

## Monitoring Design

Early scoring is the highest-risk phase because it depends on live provider
calls. Polling should check:

- runner stdout for committed batch lines, exceptions, or stalled jobs;
- count of completed `scoring_metadata.json` files for the 140 new jobs;
- any `scoring_warnings.jsonl` files and zero-filled batch reasons;
- representative `scoring_progress.json` files while jobs are active.

Recommended cadence:

- first 15 to 30 minutes: every 60 to 90 seconds;
- after multiple polls show steady completions and no warning pattern: every
  5 to 10 minutes;
- on any exception, zero-filled batch, or stalled progress: return to frequent
  polling and diagnose before encoding.

## Compatibility and Rollback

- The round2 config and previously committed scoring outputs remain unchanged.
- New scoring outputs are resumable by default because the runner uses scoring
  resume unless `--overwrite-scoring` is provided.
- The main rollback point is before encoding refresh. If the current 55-train
  encoding directory should remain inspectable, snapshot it before running the
  round3 encoding stage.
- If scoring fails partially, do not run encoding. Use the existing retry failed
  batch path or resume scoring after inspecting failure metadata.

## Trade-offs

- Using the existing full run output root keeps ROI schemas, summaries, and
  previous scoring outputs colocated, which matches current workflow.
- Refreshing `encoding/` in place keeps downstream paths simple but can obscure
  the confirmed 55-train result. Snapshotting the 55-train encoding directory
  is safer and recommended.
- Concurrency 6 should reduce wall time but raises live provider pressure. The
  monitoring cadence is part of the risk control.
