# A0a 菜单 / Schema 顺序轴定位 v1

## 结论

本轮同批完整 2×2 定位实验完成了预注册的技术停止条件：40/40 次调用成功，5/5 个 primary seed 都呈现 `menu_dominant` 模式，conflict-oriented treatment 在四格合计 20/20 选择 `cross_check_conflicts`。

在当前 `tie-break=off`、canonical ↔ synth-first、人工 fact/conflict history 的受限设置中，fact-oriented control 的结构化候选动作随**可见菜单顺序**变化，而没有随 JSON Schema enum 顺序变化：

- 菜单为 canonical 时，control 为 `inspect_facts`，两个 schema 水平合计 10/10；
- 菜单为 synth-first 时，control 为 `synthesize_decision`，两个 schema 水平合计 10/10；
- treatment 不受这两个顺序轴影响，四格均为 `cross_check_conflicts`，合计 20/20。

这把上一轮的“组合顺序依赖”进一步定位到了当前探针中的可见菜单轴，但结论不能外推成 `qwen3:8b` 的普遍菜单偏置，也不能解释为真实路由能力。实验只记录人工历史条件下的结构化枚举选择，没有执行 route、tool、证据生成、任务反馈或能量再分配。

## 预注册问题与设计

本轮执行前冻结的计划见 [`A0A_MENU_SCHEMA_AXIS_PLAN_V1.md`](./A0A_MENU_SCHEMA_AXIS_PLAN_V1.md)。问题是：上一轮在 synth-first 条件下观察到的 fact-history control 偏离，来自可见菜单顺序、JSON Schema enum 顺序、两者对齐交互，还是任一通道单独引起？

本轮没有读取或池化旧运行的输出，而是在同一个后续 campaign 中重新发起四格调用：

| cell | 可见菜单 | JSON Schema enum |
|---|---|---|
| M0S0 | canonical | canonical |
| M1S0 | synth-first | canonical |
| M0S1 | canonical | synth-first |
| M1S1 | synth-first | synth-first |

其中：

- canonical：inspect → cross-check → synthesize；
- synth-first：synthesize → inspect → cross-check；
- 5 个 primary seed 为 11100、11200、11300、11400、11500；
- 每个 seed 跨四格重复，形成 20 个 pair、40 次调用；20 个 pair 不是 20 个独立样本；
- pair 内 control/treatment 使用相同 seed，两臂相邻、串行执行且不重试；
- control 为 fact-oriented history，treatment 为 conflict-oriented history；
- tie-break 关闭；模型为 `qwen3:8b`，temperature 0.6，`think=false`，输出受严格 JSON Schema 约束。

这里的“重新发起”不等于 held-out 或独立复现。M0S0 和 M1S1 的 20 次调用与上一轮对应 cell 使用相同 seed、request fingerprint 和 provider payload hash，输出也逐项相同；真正新增、用于区分两个顺序轴的是 M1S0 与 M0S1 两个 off-diagonal cell 的 20 次调用。因此，本轮提供的是同批 2×2 技术定位，不增加新的独立 seed 样本。

## 原始产物核验

规范运行目录为：

> `runs/a0a-action-axis/qwen3-8b-menu-schema-2x2-v1/`

本报告逐项读取并核对了该目录中的 `config.json`、`events.jsonl` 和 `metrics.json`：

- `config.json` 计划 20 个 pair、40 次调用、5 个跨四格重复的 primary seed，四格各 5 个 pair；
- pair 执行顺序为 control-first 10 个、treatment-first 10 个；
- `events.jsonl` 含 40 条事件，全部为 `status=completed`，每格 10 条、每个 seed 8 条；
- 20 个 pair ID 均唯一，没有 provider、JSON 或 schema 失败；
- `metrics.json` 的动作计数、位置计数、seed 判型和二元效应与 40 条事件重新聚合一致。

证据等级为 `exploratory_technical`，机器结果明确标记 `scientific_claim_eligible=false`。

## 结果

### 四格动作与目标转移

预注册目标转移是 `inspect_facts -> cross_check_conflicts`。四格结果为：

| cell | control 动作 | treatment 动作 | 目标转移 | control synthesis 率 |
|---|---|---|---:|---:|
| M0S0 | inspect × 5 | cross-check × 5 | 5/5 | 0.0 |
| M1S0 | synthesize × 5 | cross-check × 5 | 0/5 | 1.0 |
| M0S1 | inspect × 5 | cross-check × 5 | 5/5 | 0.0 |
| M1S1 | synthesize × 5 | cross-check × 5 | 0/5 | 1.0 |

汇总后：

| 指标 | 结果 |
|---|---:|
| 成功调用 | 40/40 |
| 完成配对 | 20/20 |
| 动作发生变化的 pair | 20/20 |
| 预注册目标转移 | 10/20 |
| control 动作 | inspect 10；synthesize 10 |
| treatment 动作 | cross-check 20 |
| 两臂语义目标命中 | 30/40 |
| 菜单第一项跟随 | 20/40 |
| Schema 第一项跟随 | 10/40 |

菜单第一项的 20/40 全部来自 control：fact-oriented control 在四格中 20/20 选择可见菜单第一项。treatment 20/20 选择 `cross_check_conflicts`，因此没有机械地跟随菜单第一项。Schema 第一项只在 M0S0 和 M1S1 的 control 中被选择，合计 10/40。

