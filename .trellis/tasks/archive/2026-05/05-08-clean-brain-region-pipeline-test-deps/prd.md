# 清理 brain_region_pipeline 的 test_pipeline 残留依赖

## Goal

清理当前 `brain_region_pipeline` 中尚未真正完成的 encoding 外壳，去掉它对 `test_pipeline` 的运行时依赖，让当前主包只保留已经收敛的 brain-region prompt scoring 主线。encoding 相关能力后续重新设计时再以独立、清晰的模块边界加入。

## What I Already Know

- 用户明确要求先清理当前目录，尤其是 `brain_region_pipeline` 里残留的 `test_pipeline` 依赖。
- 用户判断这些依赖主要属于 encoding 部分，而 encoding 还没做完，因此暂时不需要保留，后续再做。
- 当前源码中的活跃 `test_pipeline` 引用集中在：
  - `brain_region_pipeline/runner.py`
  - `brain_region_pipeline/encoding_eval.py`
  - `tests/test_brain_region_runner.py`
  - `README.md`
  - `docs/brain_region_pipeline_vmpfc_review.md`
- 当前 CLI 仍暴露 `encode` 子命令。
- 当前 `PipelineDependencies` 同时承担 scoring 依赖和 encoding 依赖，导致非 encoding 测试也需要注入 `load_bold`、`fit_ridge_encoding`、`save_encoding_results` 这些暂不需要的字段。
- 当前 `pyproject.toml` 仍保留 `encoding` optional extra，包括 `numpy`、`scikit-learn`、`h5py`。
- 目录里存在 `brain_region_pipeline/__pycache__`、`test_pipeline/__pycache__`、`tests/__pycache__` 这类本地缓存；其中 `brain_region_pipeline/__pycache__` 还包含旧模块名缓存。

## Requirements

- 移除 `brain_region_pipeline` 到 `test_pipeline` 的直接源码依赖。
- 暂时移除或隐藏未完成的 `encode` CLI 面向用户入口，避免用户误认为 encoding 已可维护。
- 保留当前主线：
  - `make-module-prompt`
  - `score-descriptions`
  - dense description 解析
  - module scoring
  - TR feature alignment
  - demo 输出契约
- 简化 `PipelineDependencies`，只保留 prompt generation 和 description scoring 主线所需依赖。
- 移除对应 encoding smoke tests，保留主线 smoke tests。
- 同步更新 README 和审查文档，避免继续宣传当前未完成 encoding。
- 清理本地 `__pycache__` 残留。

## Proposed Scope

### Keep

- `brain_region_pipeline/__main__.py`
- `brain_region_pipeline/cli.py`
- `brain_region_pipeline/runner.py`
- `brain_region_pipeline/config.py`
- `brain_region_pipeline/models.py`
- `brain_region_pipeline/atlas.py`
- `brain_region_pipeline/module_prompt.py`
- `brain_region_pipeline/description_io.py`
- `brain_region_pipeline/module_scorer.py`
- `brain_region_pipeline/score_aligner.py`
- `brain_region_pipeline/tr_output.py`
- `brain_region_pipeline/genai.py`
- `brain_region_pipeline/io_utils.py`

### Remove Or Defer

- `brain_region_pipeline/encoding_eval.py`
- `EncodeConfig`
- `encode` CLI parser and dispatch
- encoding-specific fields on `PipelineDependencies`
- encoding tests in `tests/test_brain_region_runner.py`
- README / docs sections that describe current `encode` as retained functionality
- optional `encoding` extra in `pyproject.toml`, unless user wants to keep dependency metadata for future work
- local `__pycache__` directories

## Open Questions

- 默认方案只移除 `brain_region_pipeline` 对 `test_pipeline` 的依赖，不删除顶层 `test_pipeline/` 目录本身。是否需要把顶层 `test_pipeline/` 也纳入本次删除范围？

## Acceptance Criteria

- [ ] `rg "test_pipeline" brain_region_pipeline tests README.md docs pyproject.toml` 不再显示与当前主线相关的活跃依赖或文档宣传。
- [ ] `uv run python -m brain_region_pipeline` help 中不再显示 `encode`。
- [ ] `uv run python -m brain_region_pipeline encode --help` 不再作为有效命令。
- [ ] `uv run python -m unittest discover -s tests -p 'test_*.py'` 通过。
- [ ] `uv run python -m compileall brain_region_pipeline tests` 通过。
- [ ] 已清理本地 `__pycache__` 缓存。

## Risks And Notes

- 如果直接删除整个 `test_pipeline/`，会影响历史测试流程和过往 review 资产；建议默认先只做解耦，不动顶层目录。
- 移除 `encode` 会让 README 中的 downstream encoding 示例失效，因此文档必须同步改成“暂未实现 / 后续再做”。
- 如果 `PipelineDependencies` 字段被缩减，所有测试中的 fake deps 都需要一起更新，否则测试会因为构造参数不匹配失败。
- `pyproject.toml` 的 `encoding` extra 是否移除取决于是否希望保留未来依赖占位。若目标是“当前目录干净”，建议移除；后续实现 encoding 时再重新加入。

## Technical Notes

- 只读检查命令：
  - `rg -n "test_pipeline|encoding|EncodeConfig|load_bold|fit_ridge_encoding|save_encoding_results" .`
  - `find brain_region_pipeline -maxdepth 3 -type f -print`
  - `find . -maxdepth 3 -type d -name '__pycache__' -print`
- 相关项目规范：
  - `.trellis/spec/guides/index.md`
  - `.trellis/spec/backend/index.md`
