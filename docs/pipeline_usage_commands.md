# Brain Region Pipeline 使用命令

本文档记录当前项目中 Fallen 与 Friends 两条流程的可运行命令。所有 Python 命令默认在仓库根目录执行，并使用 `uv run`。

## 公开复现边界

仓库提供源码、atlas/config 和命令说明。Fallen 描述文件、GT CSV、summary、Friends 剧集描述、H5 fMRI 文件、视频文件、LLM API key 和长跑输出不随仓库发布，需要用户自行准备或由命令生成。

本文中的 `fallen/...` 路径是本地 Fallen 数据目录示例。Friends config 中的相对路径按 config 文件所在目录解析，所以 `configs/friends_multi_roi_pilot.json` 里的 `../friends/...` 默认对应仓库根目录下被 ignore 的 `friends/...` 数据目录。运行前请先阅读 [configs/README.md](../configs/README.md)，并根据本地数据位置修改 `descriptions`、`h5_file`、`h5_dataset` 和 `output_root`。

## 0. 环境与 LLM Provider

默认 LLM provider 是 AIHubMix：

```bash
export AIHUBMIX_API_KEY="..."
# 可选，默认就是 https://aihubmix.com/v1
export AIHUBMIX_BASE_URL="https://aihubmix.com/v1"
```

如果 config 或命令显式使用 Gemini：

```bash
export GEMINI_API_KEY="..."
# 使用 Vertex AI Express API-key 模式时再打开
export GEMINI_USE_VERTEXAI=true
```

常用 provider/model 参数：

```bash
--provider aihubmix --model gemini-3.5-flash
--provider gemini --model gemini-3.5-flash
```

## 1. Fallen：描述打分与 GT 相关性

Fallen 的相关性是 description segment-level feature score 与人工 GT 情绪曲线的 Pearson 相关。当前维护 CLI 是 `correlate-scores`，支持指定单个 `--lag-s`；历史输出中的 `sigma_grid_*`、`gaussian_sigma20_*` 是已有分析产物，不是当前维护 CLI 命令。

推荐输入：

```text
描述文件: fallen/demo/refined_description_for_scoring.md
GT 目录: fallen/gt
已有 summary: fallen/previous_code/summary.json
atlas: atlas/subregion_func_network_Yeo_updated.csv
ROI definitions: configs/roi_definitions_brainnetome246_yeo.json
```

### 1.1 分阶段：生成 domain pool 草稿

```bash
uv run python -m brain_region_pipeline make-domain-pool \
  --atlas-labels atlas/subregion_func_network_Yeo_updated.csv \
  --target-region VMPFC \
  --proposal-runs 5 \
  --provider aihubmix \
  --model gemini-3.5-flash \
  --output-file fallen/demo/vmpfc_fallen_run/vmpfc_domain_pool_draft.json
```

这个命令只生成 `domain_pool_v2` 草稿。正式 schema 推理前需要人工 review，并将确认后的文件保存为：

```text
fallen/demo/vmpfc_fallen_run/vmpfc_domain_pool_confirmed.json
```

确认文件中的 `curation_status` 必须是 `confirmed`。不要把未经 review 的 domain pool 自动确认后用于正式科学结论。

### 1.2 分阶段：schema 推理

```bash
uv run python -m brain_region_pipeline make-region-schema \
  --atlas-labels atlas/subregion_func_network_Yeo_updated.csv \
  --target-region VMPFC \
  --domain-pool fallen/demo/vmpfc_fallen_run/vmpfc_domain_pool_confirmed.json \
  --roi-definitions configs/roi_definitions_brainnetome246_yeo.json \
  --roi-id VMPFC \
  --provider aihubmix \
  --model gemini-3.5-flash \
  --output-file fallen/demo/vmpfc_fallen_run/vmpfc_region_schema.json
```

### 1.3 分阶段：打分并对齐 GT

