# Biofield 能量经济、任务测量与生物动力学研究议程

日期：2026-07-21

## 0. 文档地位

本文把三组相互关联但不能互相替代的想法落成独立研究议程：

1. 宏观层面的能量—货币体系；
2. Agent 任务理解、分解、执行与测量的分离及对齐；
3. 膜电位、选择性通道、生态位和侧向抑制等生物启发局部动力学。

本文不是当前运行时合同，也不声称这些机制已经实现或有效。当前工程边界仍由 [当前架构规格](../architecture/ARCHITECTURE_EXPLORATION_FINAL.md) 决定，实验优先级由 [路线图](../experiments/EXPERIMENT_ROADMAP_REVIEW_V1.md) 和 [实验协议](../experiments/EXPERIMENT_PROTOCOL.md) 决定。

三条研究线分别获得证据前，不把它们合并成一套统一理论。宏观能量经济不作为 Biofield MVP 的货币实现；生物术语不直接成为代码对象；任务评测不由被评 Agent 自行决定。

## 1. 共同出发点：流动塑造结构，但流动不是完整解释

原始直觉“能量的生产、运输和消费构成结构的本质”保留为研究启发，但改写为可检验版本：

> 一个有边界的开放系统，需要持续获得可用能和物质输入，通过具有容量、效率和损耗的转换网络维持自身；反复成功的资源、信息和控制流路径可能塑造组织结构。

这里有四个必要修正：

1. 物理能量不被创造，只发生捕获、储存、转换、运输和耗散；
2. 相同焦耳数的能量不具有相同做功能力；
3. 能量充足不代表系统可运行，物质比例、转换设施、地点和时间可能成为独立瓶颈；
4. 结构还依赖边界、信息、催化/转换机制、历史路径和选择压力，不能仅由能量存量推出。

地球在能量上是开放系统：太阳辐射进入，能量在地表、大气和海洋中重新分布，最终以热辐射离开。对人类时间尺度而言，地球同时近似为物质上相对封闭的系统。因此宏观模型必须同时记录外部能量通量、内部循环、对外耗散和有限物质存量，不能只记录“外部注入”。

## 2. 宏观能量—货币体系

### 2.1 货币不是必须绑定实物

现代主要货币不是金本位。货币至少同时承担计价单位、交换媒介、价值储藏和最终结算工具；其可接受性还与税收、法律结算、发行机构信用、金融资产负债表和社会预期有关。

因此本研究不采用以下过强前提：

```text
货币必须绑定实物
  → 脱离实物就是超发
  → 超发必然直接产生通胀
```

研究采用更窄的表述：

> 当名义索取权持续增长，而风险调整后的实际可交付能力、信用和需求不能吸收这种增长时，系统可能出现兑付压力、价格重估和信任下降。

这使“能量货币”从一种价值本体论，转化为可研究的可交付权利和结算制度。

### 2.2 不采用“焦耳本位”

一兆焦电能、一兆焦高温热和一兆焦接近环境温度的废热，能量数值相同，可转换成有用功的能力不同。物质也不能通过质能等价式直接成为可兑现经济价值，因为绝大多数静质量能量在现实转换条件下不可访问。

底层至少区分：

```text
Energy    物理能量通量与存量
Exergy    相对于指定环境的最大可用功
Matter    不可由能量标量替代的材料和元素约束
Capacity  捕获、储存、转换与运输能力
Context   地点、时间、质量、可靠性和环境参照态
```

`exergy` 是有边界条件的工程量，不是普遍价值。它适合描述“这股能流在当前条件下还能完成多少工作”，不适合独立决定人的偏好、权利和社会价值。

### 2.3 五层模型

#### 第一层：生物物理账本

```text
ResourceVector
  energy_by_carrier
  exergy_by_reference_state
  material_stocks
  conversion_capacity
  storage_capacity
  transport_capacity
  location
  time_window
  quality
  provenance
```

底层保留向量和来源，不永久压缩成一个统一余额。

#### 第二层：转换网络

```text
ConversionEvent
  input_resources
  converter
  output_resources
  efficiency
  exergy_destroyed
  waste_outputs
  capacity_used
  location / time
  provenance
```

研究重点从“谁持有多少能量”转向“哪些路径能以什么成本、容量和损耗，把输入变成可交付输出”。反复有效的转换路径才可能形成稳定结构。

