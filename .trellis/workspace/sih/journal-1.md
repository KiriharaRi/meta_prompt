# Journal - sih (Part 1)

> AI development session journal
> Started: 2026-05-08

---



## Session 1: Clean brain-region pipeline dependencies

**Date**: 2026-05-09
**Task**: Clean brain-region pipeline dependencies
**Branch**: `main`

### Summary

Removed unfinished brain_region_pipeline encoding/test_pipeline coupling, recorded package boundary specs, refined module prompt generation, and cleaned generated artifacts from Git tracking.

### Main Changes

- Added notebook-style Story Context / Local Buffer / Target Segments batch scoring to `score-descriptions`.
- Preserved multi-dimensional vmPFC module scoring while batching 40 target segments with 10 prior buffer segments by default.
- Added notebook-style GT CSV averaging to segment means and committed Fallen demo inputs/artifacts.
- Updated README, review docs, Trellis specs, and regression tests.

### Git Commits

| Hash | Message |
|------|---------|
| `c24a93c` | (see git log) |
| `ab46ce2` | (see git log) |
| `524b967` | (see git log) |
| `df2b1ea` | (see git log) |

### Testing

- [OK] `uv run python -m unittest discover -s tests -p 'test_*.py'`
- [OK] `uv run python -m compileall brain_region_pipeline tests`
- [OK] `uv run python -m brain_region_pipeline score-descriptions --help`

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 2: Refine vmPFC annotation dimensions

**Date**: 2026-05-09
**Task**: Refine vmPFC annotation dimensions
**Branch**: `main`

### Summary

Implemented and validated a vmPFC domain-pool workflow for granular annotation dimensions, including confirmed domain-pool gating, 20-dimension module prompts, scorer prompt rendering, tests, docs, spec updates, live Gemini run verification, and committed the simplified AGENTS.md instructions.

### Main Changes

- Removed the tracked legacy `test_pipeline/` package after confirming the maintained `brain_region_pipeline` workflow no longer references it.
- Added cleanup ignore rules for local caches, `outputs/`, and untracked Fallen demo rerun artifacts.
- Recorded and archived the Trellis cleanup task under `.trellis/tasks/archive/2026-05/`.
- Verified `pyproject.toml` and `uv.lock` are synchronized for `matplotlib>=3.10.9`, then committed the dependency update.

### Git Commits

| Hash | Message |
|------|---------|
| `8dc3fbf` | (see git log) |
| `5464db3` | (see git log) |

### Testing

- [OK] `uv run python -m unittest discover -s tests -p 'test_*.py'`
- [OK] `uv run python -m compileall brain_region_pipeline tests`
- [OK] `uv run python -m brain_region_pipeline`
- [OK] `uv lock --check`
- [OK] `uv tree --locked --package description-fmri`

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 3: Fallen context batch scoring

**Date**: 2026-05-10
**Task**: Fallen context batch scoring
**Branch**: `main`

### Summary

Implemented notebook-style context batch scoring for score-descriptions, added Fallen demo data artifacts, GT segment averaging, docs, tests, and specs.

### Main Changes

- Scored the remaining 1,278 Fallen description segments locally with the same
  vmPFC region schema configuration used for the first 800 segments.
- Produced local full-run artifacts for 2,078 segment scores, GT means, TR
  features, and no-lag / lagged correlation summaries.
- Recorded the resume-scoring rule that partial runs must preserve original
  segment indexes and batch boundaries.
- Added a gitignore rule for the generated
  `fallen/demo/vmpfc_gemini3_flash_800_20260514/` output directory and stopped
  tracking generated demo outputs while keeping the files available locally.

### Git Commits

| Hash | Message |
|------|---------|
| `52dc556` | (see git log) |
| `c574bdf` | (see git log) |

### Testing

- [OK] Verified remaining score row count: 1,278.
- [OK] Verified full score and GT row counts: 2,078 each.
- [OK] Verified full TR feature row count: 4,074.
- [OK] Verified merge boundary: row 799 ends at 2289.0s and row 800 starts at
  2289.0s.