```bash
uv run python -m brain_region_pipeline score-descriptions \
  --descriptions fallen/demo/refined_description_for_scoring.md \
  --region-schema fallen/demo/vmpfc_fallen_run/vmpfc_region_schema.json \
  --output-dir fallen/demo/vmpfc_fallen_run/scored \
  --summary-file fallen/previous_code/summary.json \
  --gt-dir fallen/gt \
  --gt-file-pattern "*.csv" \
  --gt-time-column "视频时间(s)" \
  --gt-emotion-column "情绪值" \
  --provider aihubmix \
  --model gemini-3.5-flash \
  --scoring-batch-size 40 \
  --local-buffer-size 10 \
  --tr-s 1.49
```

中断后续跑：

```bash
uv run python -m brain_region_pipeline score-descriptions \
  --descriptions fallen/demo/refined_description_for_scoring.md \
  --region-schema fallen/demo/vmpfc_fallen_run/vmpfc_region_schema.json \
  --output-dir fallen/demo/vmpfc_fallen_run/scored \
  --summary-file fallen/previous_code/summary.json \
  --gt-dir fallen/gt \
  --gt-file-pattern "*.csv" \
  --gt-time-column "视频时间(s)" \
  --gt-emotion-column "情绪值" \
  --provider aihubmix \
  --model gemini-3.5-flash \
  --scoring-batch-size 40 \
  --local-buffer-size 10 \
  --tr-s 1.49 \
  --resume
```

从头重跑同一输出目录时才使用：

```bash
--overwrite
```

主要输出：

```text
fallen/demo/vmpfc_fallen_run/scored/
  segment_region_scores.jsonl
  segment_gt_means.jsonl
  tr_features.jsonl
  tr_descriptions_readable.jsonl
  scoring_metadata.json
  scoring_progress.json
```

### 1.4 分阶段：计算 Fallen GT 相关性

`--lag-s` 的含义是 feature time `t` 与 GT time `t + lag` 比较。

```bash
uv run python -m brain_region_pipeline correlate-scores \
  --scores-jsonl fallen/demo/vmpfc_fallen_run/scored/segment_region_scores.jsonl \
  --gt-jsonl fallen/demo/vmpfc_fallen_run/scored/segment_gt_means.jsonl \
  --target-emotion agitation \
  --lag-s 0 \
  --output-file fallen/demo/vmpfc_fallen_run/scored/pearson_lag0.json
```

例：计算 +30 秒 lag：

```bash
uv run python -m brain_region_pipeline correlate-scores \
  --scores-jsonl fallen/demo/vmpfc_fallen_run/scored/segment_region_scores.jsonl \
  --gt-jsonl fallen/demo/vmpfc_fallen_run/scored/segment_gt_means.jsonl \
  --target-emotion agitation \
  --lag-s 30 \
  --output-file fallen/demo/vmpfc_fallen_run/scored/pearson_lag30.json
```

### 1.5 推荐一键复现：基于已有 confirmed schema

如果已经有人工确认过的 schema，可以直接从 scoring + GT + correlation 开始：

```bash
uv run python -m brain_region_pipeline score-descriptions \
  --descriptions fallen/demo/refined_description_for_scoring.md \
  --region-schema fallen/demo/vmpfc_aihubmix_concurrent_fallen_full_20260604/vmpfc_region_schema.json \
  --output-dir fallen/demo/vmpfc_fallen_reproduce/scored \
  --summary-file fallen/previous_code/summary.json \
  --gt-dir fallen/gt \
  --gt-file-pattern "*.csv" \
  --gt-time-column "视频时间(s)" \
  --gt-emotion-column "情绪值" \
  --provider aihubmix \
  --model gemini-3.5-flash \
  --scoring-batch-size 40 \
  --local-buffer-size 10 \
  --tr-s 1.49 && \
uv run python -m brain_region_pipeline correlate-scores \
  --scores-jsonl fallen/demo/vmpfc_fallen_reproduce/scored/segment_region_scores.jsonl \
  --gt-jsonl fallen/demo/vmpfc_fallen_reproduce/scored/segment_gt_means.jsonl \
  --target-emotion agitation \
  --lag-s 0 \
  --output-file fallen/demo/vmpfc_fallen_reproduce/scored/pearson_lag0.json
```

