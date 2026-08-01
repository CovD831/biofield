# A0a 受限动作选择 Pilot v1

## 结论

A0a v1 得到了一个受限的技术信号：在三个数值优先级完全相同、菜单与 JSON Schema enum 顺序固定、系统显式要求平局时消费既有工作倾向的探针中，人工构造的成对语义历史稳定改变了 `qwen3:8b` 的结构化候选动作选择，变化超过本轮观察到的采样动作噪声。

规范扩样运行包含 40 个配对、80 次调用：

- 80/80 调用成功；
- control-first / treatment-first 配对为 20/20；
- sampling-noise：0/10 配对改变动作；
- fact-history → conflict-history：10/10 从 `inspect_facts` 切换到 `cross_check_conflicts`；
- neutral → manual conflict role：10/10 从 `inspect_facts` 切换到 `cross_check_conflicts`；
- conflict-history vs 同方向 manual role：10/10 都选择 `cross_check_conflicts`。

这支持一个更窄的主张：**在当前 probe contract 下，直接写入并被 Prompt 显式要求消费的工作倾向可以影响小模型的结构化候选动作选择。**

它不证明“Agent 已经自组织分化”，也不证明候选动作已经进入真实路由或工具执行。本轮 `execution_history` 是研究者直接写入工作倾向的语义 fixture，系统 Prompt 又明确规定在数值优先级相同时沿用该倾向；菜单/enum 位置也没有重排。下一步必须先验证结果是否独立于位置和显式 tie-break，再验证真实执行与反馈能否自然生成这种历史。

## 为什么增加 A0a

[A0 T0/T1 Pilot v1](./A0_T0_T1_PILOT_V1.md) 的 32 次完整任务调用全部把回顾式行为签名选为 `contradiction_resolution / cross_check`。任务本身强制要求找矛盾，因此自报标签出现饱和，无法区分历史是否真正改变下一步行为。

A0a 把测量点前移到动作发生之前：模型不完成整个任务，只能返回一个结构化候选 action。v1 记录的是枚举选择，不是完成任务后的回顾性标签；但它没有把 action 送入路由器或工具，因此不能称为实际路由执行。

## 设计

### 路由状态

每次请求都给出三个未完成需求：

| Requirement | 可执行动作 | 数值优先级 | 前置条件 |
|---|---|---:|---|
| fact extraction | `inspect_facts` | 1.0 | ready |
| contradiction resolution | `cross_check_conflicts` | 1.0 | ready |
| decision synthesis | `synthesize_decision` | 1.0 | ready |

剩余能量预算固定为 1 个动作，模型只能返回一个 action。列表顺序被声明为不代表优先级，但菜单和 JSON Schema enum 始终采用表中顺序，没有通过循环重排验证模型是否真正忽略位置。

### 四个对照

| 对照 | control | treatment | 目的 |
|---|---|---|---|
| sampling noise | neutral history + primary seed | 相同内容 + alternate seed | 估计离散动作噪声 |
| execution history | fact-oriented history | conflict-oriented history | 检查历史语义能否改变动作 |
| manual role | neutral history | neutral history + conflict system instruction | 手动角色正对照 |
| role channel | conflict history | neutral history + conflict system instruction | 观察两种诱导通道是否导向同一动作，不检验通道等效性 |

execution-history 两臂的目标模型实际输入 token 为 241/242，差异约 0.4%。sampling 两臂均为 236。manual-role 和 role-channel 的 Prompt 臂为 262 token，因此通道对照仍有指令长度混淆；它们只能作为正对照和方向一致性观察，不能单独估计纯通道效应或证明两种通道等效。

协议原本要求用 `specialized vs 等长 neutral filler` 估计历史语义效应；本轮 primary execution-history 实际比较的是 fact-oriented vs conflict-oriented history。neutral history 只进入 sampling、manual-role 和 role-channel 条件。因此本轮能报告两类直接语义历史对应的选择差异，不能报告 specialized 相对 neutral 的独立效应。

### 运行

初始技术检查：

- 2 个任务标识；
- 1 个 Agent 标签；
- 1 个 seed block；
- 8 个配对、16 次调用；
- 16/16 成功，方向与规范扩样完全一致。

规范扩样：

- 2 个任务标识；
- 1 个 Agent 标签；
- 每个任务标识 5 个冻结 seed，合计 10 个 primary seed block；
- 4 个条件；
- 40 个配对、80 次调用；
- 80/80 成功，无重试。

模型与运行参数继续使用 `qwen3:8b` Q4_K_M、temperature 0.6、top_p 0.9、top_k 40、`think=false`。由于输出只包含一个枚举 action，`num_predict` 降为 32。

机器可读产物：

- `runs/a0a-action-choice/qwen3-8b-action-technical-v1/`
- `runs/a0a-action-choice/qwen3-8b-action-5seeds-v1/`（规范结果）

## 结果

| 条件 | control 动作 | treatment 动作 | 改变配对 |
|---|---|---|---:|
| sampling noise | inspect × 10 | inspect × 10 | 0/10 |
| execution history | inspect × 10 | cross-check × 10 | 10/10 |
| manual role | inspect × 10 | cross-check × 10 | 10/10 |
| role channel | cross-check × 10 | cross-check × 10 | 0/10；方向一致 10/10 |

资源：