- [OK] Verified remaining scoring warnings: 0.

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 4: Cleanup project artifacts

**Date**: 2026-05-12
**Task**: Cleanup project artifacts
**Branch**: `main`

### Summary

Removed the legacy test_pipeline package, recorded the cleanup task, verified uv dependency sync for matplotlib, and committed the dependency lockfile update.

### Main Changes

- Ran full Fallen VMPFC scoring with the Friends VMPFC schema and generated local-only DeepSeek baseline outputs.
- Validated `mimo-v2.5-pro` on one batch, then ran all 52 Fallen scoring batches concurrently with zero warnings and zero zero-filled segments.
- Recomputed sigma=20 correlations, lag sweep, and broader sigma/lag grid analyses in the local Mimo output directory.
- Switched the maintained PackyAPI default model and Friends pilot config from `deepseek-v4-pro` to `mimo-v2.5-pro`.
- Kept generated scoring artifacts out of git per user request by excluding the two local output directories in `.git/info/exclude`.

### Git Commits

| Hash | Message |
|------|---------|
| `99f9e0d` | (see git log) |
| `ec8faf0` | (see git log) |
| `d9b6c77` | (see git log) |

### Testing

- [OK] `uv run python -m unittest discover -s tests -p 'test_*.py'`
- [OK] `uv run python -m compileall brain_region_pipeline tests`
- [OK] `uv run python -m brain_region_pipeline`
- [OK] `uv run python -m brain_region_pipeline score-descriptions --help`

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 5: Refine domain pool granularity wording

**Date**: 2026-05-14
**Task**: Refine domain pool granularity wording
**Branch**: `main`

### Summary

Updated domain_pool prompts from broad-domain wording to coarse-grained domain wording, synced backend Trellis specs for the same convention, and archived the active vmpfc scoring task.

### Main Changes

- Added `scripts/run_friends_14roi_concurrent_pilot.py` as a config-driven concurrent full-run/retry runner.
- Added `docs/pipeline_usage_commands.md` covering Fallen and Friends staged, full-run, concurrent, and non-concurrent commands.
- Added dry-run coverage for config-driven episode selection and worker controls.
- Updated backend directory spec with the concurrent pilot script contract.

### Git Commits

| Hash | Message |
|------|---------|
| `a3934f3` | (see git log) |
| `15ad907` | (see git log) |

### Testing

- [OK] `uv run python scripts/run_friends_14roi_concurrent_pilot.py --help`
- [OK] `uv run python scripts/run_friends_14roi_concurrent_pilot.py --dry-run`
- [OK] `uv run python -m unittest tests.test_friends_14roi_concurrent_script`
- [OK] `uv run python -m unittest discover -s tests -p 'test_*.py'`
- [OK] `uv run python -m compileall brain_region_pipeline tests scripts`

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 6: Region schema contract migration

**Date**: 2026-05-14
**Task**: Region schema contract migration
**Branch**: `main`

### Summary

Migrated the brain-region pipeline from module prompts to domain_pool_v2 -> region_schema_v1 -> score-descriptions, including required emotion_experience validation, flat dimension_scores output, docs, specs, and tests.

### Main Changes

- Added encoding-stage raw TR alignment that slices features and fMRI by the
  same trimmed fMRI interval, allowing longer feature files and failing on
  insufficient feature coverage.
- Added pilot `encoding_trim` config defaults and manifest trim field emission
  while keeping scoring unchanged.
- Added regression tests for manifest trim writing, raw TR truncation, short
  feature failure, and `tr_index` continuity.
- Updated backend spec and config docs for the new encoding alignment contract.

### Git Commits

| Hash | Message |
|------|---------|
| `9b2b0ec` | (see git log) |

### Testing

- [OK] `uv run python -m unittest discover -s tests -p 'test_*.py'`
- [OK] `uv run python -m compileall brain_region_pipeline tests scripts`
- [OK] `git diff --check`

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 7: Complete vmPFC remaining segment scoring