#### 第三层：可交付权利

真正接近货币的对象不是抽象焦耳，而是对未来服务的标准化索取权：

```text
DeliveryClaim
  claim_id
  issuer
  carrier_or_service
  amount
  delivery_location
  delivery_window
  quality
  reliability
  reserve_or_collateral_ref
  expiry
  settlement_rule
```

一个有效权利必须说明能兑换什么、何时何地兑换、由谁承担兑付义务以及失败如何结算。电力、峰值容量、储能、运输和计算服务可能需要不同权利，不预设一种全球统一 Energy Coin。

#### 第四层：信用

信用表示对未来转换和交付能力的有风险估计，不是新产生的物理资源。信用可以支持提前组织生产，但必须与真实能力和失败责任分离。

可定义研究指标：

\[
\rho_t =
\frac{\text{outstanding redeemable claims}}
{\text{risk-adjusted deliverable capacity}}
\]

`rho_t` 只用于模拟索取权覆盖压力，不把它当作现实通胀的充分公式。

#### 第五层：价格与交换

价格是地点、时间、风险、稀缺、偏好和制度共同作用的动态信号。价格可以帮助协调资源，但不能修改底层守恒关系，也不能把社会价值还原为 exergy。

### 2.4 层间不变量

1. 发行权利不会增加底层物理资源；
2. 信用评分不会直接改变已验证交付事实；
3. 价格变化不会重写历史转换损耗；
4. 底层资源必须保留单位、地点、时间、质量和来源；
5. 任何统一计价单位都只是任务或市场条件下的投影，不能成为唯一真值；
6. 结算必须同时产生权利终态和物理/服务交付证据；
7. 违约、过期和部分交付必须是显式状态，不能被当作成功删除。

### 2.5 与 Agent 生态的有限对应

宏观体系只提供概念分层，不直接决定 Biofield 实现。允许的有限对应是：

| 宏观对象 | Agent 生态中的候选对象 |
|---|---|
| 真实能源与物质 | token、模型调用、CPU/GPU、墙钟、工具、数据和人工监督 |
| 转换设施 | Agent、模型、工具和协作路径的条件转换能力 |
| 可交付权利 | 有上限、有 TTL、可结算的 grant/reservation/commitment |
| 信用 | 绑定证据、可撤销的贡献与可靠性后验 |
| 动态价格 | 局部资源压力、机会成本和拥塞信号 |

Agent 不得自行铸造资源。Harness 可以注入和结算真实资源；Agent 只能请求、保留、消费或返还经过准入的权利。

## 3. 细胞和生态系统给出的多载体启发

### 3.1 ATP 不是完整财富体系

ATP 更接近短周期、可复用的反应耦合载体，而不是细胞的全部财富或长期储备。细胞同时依赖：

- 葡萄糖、糖原和脂质等储存；
- ATP 等即时耦合载体；
- NADH/NADPH 等还原能力；
- 质子和离子梯度；
- 碳、氮、磷及其他物质原料；
- 膜、酶、线粒体和输运蛋白等转换结构。

因此，生物类比支持的是“多载体代谢系统”，而不是把所有东西合并成单一能量币。

### 3.2 可迁移映射与禁用映射

| 生物概念 | 候选功能映射 | 当前禁止的过强映射 |
|---|---|---|
| ATP | 短周期执行凭证或即时预算 | Agent 的全部价值与长期财富 |
| 糖原/脂质 | 储备预算和应急容量 | 实时激活信号 |
| 膜 | 权限、范围和选择性接口边界 | 任何普通 API 包装 |
| 膜电位 | 局部准备度、风险或激活阈值 | 货币余额或任务质量 |
| 离子泵 | 消耗资源维持局部状态的机制 | 免费自维持的“生命力” |
| 通道/缝隙连接 | 有条件、有容量、有 TTL 的局部通信 | 无限制全局广播 |
| 生态位 | 条件化输入—输出转换能力 | 固定自然语言角色标签 |
| 侧向抑制 | 已充分覆盖方向上的局部冗余抑制 | 中央替 Agent 指定分工 |

### 3.3 “生态位”的更严格定义

Agent 的生态位不定义为一个角色名称，而定义为条件转换函数：