从零开始的完整科学流程仍然需要在 domain pool 和 schema 之间停下来人工确认。

## 2. Friends：多 ROI 打分、encoding 与 fMRI 相关性

Friends 的“相关性”来自 encoding 阶段：模型用 ROI score features 预测 H5 fMRI target，输出 parcel-wise Pearson 和 ROI summary。它不是 Fallen 那种 GT CSV 相关性。

用户通过 config 决定处理哪些剧集。最关键字段是：

```json
{
  "output_root": "../friends/demo/multi_roi_pilot",
  "rois": ["DLPFC", "VMPFC", "OFC"],
  "episodes": [
    {
      "episode_id": "s01e01a",
      "split": "train",
      "descriptions": "../friends/description/downloaded_refine_descriptions/mv_friends_s01e01a/descriptions/refined_description.md",
      "h5_dataset": "ses-003_task-s01e01a"
    },
    {
      "episode_id": "s01e02a",
      "split": "val",
      "descriptions": "../friends/description/downloaded_refine_descriptions/mv_friends_s01e02a/descriptions/refined_description.md",
      "h5_dataset": "ses-001_task-s01e02a"
    },
    {
      "episode_id": "s01e03a",
      "split": "test",
      "descriptions": "../friends/description/downloaded_refine_descriptions/mv_friends_s01e03a/descriptions/refined_description.md",
      "h5_dataset": "ses-001_task-s01e03a"
    }
  ]
}
```

要求：

```text
每个 subject 必须至少有 train / val / test。
每个 episode 的 descriptions 路径必须存在。
h5_dataset 必须存在于 config 指定的 h5_file 中。
rois 建议使用 configs/roi_definitions_brainnetome246_yeo.json 中定义的 14 ROI。
14 ROI 并发脚本本身不硬编码 ROI 个数；实际 ROI 集合由 config 的 rois 字段决定。
```

### 2.1 串行分阶段标准接口

串行接口最适合调试和审计：

```bash
uv run python -m brain_region_pipeline run-multi-roi-pilot \
  --config configs/friends_multi_roi_pilot.json \
  --stage summaries
```

生成 domain pool 草稿：

```bash
uv run python -m brain_region_pipeline run-multi-roi-pilot \
  --config configs/friends_multi_roi_pilot.json \
  --stage domain-pools
```

分阶段执行时，`domain-pools` 只生成 draft。正式继续 schema 前，需要逐个 ROI review domain pool，并保存为：

```text
<output_root>/rois/<ROI>/domain_pool_confirmed.json
```

生成 schemas：

```bash
uv run python -m brain_region_pipeline run-multi-roi-pilot \
  --config configs/friends_multi_roi_pilot.json \
  --stage schemas
```

打分：

```bash
uv run python -m brain_region_pipeline run-multi-roi-pilot \
  --config configs/friends_multi_roi_pilot.json \
  --stage scoring \
  --resume-scoring
```

生成 encoding manifest：

```bash
uv run python -m brain_region_pipeline run-multi-roi-pilot \
  --config configs/friends_multi_roi_pilot.json \
  --stage manifest
```

运行 encoding 并计算 fMRI prediction Pearson：

```bash
uv run python -m brain_region_pipeline run-multi-roi-pilot \
  --config configs/friends_multi_roi_pilot.json \
  --stage encoding
```

### 2.2 串行一键 pilot

```bash
uv run python -m brain_region_pipeline run-multi-roi-pilot \
  --config configs/friends_multi_roi_pilot.json \
  --stage all \
  --resume-scoring
```

`--stage all` 会为了 pilot 连续运行而生成 `domain_pool_auto_confirmed.json`。这些自动确认文件适合 exploratory pilot；正式报告前仍要人工 review domain pool。

### 2.3 14 ROI 并发脚本：dry-run

新脚本默认读取 `configs/friends_multi_roi_pilot.json`，也可以通过 `--config` 指定自定义 episode 集合：

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_multi_roi_pilot.json \
  --dry-run
