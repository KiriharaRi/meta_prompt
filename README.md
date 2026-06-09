# Brain-region Prompt Scoring Pipeline

这个仓库维护一套从电影密集描述生成脑区相关特征的复现流程。当前主要覆盖两条任务线：

- **Fallen**：对电影描述做 domain pool、schema 推理、segment-level 打分，并与人工 GT 情绪曲线计算 Pearson 相关。
- **Friends**：对剧集描述生成 rolling summaries，按多个 ROI 推理 schema 和打分，再用 ROI score features 做 fMRI Ridge encoding，输出 parcel-wise Pearson。

完整命令手册见 [docs/pipeline_usage_commands.md](docs/pipeline_usage_commands.md)。ROI 选择说明见 [docs/roi_selection.md](docs/roi_selection.md)。配置文件说明见 [configs/README.md](configs/README.md)。

## 1. 环境准备

本项目使用 `uv` 管理 Python 环境。所有命令默认在仓库根目录执行。

```bash
uv sync
uv run python -m brain_region_pipeline --help
```

`pyproject.toml` 当前要求 Python `>=3.14`。如果本机没有合适版本，可以先安装：

```bash
uv python install 3.14
uv sync
```

## 2. LLM Provider

默认 provider 是 AIHubMix，模型为 `gemini-3.5-flash`：

```bash
export AIHUBMIX_API_KEY="..."
export AIHUBMIX_BASE_URL="https://aihubmix.com/v1"
```

也可以显式使用 Gemini：

```bash
export GEMINI_API_KEY="..."
# Vertex AI Express API-key 模式才需要打开
export GEMINI_USE_VERTEXAI=true
```

命令级参数示例：

```bash
--provider aihubmix --model gemini-3.5-flash
--provider gemini --model gemini-3.5-flash
```

## 3. 数据边界

仓库包含源码、atlas/config 和复现命令说明。以下内容不随仓库发布，需要用户自行准备或由命令生成：

- Fallen 描述文件、GT CSV、summary 和长跑输出，例如 `fallen/demo/refined_description_for_scoring.md`、`fallen/gt`、`fallen/previous_code/summary.json`
- Friends 剧集描述文件，例如 config 中的 `../friends/description/.../refined_description.md`
- Friends H5 fMRI 文件，例如 config 中的 `../friends/BN/sub-01/BN_246.h5`
- 原始电影/剧集视频文件
- LLM 长跑输出、scoring 输出、encoding 输出
- 个人 `.env`、API key 和本地缓存

Fallen 命令里的 `fallen/...` 路径也是本地数据路径示例，仓库不会发布该目录。Pilot config 的相对路径按 config 文件所在目录解析。因此 `configs/friends_multi_roi_pilot.json` 中的 `../friends/...` 会解析到仓库根目录下的 `friends/...`，该目录已被 `.gitignore` 忽略。复现前请按你的机器目录修改命令或 `configs/*.json` 中的 `descriptions`、`h5_file` 和 `output_root`。

## 4. Fallen 快速复现

Fallen 的正式科学流程需要用户先准备本地描述文件、GT CSV 和 summary，并人工 review domain pool。推荐分阶段运行：

```bash
uv run python -m brain_region_pipeline make-domain-pool \
  --atlas-labels atlas/subregion_func_network_Yeo_updated.csv \
  --target-region VMPFC \
  --proposal-runs 5 \
  --provider aihubmix \
  --model gemini-3.5-flash \
  --output-file fallen/demo/vmpfc_fallen_run/vmpfc_domain_pool_draft.json
```

人工 review 后，将确认文件保存为 `domain_pool_confirmed.json`，并确保其中：

```json
"curation_status": "confirmed"
```

然后继续 schema、scoring 和 GT 相关性计算。完整分阶段命令见 [Fallen：描述打分与 GT 相关性](docs/pipeline_usage_commands.md#1-fallen描述打分与-gt-相关性)。

如果已经有人工确认过的 schema，可以直接从 scoring + GT + correlation 开始；详见 [推荐一键复现：基于已有 confirmed schema](docs/pipeline_usage_commands.md#15-推荐一键复现基于已有-confirmed-schema)。

## 5. Friends 快速复现

Friends 推荐先用 dry-run 检查 config、description 路径和 H5 dataset：

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_multi_roi_pilot.json \
  --dry-run
```

默认 14 ROI full run：

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_multi_roi_pilot.json \
  --skip-existing-summaries \
  --summary-workers 1 \
  --domain-workers 4 \
  --schema-workers 4 \
  --scoring-workers 4
```

非并发 full run 可以把所有 workers 设为 1：

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_multi_roi_pilot.json \
  --skip-existing-summaries \
  --summary-workers 1 \
  --domain-workers 1 \
  --schema-workers 1 \
  --scoring-workers 1
```

串行分阶段标准接口仍然是：

```bash
uv run python -m brain_region_pipeline run-multi-roi-pilot \
  --config configs/friends_multi_roi_pilot.json \
  --stage summaries
```

支持的 stages 包括 `summaries`、`domain-pools`、`schemas`、`scoring`、`manifest`、`encoding` 和 `all`。完整分阶段、并发/非并发、failed batch retry 命令见 [Friends：多 ROI 打分、encoding 与 fMRI 相关性](docs/pipeline_usage_commands.md#2-friends多-roi-打分encoding-与-fmri-相关性)。

## 6. 重要输出

Fallen scoring 重点输出：

```text
segment_region_scores.jsonl
segment_gt_means.jsonl
tr_features.jsonl
pearson_lag*.json
```

Friends encoding 重点输出：

```text
encoding/group_summary.json
encoding/<subject_id>/parcel_metrics.jsonl
encoding/<subject_id>/roi_summaries.json
```

Friends 的“相关性”是 encoding 阶段的 fMRI prediction Pearson，不是 Fallen 的 GT CSV 相关性。

## 7. 验证命令

不需要 LLM key 的基础检查：

```bash
uv run python -m brain_region_pipeline --help
uv run python -m brain_region_pipeline run-multi-roi-pilot --help
uv run python scripts/run_friends_14roi_concurrent_pilot.py --help
```

需要本地 Friends 数据的 dry-run：

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py --dry-run
```

测试：

```bash
uv run python -m unittest discover -s tests -p 'test_*.py'
uv run python -m compileall brain_region_pipeline tests scripts
```
