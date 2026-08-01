# A0a 位置与 tie-break 消融 v1

## 结论

本轮预注册的严格门槛**未通过**。`qwen3:8b` 在人工构造的冲突历史下 30/30 次都选择了 `cross_check_conflicts`，但事实历史下的 control 只有 16/30 次选择预期的 `inspect_facts`；另外 14 次分别选择 `synthesize_decision` 10 次、`cross_check_conflicts` 4 次，并且这些偏离随候选顺序系统变化。

规范运行共有 30 个配对、60 次调用：

- 60/60 调用成功，无重试；
- 目标转移 `inspect_facts -> cross_check_conflicts` 为 16/30；
- 两臂分别命中其历史语义目标的调用为 46/60；
- 选择菜单/enum 第一项的调用为 34/60；
- 5 个 primary seed 在 6 个因子 cell 中重复使用，不能把 30 个 pair 当作 30 个独立样本；
- 对每个 seed 同时要求三种顺序都出现目标转移时，tie-break 开和关均为 0/5 个成功 block。

因此，A0a v1 的“人工语义历史在固定顺序下可以控制结构化候选选择”不能升级为“选择跟随历史语义而非位置”。本轮数据表现出明确的位置依赖，尚不能支撑经验形成、自组织分化或真实路由/工具执行的主张。

本轮同步重排了可见菜单与 JSON Schema enum，所以只能确认**组合顺序会影响选择**，还不能定位偏置来自菜单呈现、schema enum 约束解码，还是二者交互。下一步应把这两个顺序正交解耦。

## 预注册问题

主张：在相同模型、任务、Agent 标签和成对 seed 下，结构化候选动作应跟随注入历史的语义，而不是菜单或 JSON Schema enum 的位置。

预注册目标转移为：

> fact-oriented history：`inspect_facts`  
> conflict-oriented history：`cross_check_conflicts`

主要 block 指标不是 30 个 pair 的总体命中率，而是：对于同一个 primary seed 和同一个 tie-break 状态，三种循环顺序是否**全部**产生目标转移。这避免用某一种有利顺序的结果掩盖位置依赖。

本实验仍只是结构化候选动作选择。它不执行路由、工具、资源消耗、证据生成或反馈更新。

## 设计

### 因子

| 因子 | 水平 |
|---|---|
| 历史语义 | fact-oriented control / conflict-oriented treatment |
| tie-break 指令 | on / off |
| 候选顺序 | inspect-first / cross-check-first / synthesize-first |
| primary seed | 11100、11200、11300、11400、11500 |

三个循环顺序为：

| 顺序 ID | 菜单与 schema enum 的同步顺序 |
|---|---|
| `inspect_first` | inspect → cross-check → synthesize |
| `cross_check_first` | cross-check → synthesize → inspect |
| `synthesize_first` | synthesize → inspect → cross-check |

每个 `tie-break × 顺序 × seed` cell 含一个相同 seed 的 control/treatment pair，因此总计 `2 × 3 × 5 = 30` 个配对、60 次调用。5 个 seed 在 6 个 cell 中重复测量；30 个配对不是独立任务样本。

control-first / treatment-first 各 15 个 pair。请求串行执行、pair 两臂相邻、不重试，失败仍保留在计划分母中。

### 模型与运行

- 运行目录：`runs/a0a-action-bias/qwen3-8b-position-tie-v1/`
- 模型：`qwen3:8b`，Q4_K_M；
- temperature 0.6，top-p 0.9，top-k 40；
- `think=false`，`num_predict=32`；
- 任务标识：`software_release_readiness`；
- Agent 标签：`agent.a`；
- 证据等级：`exploratory_technical`。

## 结果

### 总体

| 指标 | 结果 |
|---|---:|
| 成功调用 | 60/60 |
| 完成配对 | 30/30 |
| 目标转移 | 16/30 |
| 两臂语义目标命中 | 46/60 |
| 第一位置跟随 | 34/60 |
| control 动作 | inspect 16；synthesize 10；cross-check 4 |
| treatment 动作 | cross-check 30 |
| tie-break off 的全顺序成功 block | 0/5 |
| tie-break on 的全顺序成功 block | 0/5 |

`semantic target` 按每次调用所在臂定义：fact-oriented control 的目标是 `inspect_facts`，conflict-oriented treatment 的目标是 `cross_check_conflicts`。它不是独立于位置的因果效应指标。

### 按候选顺序