\[
N_i(x, e, z_i) =
\mathbb{E}[\text{verified progress}\mid
\text{input }x,\ environment\ e,\ private\ state\ z_i]
- \text{cost} - \text{risk}
\]

只有当这种差异：

- 来自不同局部经历，而不是预写角色；
- 在多个任务中可重复；
- 在环境变化后可调整；
- 在 Agent ID 和候选顺序置换后仍存在；
- 相对简单基线有净收益；

才允许称为形成了功能生态位。

## 4. 任务理解、分解、执行与测量的分离

### 4.1 共享任务契约，但不共享一个坐标系

此前“任务分解产生任务坐标系，评测投影回该坐标系”的表述过强。当前改为五类不同但可引用的表示：

```text
TaskFrame        对意图、状态、范围、约束、能力、风险和不确定性的当前理解
GoalGraph        哪些目标、约束和用户可见结果应当成立
PlanGraph        Agent 计划怎样观察、行动、验证和恢复
EpisodeGraph     实际发生的状态、动作、工具返回、产物、证据和回答
MeasurementGraph 用哪些观测和规则判断 GoalGraph
```

`RequirementGraph` 是 `GoalGraph` 中冻结、可正式判定的 requirement 子图，而不是 Agent 的任务分解。任务分解产生行动表示 `PlanGraph`；任务评测产生测量表示 `MeasurementGraph`。两者共享 `TaskContract` 和 Goal/Requirement 引用，但执行者与评测权力必须分离。

任务执行过程中，EpisodeGraph 随事件增长，证据从 `unknown` 逐步填充；Agent 的可能性判断可因新证据收缩，发现新对象或约束时 TaskFrame/GoalGraph 也可能扩维。不得笼统把这些变化都称为“任务空间扩大”。

更完整的对象模型、现有 Agent 评测对照、主动测量和跨领域迁移见[任务测量研究文档](./AGENT_TASK_MEASUREMENT_RESEARCH_2026-07-21.md)。

### 4.2 Evaluation Plane

正式评测不等于再增加一个自由裁量的 LLM Agent。目标结构是独立的 Evaluation Plane：

```text
TaskFrame / GoalGraph / frozen RequirementGraph
        ↓
independent MeasurementGraph / MeasurementSpec + AcceptanceRule
        ↓
EpisodeGraph(Environment / Evidence / Trajectory / Artifact / Response)
        ↓
deterministic check → rule check → independent judge → human escalation
        ↓
EvaluationResult(pass / fail / unknown / disputed)
        ↓
Residual and credit settlement
```

优先级如下：

1. 环境原生最终状态；
2. 确定性测试、形式规则和安全不变量；
3. 来源、依赖和证据一致性检查；
4. 隔离、冻结和校准过的独立 Judge；
5. 无法自动判定时的人工升级。

Judge Agent 只能填补语义判定空缺。它不能直接修改任务、评分权重、Ledger 或被评 Agent 状态；其模型、Prompt、采样、版本、输入顺序和不确定性必须记录并可校准。

### 4.3 最小公共合同

```text
TaskOntology
  ontology_id / version
  concepts / relations
  allowed_requirement_types

TaskFrame
  task_id / version
  intent / desired_state / known_initial_state
  scope / constraints / capabilities
  uncertainty / risk / evidence_expectations

GoalGraph
  goal_id / parent / dependency
  desired_semantics
  source / criticality / schema_version

RequirementGraph
  requirement_id
  parent / dependency
  success_semantics
  criticality
  schema_version

MeasurementGraph
  measurement_graph_id / version
  target_goal_and_requirement_refs
  measurement_dependencies
  alternative_observation_paths
  hard_gates
  uncertainty_and_escalation_rules

MeasurementSpec
  measurement_id / version
  target_requirement
  measurand
  observation_source
  procedure
  unit_or_scale
  expected_coverage
  acceptance_rule
  uncertainty_rule
  calibration_ref
  cost_estimate
  judge_ref

EvaluationResult
  result_id
  measurement_id
  evidence_refs
  environment_state_hash
  trajectory_ref
  outcome
  confidence_or_uncertainty
  evaluator_version
  causal_parent_ids
```

Agent 发现目标理解或测量覆盖不完整时，可以提交 `GoalRevisionProposal`、`RequirementProposal` 或 `OntologyRevisionProposal`。只有 Evaluation Plane/Harness 按冻结治理规则批准后，才能产生新 schema version；旧 Commitment 必须显式迁移或失效。

