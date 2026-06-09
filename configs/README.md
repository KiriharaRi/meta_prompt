# Config 使用说明

本目录保存可复现流程的配置文件。配置文件本身可以入仓，但其中的 `../friends/...` 路径是本地数据路径示例，外部用户运行前通常需要改成自己的数据位置。

Pilot runner 会把相对路径按 config 文件所在目录解析。因此 `configs/friends_multi_roi_pilot.json` 中的 `../friends/...` 实际对应仓库根目录下的 `friends/...`。这个目录用于放本地数据和运行输出，已被 `.gitignore` 忽略。

## Friends pilot configs

### `friends_multi_roi_pilot.json`

默认 14 ROI Friends pilot，provider 为 AIHubMix，模型为 `gemini-3.5-flash`。这是推荐的通用 config，也是 `scripts/run_friends_14roi_concurrent_pilot.py` 的默认配置。

包含的 ROI：

```text
DLPFC, VMPFC, OFC, ACC, PCC, Precuneus, IPL, SMG, AG, TPJ, pSTS, FFA, Insula, Temporal_Pole
```

默认 episode split：

```text
train: s01e01a, s01e05a, s01e06a
val:   s01e02a
test:  s01e03a
```

### `friends_vmpfc_tpj_ipl_pilot_20260605.json`

小规模 3 ROI pilot，适合先验证完整流程是否能跑通。ROI 为：

```text
VMPFC, TPJ, IPL
```

episode split 与默认 14 ROI config 相同。

### Vertex/Gemini historical configs

这些配置保留了已运行或扩展 pilot 的参数，用于追踪实验设置：

- `friends_7roi_vertex_gemini35_pilot_20260605.json`
- `friends_14roi_vertex_gemini35_pilot_20260606.json`
- `friends_14roi_s01s02_vertex_gemini35_pilot_20260607.json`

如果使用这些配置，需要提供 Gemini key，并根据需要设置：

```bash
export GEMINI_API_KEY="..."
export GEMINI_USE_VERTEXAI=true
```

## 必须检查的路径字段

每个 Friends pilot config 都包含以下关键字段：

```json
{
  "roi_definitions": "roi_definitions_brainnetome246_yeo.json",
  "atlas_labels": "../atlas/subregion_func_network_Yeo_updated.csv",
  "h5_file": "../friends/BN/sub-01/BN_246.h5",
  "output_root": "../friends/demo/multi_roi_pilot",
  "episodes": [
    {
      "episode_id": "s01e01a",
      "descriptions": "../friends/description/downloaded_refine_descriptions/mv_friends_s01e01a/descriptions/refined_description.md",
      "h5_dataset": "ses-003_task-s01e01a"
    }
  ]
}
```

运行前请确认：

- `atlas_labels` 指向 Brainnetome/Yeo CSV，通常可以使用仓库内的 `atlas/subregion_func_network_Yeo_updated.csv`。
- `roi_definitions` 指向本目录内的 `roi_definitions_brainnetome246_yeo.json`。
- `h5_file` 指向本地 Friends fMRI H5 文件。
- `episodes[].descriptions` 指向本地 refined description Markdown 文件。
- `episodes[].h5_dataset` 存在于 `h5_file` 中。
- `output_root` 指向你希望生成 summaries、scores 和 encoding 结果的位置。

## 运行前检查

推荐先运行 dry-run。它会验证 config、description 路径、H5 dataset 和 ROI parcel selection，不会调用 LLM，也不会写长跑输出。

```bash
uv run python scripts/run_friends_14roi_concurrent_pilot.py \
  --config configs/friends_multi_roi_pilot.json \
  --dry-run
```

如果 dry-run 因缺少 `../friends/...` 路径失败，说明需要先在仓库根目录下准备被 ignore 的 `friends/...` 数据目录，或把 config 中的路径改成你的绝对路径/其他本地路径。

## 输出目录

`output_root` 下会生成 summaries、domain pools、schemas、scores、manifest 和 encoding 结果。这些都是运行产物，默认不应提交到 GitHub。需要公开复现时，优先提交命令说明和 config，而不是提交长跑输出。
