# Implement Plan

## Checklist

1. Add `SummaryDescriptionsInput` to `summary_generator.py`.
2. Change `summarize_descriptions_from_file` to accept
   `SummaryDescriptionsInput`.
3. Add `ScoreDescriptionsInput` to `scoring/runner.py`.
4. Change `score_descriptions_from_file` and helper calls to use
   `ScoreDescriptionsInput`.
5. Add CLI adapter helpers in `cli.py` for summary and scoring commands.
6. Update `pilot/concurrent.py` summary/scoring calls to construct typed inputs.
7. Update `pilot/runner.py` summary/scoring calls to construct typed inputs.
8. Confirm the deleted Friends scripts are no longer caller targets, then update
   any remaining direct summary/scoring script callers.
9. Update tests for typed input behavior and path assertions.
10. Add the narrow backend spec guideline.
11. Run validation commands.
12. Run temporary fake-data smoke and confirm the working tree stays clean.

## Validation Commands

```bash
uv run python -m unittest tests.test_friends_14roi_concurrent_script
uv run python -m unittest discover -s tests -p 'test_*.py'
uv run python -m compileall brain_region_pipeline tests scripts
git diff --check
```

Temporary smoke: generate fake config/artifacts in `TemporaryDirectory`, patch
external LLM/encoding edges, and execute
`scripts/run_friends_14roi_concurrent_pilot.py --stage all`.

## Rollback Points

- If scoring checkpoint signatures drift, rollback `ScoreDescriptionsInput`
  helper migration and re-check checkpoint serialization.
- If old scripts break from direct runner imports, search and migrate caller by
  caller rather than adding `Namespace` compatibility back to the runner.

## Follow-Up Candidates

- Migrate domain-pool and region-schema runner interfaces.
- Migrate encoding runner interface.
- Consider deeper scoring domain input objects only after the current
  field-equivalent interface is stable.