### 4.4 Agent 任务评测的最低维度

Agent 评测至少区分：

1. **Outcome**：最终环境状态是否满足目标；
2. **Process**：是否遵守权限、顺序、依赖和政策；
3. **Evidence**：结论是否有可复查来源，是否存在冲突；
4. **Cost**：模型、工具、时间、通信、重试和监督成本；
5. **Reliability**：多次运行是否一致，而非最好一次是否成功；
6. **Robustness**：顺序、ID、环境扰动和攻击下是否保持；
7. **Adaptation**：经验后是否改善；
8. **Retention**：新经验是否破坏旧能力；
9. **Safety**：越权、错误接受和副作用是否增加。

不能用一个总分代替这些维度。综合分只允许作为预注册的派生视图，并同时保留原始向量。

## 5. 类比迁移合同

任何来自生物、物理、金融或社会系统的概念，在进入架构前必须填写：

```text
AnalogyTransferContract
  source_concept
  source_definition
  source_system_boundary
  invariant_or_conservation_law
  causal_mechanism
  target_variable
  target_unit_or_scale
  mapping_strength
  falsifiable_prediction
  simplest_baseline
  ablation
  known_mismatch
  rejection_condition
```

映射强度分三级：

- **结构同构**：共享可明确写出的数学结构、约束或守恒关系；
- **功能类比**：在系统中承担相似功能，但底层机制不同；
- **叙事隐喻**：只帮助思考，不能直接产生实现和主张。

若没有目标变量、单位/尺度、因果机制和可证伪预测，默认归入叙事隐喻。若一个生物机制不能优于更简单的阈值、队列、UCB 或局部广播基线，则接受该机制没有额外工程价值。

## 6. 三条独立实验线

### 6.1 MEAS0：Agent 任务测量学

这是 Biofield 主架构的基础实验，优先级最高。

研究问题：GoalGraph/RequirementGraph 与独立 MeasurementGraph/MeasurementSpec 能否在不依赖被评 Agent 自证的情况下，稳定测量结果、过程、成本、安全和可靠性？

必须比较：

- 最终状态/测试驱动评测；
- 规则 + 状态评测；
- 独立 Judge；
- 被评 Agent 自评；
- 混合 Evaluation Plane。

必须注入：漏掉的需求维度、冲突证据、Judge 顺序偏差、状态成功但过程违规、文本看似正确但环境未改变等场景。

MEAS0 只建立固定多信号基线。通过后可分别运行：

- MEAS1：蜕变关系与主动风险加权测量，检验能否在相同错误率下降低测量成本；
- MEAS2：数据量足够后研究任务难度/区分度、自适应任务选择和因果重放。

### 6.2 EN0：能量经济模拟

这是独立概念模拟，不阻塞 LA0/LA1，也不接入真实金融系统。

比较三种制度：

1. 单一标量 Energy Token；
2. 多维资源账本；
3. 多维账本 + exergy/转换网络 + 可交付权利 + 信用和动态价格。

环境冲击至少包括：输入能流波动、储能故障、运输瓶颈、材料短缺、转换设施失效和索取权扩张。指标包括交付率、claim coverage、浪费/不可用资源、价格波动、资源集中、违约、恢复时间和结构锁定。

### 6.3 BIO0：生物启发局部动力学

这是 Field/Agent 局部机制的独立消融线。每次只引入一个机制：

- membrane-like activation threshold；
- resource-consuming state maintenance；
- selective channel/gap-junction communication；
- local lateral inhibition；
- niche persistence and reversible re-specialization。

每个机制至少对比：无该机制、普通阈值/队列、局部无 Field 和中央策略。只允许在相同资源预算下报告覆盖、冗余、恢复、稳定性和净收益。

### 6.4 集成门槛

只有满足以下条件才把独立研究线接入 Biofield 主路径：

1. MEAS0 先冻结正式测量合同和 evaluator isolation；
2. EN0 证明分层模型相对标量模型提供可重复解释或预测增量；
3. BIO0 的具体机制优于简单基线，并通过对应消融；
4. 接入后仍保持 Harness 权限、Ledger 守恒、事件重放和 artifact sealing；
5. 不因为类比好听而改变预注册 outcome 或通过门槛。