```

dry-run 只验证配置、description 路径、H5 dataset 和 ROI parcel selection，不调用 LLM，也不写长跑输出。

### 2.4 14 ROI 并发脚本：full run

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_multi_roi_pilot.json \
  --skip-existing-summaries \
  --summary-workers 1 \
  --domain-workers 4 \
  --schema-workers 4 \
  --scoring-workers 4
```

执行顺序固定为：

```text
summaries -> domain-pools -> schemas -> scoring -> manifest -> encoding
```

同一输出目录中已经有完整 summaries 时，`--skip-existing-summaries` 会跳过这些 summaries；如果是全新的 `output_root`，这个参数不会改变生成流程。为了让命令在已有 demo 输出目录和新输出目录下都更稳，推荐默认带上它：

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_multi_roi_pilot.json \
  --skip-existing-summaries \
  --summary-workers 1 \
  --domain-workers 4 \
  --schema-workers 4 \
  --scoring-workers 4
```

默认 scoring 是 resume-only；只有确认要清空已有 scoring 输出时才加：

```bash
--overwrite-scoring
```

### 2.5 14 ROI 并发脚本：单阶段运行

并发脚本支持与串行标准接口相同的 `--stage` 取值：`summaries`、`domain-pools`、`schemas`、`scoring`、`manifest`、`encoding` 和 `all`。默认是 `all`，单阶段只运行指定阶段，不会自动串联下游阶段。

只并发补 scoring：

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_multi_roi_pilot.json \
  --stage scoring \
  --scoring-workers 4
```

如果 scoring 更新后需要刷新下游结果，继续显式运行：

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_multi_roi_pilot.json \
  --stage manifest

uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_multi_roi_pilot.json \
  --stage encoding
```

`--retry-failed-batches` 仍是独立恢复模式，不和非 `all` 的 `--stage` 混用。

### 2.6 14 ROI 非并发 full run

把所有 workers 设为 1：

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_multi_roi_pilot.json \
  --skip-existing-summaries \
  --summary-workers 1 \
  --domain-workers 1 \
  --schema-workers 1 \
  --scoring-workers 1
```

### 2.7 重试 failed scoring batches

如果 `scoring_warnings.jsonl` 中存在 `batch_generation_failed_zero_filled`，可以只重试失败 batch。重试成功后脚本会刷新 manifest 和 encoding：

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_multi_roi_pilot.json \
  --retry-failed-batches \
  --scoring-workers 4
```

### 2.8 Friends 输出检查

输出根目录来自 config 的 `output_root`。典型结构：

```text
<output_root>/
  summaries/<episode_id>/
    summary.json
    summary_metadata.json
  rois/<ROI>/
    domain_pool_draft.json
    domain_pool_auto_confirmed.json
    region_schema.json
    scores/<episode_id>/
      segment_region_scores.jsonl
      tr_features.jsonl
      tr_descriptions_readable.jsonl
      scoring_metadata.json
      scoring_progress.json
  encoding/
    roi_encoding_manifest.jsonl
    roi_schemas.json
    group_summary.json
    encoding_metadata.json
    sub-01/
      alpha_search.json
      parcel_metrics.jsonl
      roi_summaries.json
      test_predictions.npz
      ridge_coefficients.npz
```

重点看：

```text
encoding/group_summary.json
encoding/<subject_id>/parcel_metrics.jsonl
encoding/<subject_id>/roi_summaries.json
```

`group_summary.json` 的主指标是 `mean_subject_mean_test_pearson`。`parcel_metrics.jsonl` 中每行的 `pearson` 是对应 Brainnetome parcel 的 test split prediction Pearson。

## 3. 常用验证命令

```bash
uv run python -m brain_region_pipeline --help
uv run python -m brain_region_pipeline run-multi-roi-pilot --help
uv run python scripts/run_friends_14roi_concurrent_pilot.py --help
uv run python scripts/run_friends_14roi_concurrent_pilot.py --dry-run
```

项目测试：

```bash
uv run python -m unittest discover -s tests -p 'test_*.py'
uv run python -m compileall brain_region_pipeline tests scripts
```