**Date**: 2026-05-14
**Task**: Complete vmPFC remaining segment scoring
**Branch**: `main`

### Summary

Completed remaining Fallen vmPFC segment scoring analysis, recorded resumed scoring boundary guidance, and stopped tracking generated demo outputs while keeping them local.

### Main Changes

- Added Friends pass24 sweep configs for S1 scoring batches, plus3/plus4 encoding runs, and train-size sweep configs.
- Tracked 14 newly scored S1 episodes across 14 ROIs under the Friends full run output root.
- Tracked the final 28-episode encoding outputs with `s01e02a` as validation and `s06e01a/s06e01b/s06e03a/s06e03b` as test.
- Cleared the stale Trellis current-task runtime pointer for the missing `06-16-friends-pass24-encoding-sweep` task directory.

### Git Commits

| Hash | Message |
|------|---------|
| `70a4994` | (see git log) |
| `d35a756` | (see git log) |
| `5661599` | (see git log) |

### Testing

- [OK] Verified `s01e15b` scoring completion across 14 ROIs with 477 TR rows and zero warnings.
- [OK] Reran encoding for 23 train / 1 val / 4 test episodes; final `mean_subject_mean_test_pearson` is 0.1851977718935396.
- [OK] Confirmed Trellis current task now resolves to none after stale runtime cleanup.

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 8: H5 Ridge Encoding Stage

**Date**: 2026-05-19
**Task**: H5 Ridge Encoding Stage
**Branch**: `main`

### Summary

Added a manifest-driven H5 fMRI Ridge encoding stage, documented the new encoding contract, ignored the generated vmPFC demo output, and verified tests/compile/help.

### Main Changes

- Added `configs/friends_train_size_sweep_20260617/s01_train_s02_val.json`.
- Ran a 14-ROI encoding experiment with 25 S01 train episodes, 5 S02 validation episodes, and 4 S06 test episodes.
- Preserved ignored encoding outputs under `friends/analysis/train_size_sweep_20260617/s01_train_s02_val/encoding/`.
- Reported overall test Pearson `0.191285`, median test Pearson `0.186196`, selected alpha `10000`, and ROI-level metrics.

### Git Commits

| Hash | Message |
|------|---------|
| `dd21338` | (see git log) |
| `105028b` | (see git log) |

### Testing

- [OK] `uv run python -m brain_region_pipeline run-multi-roi-pilot --config configs/friends_train_size_sweep_20260617/s01_train_s02_val.json --dry-run`
- [OK] `uv run python -m compileall brain_region_pipeline tests`
- [OK] `uv run python -m unittest discover -s tests -p 'test_*.py'` (101 tests)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 9: Multi-ROI pilot encoding workflow

**Date**: 2026-05-26
**Task**: Multi-ROI pilot encoding workflow
**Branch**: `main`

### Summary

Implemented and verified the multi-ROI pilot workflow: per-ROI domain pools and active dimensions, shared summaries, per-ROI scoring, combined multi-ROI encoding, pilot config, tests, README, and Trellis spec updates.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `185f405` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 10: Brainnetome multi-ROI pilot cleanup

**Date**: 2026-05-29
**Task**: Brainnetome multi-ROI pilot cleanup
**Branch**: `main`

### Summary

Completed ROI pilot cleanup by moving the workflow to Brainnetome-only ROI selection, removing Schaefer and primary/control leftovers, preserving the uploaded ROI source table, and cleaning local pilot artifacts.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `20391ef` | (see git log) |
| `59ed4e2` | (see git log) |
| `4abf9c8` | (see git log) |
| `18574d5` | (see git log) |
| `a59c972` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 11: Merge Brainnetome H5

**Date**: 2026-05-30
**Task**: Merge Brainnetome H5
**Branch**: `main`

### Summary

Merged cortical and subcortical Brainnetome H5 inputs into a local BN_246.h5 artifact, updated the Friends multi-ROI pilot config to use the merged H5, removed missing training episodes, and verified the pilot dry-run.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `619e8c8` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 12: Add AIHubMix Xiaomi MiMo provider

