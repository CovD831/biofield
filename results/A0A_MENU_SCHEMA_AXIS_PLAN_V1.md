# A0a 菜单 / Schema 顺序轴定位：预注册计划 v1

状态：在读取本轮模型输出前冻结。

## 1. 起因与问题

位置 / tie-break 消融中，fact-history control 在 `synthesize-first` 的同步菜单与 enum 顺序下 10/10 选择 `synthesize_decision`，而 conflict-history treatment 仍 10/10 选择 `cross_check_conflicts`。因为用户菜单和 JSON Schema enum 当时同步重排，现有结果只能证明“组合顺序依赖”，不能定位偏置来自哪个通道。

本轮只回答：

> 在 tie-break 关闭时，fact-history 的 synth-first 偏置由用户菜单顺序、JSON Schema enum 顺序、两者对齐交互，还是任一通道单独引起？

## 2. Fresh 2×2 设计

不把旧运行的对角 cell 池化为主结果。本轮在同一 fresh campaign 中完整重跑四格，以避免 cell 与运行批次共线。

两个顺序水平：

- canonical：inspect → cross-check → synthesize
- synth-first：synthesize → inspect → cross-check

四个 cell：

| cell | 用户菜单 | Schema enum |
|---|---|---|
| M0S0 | canonical | canonical |
| M1S0 | synth-first | canonical |
| M0S1 | canonical | synth-first |
| M1S1 | synth-first | synth-first |

冻结条件：

- tie-break 关闭；系统不含“平局时沿用历史”的策略句。
- 每个 cell 五个 paired seed，seed 为 11100、11200、11300、11400、11500。
- 每对 control 为 fact-oriented history，treatment 为 conflict-oriented history；配对内同 seed。
- 五个 seed 均跨四个 cell 复用，共 20 pairs、40 calls；20 对不是独立样本。
- 四个 cell 的执行位置按 seed 做循环轮换；arm 顺序总体 10/10 平衡。
- 串行执行，配对两臂相邻；失败保留在计划分母且不重试。
- 模型与生成参数沿用上一轮：`qwen3:8b`、temperature 0.6、`think=false`、严格 JSON Schema。

## 3. 预注册结果模式

对每个 seed，只用 fact-history control 的四格原始动作判型：

- **menu dominant**：M0S0=inspect、M1S0=synthesize、M0S1=inspect、M1S1=synthesize。
- **schema dominant**：M0S0=inspect、M1S0=inspect、M0S1=synthesize、M1S1=synthesize。
- **alignment conjunction**：只有 M1S1=synthesize，其余为 inspect。
- **either axis sufficient**：除 M0S0=inspect 外，其余均为 synthesize。
- **no synthesis bias**：四格均为 inspect。
- **always synthesis**：四格均为 synthesize。
- 其余模式记为 `other`，不得强行归因。

conflict-history treatment 是负对照，目标是在四格都选择 `cross_check_conflicts`。

## 4. 指标与停止条件

报告：

1. 每个 seed 的四格 control 原始动作与判型。
2. 每格有方向的 `inspect_facts → cross_check_conflicts` 目标转移。
3. control / treatment 动作分布与语义目标命中。
4. 菜单首位跟随与 Schema 首位跟随，分开计算。
5. 以“control 是否选择 synthesis”为二元量，报告四格率、四个 simple effects 与 2×2 interaction；这些只是五个 seed block 上的描述量，不做独立样本显著性叙事。

严格工程停止条件：

- 40/40 调用成功；
- 五个 seed 给出同一种预注册判型；
- conflict-history treatment 在四格合计 20/20 选择 `cross_check_conflicts`。

若模式混合、调用失败或 treatment 负对照不稳定，只报告探索结果，并优先增加 seed 或复测；不继续扩成 3×3。

## 5. 边界

即使出现一致判型，结论也仅适用于 tie-off、canonical ↔ synth-first、当前人工 fact/conflict history 和结构化候选动作选择。它不解释 tie-on 的 cross-first 异常，不覆盖全部六种排列、opaque action ID、synthesis-oriented history、真实路由或工具执行。若定位到菜单或 Schema 通道，下一步仍需通过 opaque ID 映射轮换排除 action token / 标签先验。
