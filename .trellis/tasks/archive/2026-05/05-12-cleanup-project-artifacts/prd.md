# 清理项目目录和 test_pipeline 残留

## Goal

清理当前项目目录中已经脱离主线的旧实验包、缓存和本地生成物，让仓库边界重新回到可维护的 `brain_region_pipeline` 主线，同时把删除依据和保留边界按 Trellis 任务记录下来。

## What I already know

* 当前主包维护边界是 `brain_region_pipeline` 的 brain-region prompt scoring workflow。
* 代码规范明确禁止让 `brain_region_pipeline` 重新依赖 `test_pipeline`，未来 encoding 应通过新的清晰边界重新设计。
* 只读检查显示 `brain_region_pipeline`、`tests/`、`README.md`、`docs/`、`pyproject.toml` 已经没有活跃 `test_pipeline` 引用。
* `test_pipeline/` 仍是 tracked 历史实验包，当前不再被主线依赖。
* `test_data/` 体积约 2.3G，包含旧 Friends 视频、BOLD/H5、NIfTI、`.npy` 和 Schaefer atlas label；README 示例仍引用 atlas label 路径。
* 当前工作树已有用户/前序任务产生的未提交 demo 输出和 `pyproject.toml`/`uv.lock` 改动，需要避免误删或误提交。

## Requirements

* 删除已经不被主线依赖的顶层 `test_pipeline/`。
* 清理 Python/工具缓存和 macOS 本地文件：
  * `brain_region_pipeline/__pycache__/`
  * `tests/__pycache__/`
  * `.ruff_cache/`
  * `.mypy_cache/`
  * `.DS_Store`
* 不删除 `test_data/`，先把它作为后续单独整理项保留。
* 更新 `.gitignore`，防止缓存、输出目录和本地分析产物反复污染工作树。
* 保留当前已经 tracked 的 Fallen demo 结果，不在本次清理中删除实验结果。
* 运行主线验证，确认删除 `test_pipeline/` 后主包和测试仍然可用。

## Acceptance Criteria

* [x] `test_pipeline/` 不再存在于工作树。
* [x] `rg "test_pipeline" brain_region_pipeline tests README.md docs pyproject.toml` 无输出。
* [x] Python/工具缓存和 `.DS_Store` 已清理。
* [x] `.gitignore` 覆盖本地缓存、`outputs/` 和未跟踪 demo rerun 目录。
* [x] `uv run python -m unittest discover -s tests -p 'test_*.py'` 通过。
* [x] `uv run python -m compileall brain_region_pipeline tests` 通过。
* [x] `uv run python -m brain_region_pipeline` 仍显示维护中的 CLI 命令，且不暴露 `encode`。
* [x] `test_data/` 的保留原因已记录清楚，后续如需瘦身另开任务处理。

## Out of Scope

* 不重构 `brain_region_pipeline` 源码。
* 不删除 `test_data/` 大文件。
* 不删除已经 tracked 的 Fallen demo/scoring 结果。
* 不修改当前 vmPFC scoring pilot 的实验逻辑和依赖版本。
* 不把本次清理和当前未提交实验输出混在同一个提交里。

## Risks And Notes

* 删除 `test_pipeline/` 会移除旧 movie-fMRI/Friends 实验入口；如果未来要恢复，应从 Git 历史取回，而不是重新接回当前主包。
* `test_data/` 仍然占用较大空间，但里面的 atlas label 仍被 README 示例引用；直接删除整个目录会破坏用户当前使用习惯。
* `.gitignore` 新增规则应避免影响已 tracked 的历史产物；Git 对已 tracked 文件不会因 ignore 规则自动移除。
* 当前工作树已有未提交输出，本任务只整理目录边界，不替用户决定实验结果是否保留。

## Technical Notes

* 只读确认命令：
  * `rg -n "test_pipeline" brain_region_pipeline tests README.md docs pyproject.toml`
  * `rg -n "(^|\\s)(from|import)\\s+test_pipeline|test_pipeline\\." . --glob '!test_pipeline/**'`
  * `du -sh test_pipeline test_data fallen/demo outputs`
* 相关规范：
  * `.trellis/spec/backend/directory-structure.md`
  * `.trellis/spec/backend/quality-guidelines.md`

## Completion Notes

* Deleted tracked legacy package `test_pipeline/` after confirming there were no active references from `brain_region_pipeline`, tests, README, docs, or dependency metadata.
* Removed generated local files and caches: `brain_region_pipeline/__pycache__/`, `tests/__pycache__/`, `.ruff_cache/`, `.mypy_cache/`, and all discovered `.DS_Store` files.
* Updated `.gitignore` to explicitly ignore `.mypy_cache/`, `.ruff_cache/`, `outputs/`, and the untracked Fallen rerun/scoring artifacts from the current pilot work.
* Kept `test_data/` in place because it is large but still contains the README-referenced Schaefer atlas label file; removing or relocating dataset assets should be handled in a separate data-layout task.
* Spec update review: no `.trellis/spec/` change was needed because the existing backend directory and quality specs already state the maintained package boundary, the `test_pipeline` prohibition, and cache-cleanup expectations.
* Validation passed:
  * `uv run python -m unittest discover -s tests -p 'test_*.py'`
  * `uv run python -m compileall brain_region_pipeline tests`
  * `uv run python -m brain_region_pipeline`
