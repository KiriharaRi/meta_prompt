# Run Multi-ROI Pilot Workflow

## Goal

实际运行既有多 ROI pilot workflow，按阶段依次完成 summary、每个 ROI 的 domain-pool、active dimension schema、per-ROI scoring、multi-ROI manifest 和 joint fMRI encoding。执行时不用 `--stage all`，而是逐步运行各 stage，便于定位失败点和记录中间产物。运行中发现 `emotion_experience` 被错误地作为所有 ROI 的强制域，需要先修复为仅 vmPFC 强制保留。

## What I Already Know

- 用户要求“实际运行一下整个多ROI编码的全部流程，不要用all，分步进行”。
- 已有入口：`uv run python -m brain_region_pipeline run-multi-roi-pilot --config configs/friends_multi_roi_pilot.json --stage <stage>`。
- pilot config 使用 6 个 ROI：`vmPFC`、`PCC_Precuneus`、`TPJ_IPL`、`Anterior_Temporal_Pole`、`OFC`、`Insula_FrontalOperculum`。
- episode split：train 使用 `s01e01a`、`s01e05a`、`s01e06a`、`s01e07a`、`s01e09a`；val 使用 `s01e02a`；test 使用 `s01e03a`。
- config 输出根目录为 `../friends/demo/multi_roi_pilot`。
- 运行 `domain-pools` 时发现非 vmPFC ROI 也被硬性注入并保留 `emotion_experience`，这应是 vmPFC 专属约束。
- 用户确认修复 ROI-aware emotion seed，但不新增显式分步确认机制；domain-pool confirmation 仍手动控制。

## Assumptions

- 允许对已提交代码做最小修复：`emotion_experience` 仅作为 vmPFC required domain；非 vmPFC 不硬性 seed / prompt / validate core emotion panel。
- summary 共享，domain-pool / schema 按 ROI 独立生成，scoring 按 ROI 跑，encoding 使用所有 ROI 拼接后的 manifest。
- 允许实际调用 Gemini API；如果网络、API key、quota 或模型服务失败，记录失败阶段和错误信息后停止。

## Requirements

- 先运行非写入的状态检查或 dry-run 只用于确认输入，不替代实际执行。
- 按顺序分别运行 `summaries`、`domain-pools`、`schemas`、`scoring`、`manifest`、`encoding`。
- 不使用 `--stage all`。
- 不新增 `confirm-domain-pools` 或其他显式确认阶段；确认文件由人工控制。
- 对 scoring 使用 resume 语义，避免已完成部分重复调用；除非确认需要，不强制 overwrite。
- 每个阶段完成后检查关键输出是否存在，再进入下一阶段。

## Acceptance Criteria

- [ ] summary stage 生成共享 episode summaries。
- [ ] vmPFC domain pool 仍强制保留 `emotion_experience`。
- [ ] 非 vmPFC domain pool 不再硬性注入或强制保留 `emotion_experience`。
- [ ] domain-pools stage 为每个 ROI 生成 draft domain pool；后续 confirmed pool 由人工确认控制。
- [ ] schemas stage 为每个 ROI 生成 active dimension schema。
- [ ] scoring stage 为每个 ROI 和 episode 生成 scoring/TR feature 输出。
- [ ] manifest stage 生成 multi ROI encoding manifest。
- [ ] encoding stage 完成 joint multi-ROI Ridge encoding 并写出 metrics/predictions/metadata。
- [ ] 最终汇报每个阶段的状态、关键输出路径，以及任何失败/跳过原因。

## Out Of Scope

- 不新增显式分步确认机制。
- 不重构配置格式。
- 不提交本地数据目录或运行产物，除非用户另行要求。

## Technical Notes

- CLI help 显示可用 stage：`summaries`、`domain-pools`、`schemas`、`scoring`、`manifest`、`encoding`、`all`。
- 本任务明确禁用 `all`，只使用单 stage 调用。