**Date**: 2026-05-30
**Task**: Add AIHubMix Xiaomi MiMo provider
**Branch**: `main`

### Summary

Added OpenAI SDK backed AIHubMix provider defaults for Xiaomi MiMo, wired provider/model through CLI and pilot config, updated docs/specs, and validated tests.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `fa0791c` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 13: Switch default AIHubMix model to DeepSeek

**Date**: 2026-05-30
**Task**: Switch default AIHubMix model to DeepSeek
**Branch**: `main`

### Summary

Changed the default AIHubMix generation model to deepseek-v4-pro after validating domain-pool JSON output, updated pilot config, README, tests, and backend provider spec, then verified unittest, compileall, CLI help, and diff checks.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `d46672c` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 14: DeepSeek domain-pool prompt contract

**Date**: 2026-05-31
**Task**: DeepSeek domain-pool prompt contract
**Branch**: `main`

### Summary

Refined domain-pool generation prompts around viewer-centric inference, enforced canonical vmPFC emotion_experience definitions, added regression tests, and stopped the attempted retry run on request.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `8d10aaa` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 15: Migrate LLM provider to PackyAPI

**Date**: 2026-05-31
**Task**: Migrate LLM provider to PackyAPI
**Branch**: `main`

### Summary

Migrated the default OpenAI-compatible LLM provider from AIHubMix to PackyAPI, updated env/config/docs/tests/specs, fixed PackyAPI structured-output compatibility by using json_object, and verified with offline tests plus a live make-domain-pool smoke test.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `578b584` | (see git log) |
| `83c9dfa` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 16: Remove generation retries and timeouts

**Date**: 2026-05-31
**Task**: Remove generation retries and timeouts
**Branch**: `main`

### Summary

Removed project-level LLM retry and timeout controls, disabled PackyAPI OpenAI SDK retries, and updated tests/docs/specs for single-attempt provider calls.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `8f8ebaf` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 17: Fix schema dimension contracts

**Date**: 2026-05-31
**Task**: Fix schema dimension contracts
**Branch**: `main`

### Summary

Removed total dimension limits, enforced domain-to-dimension separation with 3-8 non-emotion dimensions per domain, scoped vmPFC emotion prefix validation, and generated valid Friends ROI schemas.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `ca7fbc4` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 18: Fallen VMPFC scoring and Mimo default

**Date**: 2026-06-01
**Task**: Fallen VMPFC scoring and Mimo default
**Branch**: `main`

### Summary

Ran full Fallen VMPFC scoring and correlation analyses, validated Mimo v2.5 Pro scoring outputs, switched the default PackyAPI generation model from DeepSeek to mimo-v2.5-pro, and left generated scoring artifacts local-only per user request.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `6b0e301` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 19: Consolidate region schema prompt rules

**Date**: 2026-06-01
**Task**: Consolidate region schema prompt rules
**Branch**: `main`

### Summary

Centralized region-schema prompt/schema/validator bounds, added regression tests, and documented LLM prompt contract synchronization.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `60d607e` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 20: Reorganize brain region pipeline

**Date**: 2026-06-02
**Task**: Reorganize brain region pipeline
**Branch**: `main`

### Summary

Restructured brain_region_pipeline into workflow packages and unified single and multi ROI encoding under fit-roi-encoding.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `8edd1fa` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 21: Switch generation default to AIHubMix

**Date**: 2026-06-04
**Task**: Switch generation default to AIHubMix
**Branch**: `main`

### Summary

Switched the brain-region prompt pipeline default generation provider/model to AIHubMix gemini-3.5-flash, added strict json_schema enforcement and schema normalization, updated tests/docs/spec, and verified with unit tests plus a live representative AIHubMix smoke test.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `4df53ec` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 22: Tribe encoding baseline

**Date**: 2026-06-05
**Task**: Tribe encoding baseline
**Branch**: `main`

### Summary