## 7. 可证伪假设

| ID | 假设 | 反证或停止条件 |
|---|---|---|
| MEAS-H1 | GoalGraph/RequirementGraph + 独立 MeasurementGraph 比 Judge-only 更能发现状态/过程不一致 | 混合评测不提高错误检出，且成本显著更高 |
| MEAS-H2 | GoalGraph/MeasurementGraph 缺口能通过独立证据和未归类产物检测 | 缺口只能由任务作者事后人工指出 |
| MEAS-H3 | 蜕变关系在缺少完整 oracle 时提高错误检出 | 相对重复运行和固定规则没有增量，或引入过多误拒绝 |
| MEAS-H4 | 主动风险加权测量在相同错误率下降低评测成本 | 不优于固定最小/固定全量测试，或系统性忽略低概率高损失失败 |
| MEAS-H5 | 事件父链、动作消融和重放能区分最终状态正确与可归因完成 | 因果证据成本过高，或不能比时间顺序/状态检查提供额外诊断 |
| EN-H1 | 多维资源与可交付权利比标量币更能预测瓶颈和违约 | 标量模型等成本下同样准确且更稳定 |
| EN-H2 | 反复高收益转换路径会形成可测的结构依赖 | 路径结构不影响冲击恢复或资源效率 |
| BIO-H1 | 选择性局部通信能降低协调成本而不显著损失必要信息 | 仅增加消息延迟或形成信息孤岛 |
| BIO-H2 | 局部侧向抑制能减少冗余并保持需求覆盖 | 覆盖下降、振荡或输给简单拥塞阈值 |
| BIO-H3 | 局部经历能形成稳定但可逆的功能生态位 | 差异由 ID/顺序/Prompt 决定，或 drift 后不能调整 |

## 8. 与当前架构的关系

当前架构继续保持：

- Harness 管理真实资源、事实、安全、准入、结算和回滚；
- Evaluation Plane 管理正式 MeasurementSpec 和 EvaluationResult；
- Local Agent 产生 Intent/Bid/Refusal/Communication/Action proposal；
- Field 只传播公共状态的局部信号；
- 生物机制是可替换策略，不是运行时权威；
- 宏观能量经济是独立研究线，不授权真实货币发行或金融行为。

由此形成的最小闭环是：

```text
外部目标与真实资源
  → TaskFrame / GoalGraph / RequirementGraph
  → independent MeasurementGraph / MeasurementSpec
  → Field observation
  → Agent proposal / commitment / action
  → Environment state / Evidence / Trajectory
  → Evaluation Plane
  → Residual / Resource settlement / Revocable credit
  → Agent local update and organization change
```

## 9. 参考入口

- IMF, [Money: At the Center of Transactions](https://www.imf.org/en/publications/fandd/issues/series/back-to-basics/money)
- Bank of England, [What is money?](https://www.bankofengland.co.uk/explainers/what-is-money)
- NASA, [Climate and Earth’s Energy Budget](https://science.nasa.gov/earth/earth-observatory/climate-and-earths-energy-budget/)
- U.S. Department of Energy, [Exergy as useful-work potential](https://www.energy.gov/sites/prod/files/2014/03/f8/deer11_edwards.pdf)
- NCBI Bookshelf, [The Mitochondrion](https://www.ncbi.nlm.nih.gov/books/NBK26894/)
- NCBI Bookshelf, [How Cells Obtain Energy from Food](https://www.ncbi.nlm.nih.gov/books/NBK26882/)
- Sinsabaugh et al., [Ecoenzymatic stoichiometry of microbial nutrient acquisition](https://doi.org/10.1038/nature08632)
- Zhou et al., [WebArena](https://arxiv.org/abs/2307.13854)
- Yao et al., [tau-bench](https://arxiv.org/abs/2406.12045)
- Jimenez et al., [SWE-bench](https://arxiv.org/abs/2310.06770)
- Debenedetti et al., [AgentDojo](https://arxiv.org/abs/2406.13352)
- Shi et al., [Position bias in LLM-as-a-Judge](https://arxiv.org/abs/2406.07791)
- Wataoka et al., [Self-preference bias in LLM-as-a-Judge](https://arxiv.org/abs/2410.21819)
