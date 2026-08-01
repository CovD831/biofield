# A0a 位置与 tie-break 消融：预注册计划 v1

状态：在读取本轮模型输出前冻结。

## 1. 要排除的替代解释

A0a v1 固定按 `inspect_facts`、`cross_check_conflicts`、`synthesize_decision` 排列用户菜单与 JSON Schema enum，且系统指令明确要求平局时沿用历史。因此，事实历史选择第一项、冲突历史选择第二项，仍可能由位置偏置或显式 tie-break 指令共同造成。

本轮只检验下面这句技术命题：

> 在人工构造的事实/冲突历史下，结构化候选动作是否跟随历史语义，而不是菜单或 enum 的位置；移除显式 history tie-break 后，该关系是否仍存在。

它不检验真实路由、工具执行、经验形成、自组织分化或反馈闭环。

## 2. 冻结设计

- 模型与采样参数沿用 A0a v1：`qwen3:8b`、temperature 0.6、固定 seed、`think=false`、严格 JSON Schema。
- 单一标签化上下文：`software_release_readiness`。任务 ID 在本探针中不提供真实任务材料，因此不作为任务复现。
- 两个 tie-break 模式：on / off。
- 三个循环顺序，同时作用于用户菜单与 JSON Schema enum：
  1. inspect → cross-check → synthesize
  2. cross-check → synthesize → inspect
  3. synthesize → inspect → cross-check
- 五个 primary seed；同一 seed 在六个 factorial cell 中复用。
- 每个 cell 五个配对，每对两臂：fact-oriented history / conflict-oriented history；配对内使用同一个 seed。
- 合计 30 pairs、60 calls。它们是五个 seed 的重复测量，不是 30 个独立试验。
- control-first / treatment-first 总体 15/15；每个 action order 聚合后 5/5。失败留在计划分母中，不重试。

## 3. 预注册指标

目标转移固定为：

`inspect_facts → cross_check_conflicts`

报告以下指标：

1. `target_transition_successes`：只有上述有方向转移才算成功；仅仅“动作发生变化”不算。
2. `semantic_target_successes`：fact history 的目标为 inspect，conflict history 的目标为 cross-check。
3. `position_follow_successes`：所选动作是否等于该调用菜单与 enum 的第一项。
4. `selected_position_counts`：选择落在第一、第二、第三位置的次数。
5. `all_orders_target_success_by_tie`：对每个 tie-mode × seed block，三个循环顺序必须全部出现目标转移才成功；每个 tie mode 报 x/5。
6. 六个 factorial cell 的完整方向转移表。

本轮没有 identical-content sampling pair，不重新估计 sampling p90；此前噪声结果只能作为外部技术背景。

## 4. 预注册判读

- **严格技术通过**：60/60 调用成功、目标转移 30/30，且 tie on 与 off 的 `all_orders_target_success` 都为 5/5。
- **tie-break 依赖**：tie on 跨顺序稳定，而 tie off 出现系统性失败。
- **位置依赖**：失败集中在特定第一项，`position_follow` 上升，并且语义目标随循环顺序改变。
- **混合结果**：部分 seed 或 cell 通过，但不满足严格门槛；只报告适用条件，不将其写成稳健机制。
- **技术未通过**：输出合法但目标方向不稳定，或调用/Schema 失败使严格门槛无法判断。

即使严格通过，也只能说明两种人工历史语义对结构化候选选择的位置稳健性；因为没有 synthesis-oriented history，第三种语义方向仍未验证；fact-vs-conflict 也不修复原协议中 specialized-vs-neutral 的偏差。