Added one-off Tribe word-feature Ridge encoding baseline script, ran sum and mean aggregation comparisons against the current BN246 ROI-union model-scoring baseline, and verified tests.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `217198f` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 23: Friends 7 ROI Vertex Gemini pilot

**Date**: 2026-06-05
**Task**: Friends 7 ROI Vertex Gemini pilot
**Branch**: `main`

### Summary

Added and ran the Friends 7 ROI Vertex Gemini pilot runner, reused existing summaries, retried failed scoring batches with lower concurrency, and refreshed encoding results.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `23ad589` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 24: Gemini SDK retry before zero fill

**Date**: 2026-06-05
**Task**: Gemini SDK retry before zero fill
**Branch**: `main`

### Summary

Added Google GenAI SDK retry options for direct Gemini clients with three retries after the initial request, kept scoring zero-fill fallback unchanged, updated tests and backend provider spec.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `fde67c2` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 25: Run Friends remaining 7 ROIs

**Date**: 2026-06-06
**Task**: Run Friends remaining 7 ROIs
**Branch**: `main`

### Summary

Ran the remaining Friends ROIs with the 14-ROI Vertex Gemini 3.5 Flash config, retried failed scoring batches, refreshed manifest and encoding, and verified zero residual scoring warnings.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `2345cb5` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 26: Tribe encoding for Vertex ROI target

**Date**: 2026-06-07
**Task**: Tribe encoding for Vertex ROI target
**Branch**: `main`

### Summary

Parameterized the one-off Tribe Ridge encoding baseline to accept a target encoding directory, ran Tribe sum and mean aggregations against the Vertex Gemini ROI selected_parcels target, and verified the results against the model-scoring baseline.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `f25bdbf` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 27: Tribe expanded train s02e05a encoding comparison

**Date**: 2026-06-07
**Task**: Tribe expanded train s02e05a encoding comparison
**Branch**: `main`

### Summary

Added custom train/val/test episode split support for Tribe encoding baseline; ran expanded-train s02e05a held-out encoding comparisons for sum and mean aggregation against the 14-ROI parcel union, and verified with py_compile, unit tests, and default-split smoke run.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `97bfaa2` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 28: Friends 14 ROI s01/s02 Vertex expansion

**Date**: 2026-06-08
**Task**: Friends 14 ROI s01/s02 Vertex expansion
**Branch**: `main`

### Summary

Completed the expanded Friends 14-ROI s01/s02 Vertex Gemini pilot: added the run config and one-off orchestration script, reused validated s01 artifacts, generated/scored s02 episodes, retried failed scoring batches, and produced the expanded encoding result with s02e05a held out.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `80c182f` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 29: Friends 14 ROI concurrent pilot docs

**Date**: 2026-06-08
**Task**: Friends 14 ROI concurrent pilot docs
**Branch**: `main`

### Summary

Added a config-driven Friends 14 ROI concurrent pilot runner, documented Fallen/Friends command workflows, added dry-run coverage, and recorded the concurrent script boundary in backend specs.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `0bd7d33` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 30: AIHubMix schema prompt deduplication

**Date**: 2026-06-14
**Task**: AIHubMix schema prompt deduplication
**Branch**: `main`

### Summary

Removed duplicate rendered JSON schema from AIHubMix prompts while keeping strict response_format enforcement; added regression coverage and synchronized the backend provider spec.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `73ab63b` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 31: AIHubMix Gemini SDK migration

**Date**: 2026-06-14
**Task**: AIHubMix Gemini SDK migration
**Branch**: `main`

### Summary

Switched AIHubMix provider from the OpenAI-compatible path to Google GenAI SDK while keeping provider name and AIHUBMIX_API_KEY, moved the default endpoint to https://aihubmix.com/gemini, added legacy /v1 rejection tests, and synchronized docs plus backend provider spec.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `4914e9d` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 32: Encoding raw TR alignment

**Date**: 2026-06-16
**Task**: Encoding raw TR alignment
**Branch**: `main`

### Summary

Aligned ROI encoding features to fMRI raw TR trim, kept scoring unchanged, added pilot encoding_trim and regression tests.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `abeac4d` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 33: Friends pass24 encoding sweep