| 顺序 | control 选择 | treatment 选择 | 目标转移 | 两臂语义目标命中 | 第一位置跟随 |
|---|---|---|---:|---:|---:|
| inspect-first | inspect × 10 | cross-check × 10 | 10/10 | 20/20 | 10/20 |
| cross-check-first | inspect × 6；cross-check × 4 | cross-check × 10 | 6/10 | 16/20 | 14/20 |
| synthesize-first | synthesize × 10 | cross-check × 10 | 0/10 | 10/20 | 10/20 |

最关键的反例是 synthesize-first：事实历史的 control 10/10 都选了第一项 `synthesize_decision`，没有一次选择预注册语义目标 `inspect_facts`。inspect-first 恰好让事实语义目标位于第一项，因此目标转移达到 10/10；这两组共同表明固定顺序结果不能解释为纯历史语义效应。

### 按 tie-break 开关

| tie-break | 目标转移 | 两臂语义目标命中 | 第一位置跟随 | 全顺序成功 block |
|---|---:|---:|---:|---:|
| off | 10/15 | 25/30 | 15/30 | 0/5 |
| on | 6/15 | 21/30 | 19/30 | 0/5 |

移除显式 tie-break 后，总体目标转移没有消失，但依然无法跨三种顺序成立。tie-break off 的 10/15 高于 on 的 6/15，不能解释成 tie-break 指令增强了语义跟随；两种模式都没有通过主要 block 门槛。

### 资源与合同

| 指标 | 结果 |
|---|---:|
| 输入 token | 13,650 |
| 输出 token | 624 |
| 平均单次延迟 | 1.94 秒 |
| provider / JSON / schema 失败 | 0 |
| control-first / treatment-first | 15 / 15 pairs |

`config.json` 记录 30-pair 冻结日程、模型身份、生成参数、源文件哈希和预注册解释；`events.jsonl` 含 60 条完成事件；`metrics.json` 的 pair、动作、位置、顺序和 tie-break 汇总与事件逐条复核一致。

旧规范运行还有一个时序限制：每个 seed 都按固定的因子 cell 顺序执行，候选顺序与局部运行位置没有做轮换。Ollama 请求不共享会话状态，且五个 seed 的主要模式一致，但该设计仍未排除进程漂移、缓存或顺序效应。后续 runner 已将 cell 顺序改为按 seed 循环轮换；这项修复只用于未来运行，不改写本轮冻结产物。

## 能解释什么

### 支持

- 这个本地结构化调用合同可以稳定执行 60 次，未出现 provider、JSON 或 schema 失败。
- conflict-oriented treatment 在本探针内是强信号：三种顺序和两个 tie-break 状态下都选择 `cross_check_conflicts`。
- 候选组合顺序会系统性改变 fact-oriented control 的选择；固定顺序下的 10/10 不能被当作位置无关的历史效应。
- tie-break 不是唯一解释，因为关闭后仍有语义命中和位置依赖。

### 不支持或尚未定位

- 不支持“动作稳定跟随历史语义而非位置”的预注册严格主张；
- 不支持把 A0a v1 的固定顺序结果外推为三动作空间中的稳健路由能力；
- 不能区分可见菜单位置偏置与 JSON Schema enum 解码偏置，因为二者本轮同步重排；
- 不能把 5 个 seed 在 6 个 cell 中的重复测量解释成 30 个独立样本；
- 没有测试真实 episode 是否会形成 history；
- 没有执行动作，也没有产生证据、任务反馈或能量再分配；
- 没有验证多 Agent 互补分化或最终任务质量。

## 判定

- 运行合同：通过，60/60 调用成功。
- 固定顺序下人工历史可改变结构化候选选择：保留为既有局部观察。
- 位置无关的历史语义跟随严格门槛：**未通过**，两种 tie-break 状态的全顺序成功均为 0/5。
- 科学证据等级：`exploratory_technical`；`scientific_claim_eligible=false`。
- 经验诱导、自组织和真实执行：尚未进入验证。

## 下一步：正交解耦位置来源

在进入经验—反馈闭环前，先运行更小的定位实验：

1. 固定可见菜单顺序，只循环重排 JSON Schema enum；
2. 固定 schema enum 顺序，只循环重排可见菜单；
3. 增加一个不依赖 enum 的结构化编码对照，例如固定数值 action ID 后再映射语义；
4. 保持相同 history、task、seed 和 tie-break block；
5. 分别报告菜单首位跟随、enum 首位跟随和语义目标命中；
6. 只有语义目标跨正交位置条件稳定后，才进入真实动作—证据—反馈生成历史的实验。

在该定位完成前，F0 若继续，只能把 `predefined_role` 作为保守执行基线；history-conditioned 选择应保持 shadow/log-only，不能作为已验证的自主路由机制。