### Seed block 判型

每个 seed 的 control 四格动作都相同：

> M0S0=inspect，M1S0=synthesize，M0S1=inspect，M1S1=synthesize

因此 11100、11200、11300、11400、11500 全部被预注册规则判为 `menu_dominant`，即 5/5 个 seed block 同型。这里的主要重复单位是 seed block，不把四格中的 20 个 pair 当作独立样本。

### 二元描述效应

令 control 选择 `synthesize_decision` 时 Y=1，否则 Y=0。四格 synthesis 率为：

- M0S0=0.0；
- M1S0=1.0；
- M0S1=0.0；
- M1S1=1.0。

对应描述效应为：

| 效应 | 结果 |
|---|---:|
| menu simple effect，schema=canonical | 1.0 |
| menu simple effect，schema=synth-first | 1.0 |
| schema simple effect，menu=canonical | 0.0 |
| schema simple effect，menu=synth-first | 0.0 |
| 2×2 interaction | 0.0 |

这些是 5 个重复 seed block 上的描述量，不是把 20 个 pair 视作独立样本后得到的确认性统计推断。

### 资源与运行合同

| 指标 | 结果 |
|---|---:|
| 输入 token | 8,540 |
| 输出 token | 410 |
| 平均单次延迟 | 1.49 秒 |
| provider / JSON / schema 失败 | 0 |
| control-first / treatment-first | 10 / 10 pairs |

## 能解释什么

### 当前数据支持的局部结论

- 在当前 tie-off、canonical ↔ synth-first 的同批完整 2×2 中，两个新增 off-diagonal cell 将 fact-history control 的动作模式区分到可见菜单轴；schema enum 轴在这两个顺序水平下没有产生可见差异。
- conflict-history treatment 是本探针中的强语义信号：20/20 选择 `cross_check_conflicts`，没有被菜单或 schema 第一项机械覆盖。
- 上一轮同步重排菜单与 enum 所观察到的 synth-first 偏离，在本轮受限设计内可以进一步定位到菜单呈现，而不是 schema enum 顺序或两轴对齐交互。
- 本地模型、严格结构化输出、配对日程和审计产物可以稳定完成该 40-call campaign。

### 当前数据不支持的外推

- 不能称为 `qwen3:8b` 的普遍菜单位置偏置：只测试了一个模型、一个任务标识、两个顺序水平和带语义名称的三个 action。
- 不能排除 action token、标签含义、菜单描述方式或 fact-history 本身较弱造成的共同影响。
- 不能说明全部六种排列、tie-break on 或上一轮 cross-check-first 异常会呈现相同模式。
- 不能用 5 个 seed 的重复测量替代跨任务、跨模型或确认性复测。
- 不能证明历史由真实经验自然形成，也不能证明自组织分化。
- 不能把候选枚举选择称为真实路由、工具使用或反馈闭环。

## 判定与工程含义

- 运行合同：通过，40/40 调用成功。
- 预注册技术停止条件：通过，5/5 seed 为同一 `menu_dominant` 模式，treatment 20/20 为 cross-check。
- 顺序轴定位：在本轮受限条件下，菜单轴有描述效应，schema 轴和 2×2 interaction 为 0。
- 科学证据：仍为 `exploratory_technical`，不支持普遍模型偏置或真实自主路由主张。
- F0：可以并行推进 `predefined_role` 保守基线；history-conditioned 选择继续保持 shadow/log-only，不进入执行权限路径。

## 原始诊断建议

在扩大模型或 seed 前，优先补两个更能排除替代解释的小实验：

1. **Opaque action ID 映射**：让 schema 只返回不带语义的 ID，并跨 seed 轮换 ID→action 映射，区分可见菜单位置与 action token / 标签先验。
2. **历史语义补全**：加入等长 neutral history 和明确的 synthesis-oriented history，检查事实、冲突、综合三种历史是否分别稳定驱动三个动作，而不是只有 conflict history 足够强。

只有这些受控探针更稳健后，才值得把 history-conditioned 路由从 shadow 提升到真实 action → evidence → feedback episode；在此之前，F0 的 `predefined_role` 工程分支无需等待，可继续并行实现最小闭环。

## 路线图复核后的优先级更正

上述 opaque ID 与历史语义补全仍是有效的受控诊断，但不再是当前下一步。它们继续定位的是“人工历史文本 → 候选动作选择”这一远端代理，无法补齐隐状态表示、真实执行、残差反馈和多 Agent 交互之间的证据缺口。

当前 A0a 阶段到此停止。主线改为 R0-min → F0-contract → 使用 `predefined_role` 的 F0-model，先取得真实 action → evidence → feedback → reallocation 轨迹；随后在 L0 中直接比较真实轨迹的原始历史、结构化充分统计和必要时的 latent 表示。只有 F0/L0 暴露出候选动作编码或菜单顺序正在影响真实闭环决策时，才恢复 opaque ID 等探针。

执行更新（2026-07-14）：上述 F0 主线已完成，结果见 [`F0_PILOT_V1.md`](./F0_PILOT_V1.md)；当前进入 E0、A1/F-eval、B1/D1 与 L0，A0a 仍不恢复。