**Date**: 2026-06-18
**Task**: Friends pass24 encoding sweep
**Branch**: `main`

### Summary

整理 Friends pass24 scoring/encoding sweep：记录配置、14 个新增 S1 episode 的 14 ROI scoring 输出、28 episode encoding 输出；最终 s06 四集 test mean Pearson 为 0.1851977718935396，并清理 stale Trellis current-task 指针。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `adaaa3e` | (see git log) |
| `08ee061` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 34: Friends scoring and encoding sweep wrap-up

**Date**: 2026-06-22
**Task**: Friends scoring and encoding sweep wrap-up
**Branch**: `main`

### Summary

Completed Friends scoring/encoding sweep outputs, tracked pass sweep configs/progress and plus10 encoding results, and produced the weekly PPT summary for train-size and validation-split effects.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `09e9984` | (see git log) |
| `b6e5385` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 35: Friends S01 train S02 validation encoding

**Date**: 2026-06-22
**Task**: Friends S01 train S02 validation encoding
**Branch**: `main`

### Summary

Ran Friends 14-ROI encoding with S01 episodes as train, S02 episodes as validation, and S06 episodes as test; added the split config and reported fMRI prediction performance.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `e3d30b4` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 36: Friends plus10 scoring and train-size sweep

**Date**: 2026-06-22
**Task**: Friends plus10 scoring and train-size sweep
**Branch**: `main`

### Summary

Added the Friends plus10 scoring/encoding outputs, committed fresh train-size sweep configs, added the no-SEM Friends-vs-Tribe plotting helper, verified tests and artifacts, then archived the task.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `005b5b7` | (see git log) |
| `4e6bc76` | (see git log) |
| `6e7435f` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 37: Friends next10 scoring and encoding prep

**Date**: 2026-06-23
**Task**: Friends next10 scoring and encoding prep
**Branch**: `main`

### Summary

Prepared the Friends next10 scoring/encoding outputs and cleaned backend quality guideline drift before archiving the task.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `dee34c2` | (see git log) |
| `df9d1e7` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 38: Friends round2 scoring and encoding

**Date**: 2026-06-25
**Task**: Friends round2 scoring and encoding
**Branch**: `main`

### Summary

Completed Friends round2 scoring/encoding outputs, documented scoring warning recovery, and tracked agent docs plus comparison plot.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `2f6e30d` | (see git log) |
| `38a8378` | (see git log) |
| `b68bef4` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 39: Deepen Friends pilot artifact graph

**Date**: 2026-06-25
**Task**: Deepen Friends pilot artifact graph
**Branch**: `main`

### Summary

Extracted Friends pilot artifact graph into PilotArtifacts, migrated the serial pilot runner to use it, updated tests, and synced the backend directory spec.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `2c7f50a` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 40: Deepen Friends concurrency module

**Date**: 2026-06-25
**Task**: Deepen Friends concurrency module
**Branch**: `main`

### Summary

Moved reusable Friends concurrent pilot stage jobs into brain_region_pipeline.pilot.concurrent, updated 14ROI and 7ROI scripts to use the maintained module, added regression coverage, and documented the new module responsibility.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `4f34e06` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 41: Remove CLI-shaped summary scoring interface

**Date**: 2026-06-25
**Task**: Remove CLI-shaped summary scoring interface
**Branch**: `main`

### Summary

Replaced summary and scoring runner Namespace-shaped inputs with typed dataclass inputs, updated CLI and Friends pilot callers, removed obsolete Friends scripts, added typed-input regression coverage, and recorded the backend stage-runner interface rule.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `c0cbc1d` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 42: Type schema design runner inputs

**Date**: 2026-06-25
**Task**: Type schema design runner inputs
**Branch**: `main`

### Summary

Moved schema-design stage runners from CLI-shaped args to typed input objects, updated CLI and pilot adapters, added staged/concurrent pilot regression coverage, and recorded the typed-input/config ownership boundary in backend specs.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `10ba4f6` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