| 指标 | 结果 |
|---|---:|
| 输入 token | 19,570 |
| 输出 token | 842 |
| 平均单次延迟 | 1.63 秒 |
| 累计调用延迟 | 130.39 秒 |
| provider / JSON / schema 失败 | 0 |

与完整 R1 T1 的平均 22.57 秒相比，动作选择探针把平均单次延迟降低到 1.63 秒。先测动作、再选择性执行完整任务，适合形成并行实验树。

## 能解释什么

### 支持

- 历史并非只能改变措辞；在当前受限探针中，它能改变结构化候选动作选择。
- 该变化在每个任务标识 5 个冻结 seed、合计 10 个 primary seed block 上都稳定，且 sampling 条件没有观察到动作切换。
- 手动角色 Prompt 是有效正对照。
- 在当前探针里，冲突历史与冲突 Prompt 导向同一动作；这只说明结果方向一致，不说明两种通道效果等效。
- A0 应把“动作选择”和“动作后质量”分开测量；旧的回顾式单标签不足以承担主要判定。

### 不支持或尚未测试

- 历史由真实任务执行自然形成，而不是由研究者写入；
- 任务反馈会把 Agent 的未来动作倾向更新到正确方向；
- 多 Agent 会形成互补而非全部被同一历史吸引；
- 选择动作后执行质量一定改善；
- 这种效果在非平局 residual、目标模型或真实 harness 中仍成立；
- 系统不显式要求“沿用历史工作倾向”时仍有同样效果；
- 同样的语义效应在菜单和 enum 顺序重排后仍存在；
- `synthesize_decision` 也能被历史稳定诱导选择。

## 重要限制

### 1. 这是“可控性”而不是“自组织产生”

人工历史是研究者直接写入工作倾向的语义指令，并由 system Prompt 显式要求模型消费。v1 证明模型在当前合同下会响应这个输入，但没有证明该状态能由能量消耗、任务结果和反馈循环自然产生。

### 2. 两个任务在 A0a 中只有标识不同

A0a v1 的三个 residual 数值和动作菜单完全相同，`software_release_readiness` 与 `cold_chain_readiness` 只改变任务 ID。每个任务标识使用 5 个不同 primary seed，合计形成 10 个配对和 10 个不同 primary seed；它们不是两个真正不同的任务结构。报告不能把它们当作独立任务泛化证据。

### 3. 菜单和 enum 位置偏置未控制

动作菜单和 JSON Schema enum 始终按 `inspect_facts`、`cross_check_conflicts`、`synthesize_decision` 排列；neutral 条件也始终选择第一个动作。仅声明“顺序不代表优先级”不足以排除位置或约束解码偏置。后续必须同步循环重排菜单与 enum，并预注册“选择跟随历史语义而非位置”。

### 4. tie-break 是显式的

系统 Prompt 明确说明当三个数值优先级相同时沿用历史或系统中的工作倾向。这符合 harness 可控性测试，但会放大历史信号。必须增加移除该句的消融。

### 5. primary 对照偏离 neutral-filler 协议

协议预定的主要语义对照是 specialized history vs 等长 neutral filler，本轮实际使用 fact-oriented vs conflict-oriented history。两臂 token 接近，但两边都包含直接工作倾向，因此不能隔离 specialized 相对 neutral 的效应。

### 6. 手动 Prompt 更长

manual-role treatment 比 neutral control 多约 26 个输入 token。虽然方向符合预注册预期，但 Prompt 长度与语义尚未正交。

### 7. `synthesize_decision` 未覆盖

全部条件只观察到 `inspect_facts` 和 `cross_check_conflicts`，第三个候选动作从未被选择。本轮只验证了事实/冲突二元方向，不能外推到完整三动作空间。

### 8. action 尚未执行

环境只记录了结构化候选动作，没有让路由器或工具实际消耗资源、生成证据和收到反馈。因此本轮只验证了候选选择，尚未验证真实“分配—消耗—产出—反馈—再分配”循环。

## 下一步：A0a v2 经验诱导与反馈闭环

下一轮不再手写最终工作倾向，而是让历史从真实 episode 产生：

1. 给 Agent 一组事实提取或矛盾核验 episode；
2. 让它真实选择并执行对应工具动作；
3. 环境用确定性任务指标返回 accepted/rejected/partial feedback；
4. 把动作、证据和反馈压缩成相同长度的历史；
5. 交叉交换两类历史，再测下一动作；
6. 增加 neutral 与 misleading feedback；
7. 同时运行“保留 tie-break 指令”和“移除 tie-break 指令”两个分支。

进入上述经验闭环前，先运行菜单与 JSON Schema enum 的循环重排 × tie-break 开关消融，确认候选动作跟随历史语义而不是固定位置。

这将直接连接用户提出的能量循环：任务路由注入能量，动作消耗能量并产生证据，任务反馈改变未来路由倾向。

## 当前门槛判定

- A0a v1 的“固定菜单/enum 顺序与显式 tie-break 下，人工语义历史可控制结构化候选选择”技术门槛：通过。
- A0a 对位置重排与移除 tie-break 的稳健性门槛：尚未判定，等待消融实验。
- A0 整体的“经验会形成可用分化”科学门槛：未通过，等待 A0a v2。
- F0：可以开始实现带 `routing_mode=history_conditioned` 和 `routing_mode=predefined_role` 的最小工程闭环，但对外叙事必须限定为机制原型，不能声称已证明自组织涌现。
