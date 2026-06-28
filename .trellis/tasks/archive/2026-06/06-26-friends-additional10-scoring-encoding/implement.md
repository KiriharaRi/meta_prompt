# Implementation Plan: Friends additional10 scoring and encoding

## Ordered Checklist

1. Confirm working tree status and active Trellis task.
2. Inspect round3 config and existing full-run output layout.
3. Generate a deterministic preflight report for candidate episodes:
   description file, H5 dataset, summary output, feature TRs, H5 TRs, and
   selected/skipped reason.
4. Select exactly 10 valid new train episodes outside the round3 split.
5. Create a new round config from round3 with the 10 selected episodes appended.
6. Validate the config split counts are `75 train / 5 val / 4 test`.
7. Dry-run scoring with concurrency 6.
8. Launch scoring with concurrency 6.
9. Poll early scoring frequently:
   - runner output;
   - count complete scoring metadata among selected episode/ROI jobs;
   - inspect warning and failed-batch metadata.
10. Once stable progress is confirmed, lower polling frequency.
11. Validate all newly required scoring outputs.
12. Retry failed batches if validation finds zero-filled failed batches.
13. Refresh manifest.
14. Validate manifest rows and 14-ROI feature coverage for selected episodes.
15. Run encoding.
16. Report final metrics and compare against round3 baseline
    `0.21207336267220675`.

## Validation Commands

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py --config <new-config> --stage scoring --scoring-workers 6 --dry-run
```

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py --config <new-config> --stage manifest
```

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py --config <new-config> --stage encoding
```

## Review Gates

- Do not launch scoring until the selected 10 episodes have H5/TR evidence.
- Do not run encoding until scoring validation is warning-free for selected
  episodes.
- If provider/network failures recur, retry failed batches before changing
  config or source code.

## Rollback Points

- Candidate rejection: keep only the preflight report for diagnosis.
- Scoring failure: preserve successful outputs and rerun failed batches.
- Encoding overwrite risk: snapshot the previous encoding directory before
  refreshing if the new config points at an existing encoding output.
