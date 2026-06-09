# 泛化 Friends 14 ROI 并发脚本并补充使用文档

## Goal

将当前 Friends 14 ROI 并发运行能力从固定 s01+s02 扩展脚本泛化为可由用户通过配置指定任意剧集集合的运行入口，并补充中文使用文档，覆盖 Fallen 与 Friends 两条流程的分阶段命令、一键命令、并发/非并发命令，以及相关输出检查方式。

## What I Already Know

* 项目使用 `uv` 管理 Python 运行环境，命令示例应统一使用 `uv run ...`。
* 通用 CLI 入口是 `uv run python -m brain_region_pipeline`。
* 通用 Friends 串行标准接口是 `run-multi-roi-pilot`，支持 `summaries`、`domain-pools`、`schemas`、`scoring`、`manifest`、`encoding`、`all` 阶段。
* `run-multi-roi-pilot` 已经通过 config 中的 `episodes` 字段支持用户指定剧集、split、description 路径和 H5 dataset。
* 当前 `scripts/run_friends_14roi_s01s02_vertex_pilot.py` 是 one-off 扩展脚本：硬编码 s02 episode 集合，复用旧 s01 产物，只生成 s02 summaries/scoring，再写 manifest 并跑 encoding。
* 当前 `scripts/run_friends_7roi_vertex_pilot.py` 提供可复用的并发工具函数和 7 ROI 并发运行模式，支持 `domain_workers`、`schema_workers`、`scoring_workers`。
* 用户已确认：Friends 文档应写 14 ROI 并发脚本，但不能限定 s01+s02；应允许用户自己指定要处理的剧集。
* 用户已确认：保留通用 `run-multi-roi-pilot` 作为串行分阶段标准接口。
* 用户已确认：Fallen 一键流程不应把未 review 的 domain pool 自动确认伪装成正式科学流程；推荐一键复现应基于已有 confirmed pool/schema。

## Assumptions

* 泛化后的 14 ROI 并发脚本应继续复用 `brain_region_pipeline.pilot.runner` 中的配置读取、路径生成、manifest 写入和 encoding 逻辑，避免复制一套新 pipeline。
* 文档语言使用中文，新增独立文档路径初步定为 `docs/pipeline_usage_commands.md`。
* 代码改造应最小化，优先从现有 7 ROI 并发 runner 与 14 ROI s01+s02 runner 中抽出或复用已有模式。

## Open Questions

* 暂无阻塞问题；等待用户明确确认进入实现阶段。

## Requirements

* 新增通用 14 ROI 并发运行入口 `scripts/run_friends_14roi_concurrent_pilot.py`，让用户通过 config 指定 ROI 和 episode 集合，而不是在脚本中硬编码 s01/s02。
* 保留现有 `scripts/run_friends_14roi_s01s02_vertex_pilot.py` 作为历史 one-off 扩展脚本，不作为新文档主入口。
* MVP 只支持同一 `output_root` 内的完整生成和续跑，不支持跨 `output_root` 拷贝复用历史产物。
* 同一 `output_root` 内的续跑能力通过 `--skip-existing`、resume scoring、retry failed batches、workers 控制实现。
* 支持并发与非并发两种运行方式；非并发可通过 workers 设置为 1 实现。
* 新 14 ROI 并发脚本只提供 `--dry-run`、默认 full run、`--retry-failed-batches` 三种运行模式。
* 新 14 ROI 并发脚本提供 `--summary-workers`、`--domain-workers`、`--schema-workers`、`--scoring-workers` 控制各 LLM-heavy 阶段并发度。
* 新 14 ROI 并发脚本不提供 `--stage` 分阶段矩阵；分阶段流程继续由通用 `run-multi-roi-pilot --stage ...` 承担。
* 保留通用 `run-multi-roi-pilot` 串行分阶段标准接口，并在文档中明确它是最通用、最可审计的分阶段入口。
* 文档必须覆盖 Fallen 的 domain pool、schema、scoring、GT 对齐与相关性命令，包括分阶段与推荐一键复现。
* 文档必须覆盖 Friends 的 summaries、domain pools、schemas、scoring、manifest/encoding、encoding 相关性输出，包括分阶段、一键、并发和非并发命令。
* 文档必须明确 Fallen 的相关性与 Friends encoding 相关性的含义不同。

## Acceptance Criteria

* [ ] 14 ROI 并发入口不再硬编码 s02 episode 集合。
* [ ] 现有 s01+s02 one-off 脚本保持可用，不被泛化改造破坏历史复现语义。
* [ ] 14 ROI 并发入口可以从 config 中读取用户指定 episodes，并按这些 episodes 生成 summaries、scoring、manifest、encoding。
* [ ] 14 ROI 并发入口不要求提供旧 output root，也不自动跨目录复制历史产物。
* [ ] 并发入口支持 dry-run，能展示 ROI、episodes、输出目录和 workers。
* [ ] 并发入口默认执行 full run：summaries -> domain-pools -> schemas -> scoring -> manifest -> encoding。
* [ ] 并发入口支持 retry failed batches 后刷新 manifest 和 encoding。
* [ ] workers 设置为 1 时形成非并发运行方式。
* [ ] 使用文档包含 Fallen 和 Friends 的完整命令说明。
* [ ] README 或 docs 中不把历史 `sigma_grid_*` 产物误写成当前维护 CLI。
* [ ] 相关 help / dry-run / 单元测试通过。

## Definition Of Done

* 代码修改保持高内聚、低耦合，避免把所有逻辑塞入一个新上帝脚本。
* 复用现有 runner/config/encoding 逻辑，避免复制 scoring 或 encoding 业务逻辑。
* 核心分支和兼容性逻辑有必要注释，但不添加无意义注释。
* 使用 `uv run` 执行验证命令。
* 更新中文使用文档。

## Out Of Scope

* 不重做 scoring、summary、schema、encoding 的核心算法。
* 不新增新的 fMRI 数据格式推断能力。
* 不把 Fallen 的高斯平滑 sigma-grid 历史分析重新实现为正式 CLI，除非后续单独确认。
* 不强制迁移或删除已有 one-off 历史输出目录。

## Technical Notes

* 主要 CLI 文件：`brain_region_pipeline/cli.py`。
* Friends 标准串行 runner：`brain_region_pipeline/pilot/runner.py`。
* 当前 7 ROI 并发脚本：`scripts/run_friends_7roi_vertex_pilot.py`。
* 当前 14 ROI s01+s02 one-off 脚本：`scripts/run_friends_14roi_s01s02_vertex_pilot.py`。
* Friends 14 ROI 配置示例：`configs/friends_multi_roi_pilot.json`、`configs/friends_14roi_s01s02_vertex_gemini35_pilot_20260607.json`。
* Fallen 当前维护命令来自 `make-domain-pool`、`make-region-schema`、`summarize-descriptions`、`score-descriptions`、`correlate-scores`。
* Friends encoding 输出主指标来自 `encoding/group_summary.json`，parcel-wise Pearson 来自 subject 子目录下的 `parcel_metrics.jsonl`。
