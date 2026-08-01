# Biofield 局部主体性架构：当前工程探索规格

日期：2026-07-21

核心研究命题同步：2026-07-30

## 0. 文档状态

状态：**normative architecture**

本文是当前唯一架构规范，取代本路径下此前以中央 `AllocationDecision` 为主线的规格内容。[Biofield 核心研究命题](../research/BIOFIELD_CORE_RESEARCH_THESIS.md)定义“为什么研究”和主张边界；本文定义目标系统“如何分层、谁拥有什么权力以及需要哪些合同”。两者冲突时，核心研究命题决定研究对象，本文决定尚未被显式修订的运行时权力边界。

本次修订采纳 [Biofield 架构方向复盘](./BIOFIELD_LOCAL_AGENCY_REVIEW_2026-07-21.md) 的核心判断：此前系统已经建立了可执行、可观测、可审计的 Harness，但同时把任务选择、探索、分配和通信决策过多地收归中央。新的研究对象不再是“中央控制器能否计算出更好的 Allocation 矩阵”，而是：

> 在 Harness 保持事实、安全和资源权威的前提下，具有私有状态和局部行动权的 Agent，能否通过反复经验形成功能分化和任务内组织，并使少量组织经过独立证据、有限容量和可撤销选择压力成为可匹配、可复用、可退役且有净收益的组织资产。

本文同时借鉴 [Self-Improving Agents in the Era of Experience](https://openreview.net/pdf?id=IUltZSgLMm) 对 Harness、经验更新面和纵向评测的区分，但论文不是本项目的规范来源。本项目仍以可执行合同、因果对照和本地实验结果决定架构去留。

能量经济、任务测量和生物动力学的扩展思路见 [独立研究议程](../research/ENERGY_MEASUREMENT_BIO_RESEARCH_AGENDA_2026-07-21.md)。其中只有任务测量平面进入当前目标架构；宏观能量经济和具体生物机制保持独立实验线，在各自通过门槛前不写入运行时前提。

本文不改写历史架构文件和已完成结果。当前 canonical v3 sealed evidence 支持 E0 `f0.native.v2` Gate 0；其 runner/schema v2 将实际读取的 task/answer-key 原始 fixture 字节纳入递归 source closure。MEAS0 canonical foundation 已更新为 `runs/meas0/pilot/meas0-foundation-20260731-v27`。v27 schema-v2 自包含 lock 绑定 29 个 source，run 为 36 cases / 180 results、36/36 task-native，三次 replay hash 一致。formal runner v6 的 trust/cost/oracle 边界之外，正式 readiness 还要求 J-CAL/J-AUDIT 各 288-call exact invocation membership 和严格 provenance 隔离；固定 lifecycle 只从 ledger/checkpoint/qualification 推导；write-once formal store 从 sealed bytes 重验 typed ancestry。这只证明 foundation source closure 与离线合同可重放且在缺少生产 authority 时 fail closed；未产生真实 Judge、formal 或 confirmatory evidence，因此 Gate M 保持 `FAIL`。LA0 合同层已补齐 decision round-trip 与 ancestry 校验；LA1 canonical v8 使用 runner v5、19-source 递归闭包、严格终态/失败指标校验、authoritative failure summary 和 outer run identity 绑定，§7.3/§7.5 scripted technical criteria 已由 success、agent action failure-recovery 和 governance-paths 三类 sealed runs 支持；runner 终态失败保留由独立 failure-injection tests 支持。按照冻结 DAG，formal claim-bearing Gate 1 activation 仍等待 Gate M。组织记忆、真实模型和净收益实验仍未开始。第 12 节明确区分当前事实和目标状态，简明进度见[项目状态页](../STATUS.md)，reviewed evidence 分别见 [E0 Gate 0 V2](../../results/E0_GATE0_V2.md)、[LA0 Contract V1](../../results/LA0_CONTRACT_V1.md)、[MEAS0 Foundation V11](../../results/MEAS0_FOUNDATION_V11.md)和 [LA1 Scripted Technical V4](../../results/LA1_SCRIPTED_TECHNICAL_V4.md)；E0 V1、LA1 V1–V3 与 MEAS0 Foundation V1–V10 保留为历史审计。

## 1. 研究问题与主张边界

### 1.1 核心研究问题

传统多 Agent 系统通常预先固定：

- 角色；
- 任务到 Agent 的映射；
- 通信拓扑；
- 工作流阶段；
- 失败后的替代关系。

Biofield 要研究的是：上述组织结构中的一部分，能否从 Agent 的局部感知、私有状态、行动结果和跨任务经验中形成，而不是由中央 Router 完整指定；其中少量结构能否进一步通过跨任务筛选成为有界、可撤销的组织先验，而不是无限保存每个任务的完整拓扑。

需要回答七个逐级递进的问题：

1. **测量有效性**：任务理解能否形成版本化 TaskFrame/GoalGraph，将可正式判定部分冻结为 RequirementGraph，并由独立 MeasurementGraph/MeasurementSpec 可靠测量？
2. **工程可行性**：局部感知、意图、承诺、拒绝和通信能否通过确定性合同安全运行？
3. **功能分化**：相近初态 Agent 的行为差异是否来自局部经验和私有状态，而不是 ID、顺序、角色 Prompt 或不平等观察机会？
4. **O1 任务内组织**：Agent 能否在中心不生成具体 Intent 和拓扑的情况下形成承诺、通信、拒绝和接管关系？
5. **O1 组织价值与 Field 增量**：任务内组织在等成本下是否优于 Single/Fixed/Central，Field 是否优于 no-field 和简单广播？
6. **O2 组织选择与保留**：O1 候选能否被压缩成有限、可匹配、可复用、可冷却和可退役的组织资产，并在 held-out、drift 和 recurrence 上提供净收益？
7. **经验驱动改进**：同一 evolving system 在长任务序列和 T0/T1/T2 上是否获得 held-out gain，同时保持旧能力、可塑性、安全和可控性？

前一层不通过，不升级后一层主张。

### 1.2 最小价值主张

在具有可分解需求、可验证反馈和任务或环境变化的任务序列中，局部主体性组织相对于以下基线，是否获得至少一种可重复净收益：

- 单 Agent；
- 固定 `predefined_role`；
- 中央 Equal/UCB/Field allocator；
- 局部主体性但没有 Field 信号的系统。

净收益必须在总 token、模型调用、工具调用、墙钟时间和协调成本全部计入后成立。优先报告 Pareto 结果，不用一个任意加权总分掩盖质量与成本交换。

### 1.3 不提前宣称

- Agent 产生了不同选择，就等于形成了角色；
- 局部选择就等于去中心化；
- 重复运行就等于积累了经验；
- 私有记忆增加就等于获得了新能力；
- 多 Agent 提升来自组织，而不是更多计算；
- Field 信号优于无 Field 的局部决策；
- 一次任务成功就证明了自组织、自进化或元进化；
- O1 的任务内动态结构自动等于 O2 的跨任务组织演化；
- 高频、高流量或长期存在的通信路径自动值得固化；
- 为每个任务保存完整拓扑就等于形成组织记忆；
- task embedding 相似就意味着某个历史组织可以正迁移；
- 组织检索器可以绕过 Agent 的 Bid/Refusal 直接实例化正式 Commitment；
- Harness 可以被 Agent 自主改写安全边界、正式 Goal/Requirement、MeasurementGraph/MeasurementSpec/evaluator、Ledger 或终止规则。
- 物理能量、可用功、预算、信用、价格和激活信号可以合并成一个统一标量；
- ATP、膜电位、生态位或侧向抑制的名字本身证明对应机制适合 Agent；
- 另一个 LLM 给出分数，就等于建立了独立可靠的评测层。

## 2. 架构原则

### 2.1 权威与智能分离

Harness 持有环境事实、资源和安全权威，但不默认拥有全部组织智能。

Harness 可以拒绝非法行动、限制资源和终止运行；它不应替 Agent 产生全部合法行动，也不应把某个中央优化器的输出伪装成 Agent 自主选择。

### 2.2 提案与提交分离

模型或 Agent 只能提出：

- Intent；
- Bid；
- Refusal；
- Communication request；
- Action proposal；
- Local state update proposal。

只有 Harness 能把提案转化为具有资源、权限或公共状态效果的已提交事件。提案被接受，不代表提案者拥有最终事实权。

### 2.3 私有状态与公共事实分离

Agent 可以保留私有工作记忆、局部能力后验和关系偏好。以下内容仍必须进入公共、版本化且可审计的状态：

- 已接受 Claim 与 Evidence；
- 真实资源流转；
- 权限和副作用；
- 承诺、取消和终态；
- 影响其他 Agent 的通信；
- 用于正式实验判定的观测和指标。

私有状态可以不公开全文，但必须记录版本、来源窗口、更新类型和内容哈希，使行为变化能够追溯到哪个状态版本。

“私有”是相对于其他 Agent 和非授权观察者，不表示对治理层完全不可见。Harness 至少能够检查结构、版本、来源、大小、禁止字段和 sealing；若实验需要隐藏正文，应把可审计元数据与隔离 payload 分开，而不是放弃治理。

### 2.4 经验更新与治理边界分离

首轮允许演化的对象包括：

- Agent 的局部能力后验；
- 需求选择偏好；
- 可撤销的局部经验摘要；
- 通信对象偏好；
- 已验证的技能或工作模式引用。

首轮冻结、不可自修改的对象包括：

- 权限规则；
- 正式 GoalGraph/RequirementGraph、MeasurementGraph/MeasurementSpec、evaluator、Judge 配置和 acceptance rules；
- Ledger 守恒与结算规则；
- 事件 schema 和 artifact sealing；
- 安全 hard stop；
- 实验分组、指标和通过门槛。

改变后一组对象属于未来的 meta-layer 实验，不属于局部主体性 MVP。

### 2.5 任务理解、计划、执行与测量分离

此前“任务分解产生评测坐标系”的表述过强。目标、计划、实际执行与测量共享上游 `TaskContract`，但必须形成不同表示：

- `TaskFrame` 描述当前对用户意图、目标状态、初始状态、范围、约束、能力、风险和不确定性的理解；
- `GoalGraph` 描述希望哪些世界状态、约束和用户可见结果成立；
- `RequirementGraph` 是 GoalGraph 中冻结、可被正式判定的 requirement 子图，描述“什么必须成立”，不代表 Agent 的任务分解；
- `PlanGraph` 描述 Agent 打算通过哪些观察、决策、行动、验证和恢复步骤达到目标；
- `EpisodeGraph` 记录实际发生的状态、动作、工具返回、产物、证据和回答；
- `MeasurementGraph`/`MeasurementSpec` 描述观察什么、如何测量、什么证据足够以及不确定时如何处理；
- `EvaluationResult` 记录 EpisodeGraph 相对冻结测量规则的判定；
- `ResidualSnapshot` 只由已批准的 EvaluationResult 推导。

因此，任务分解与任务评测不是同一个坐标系。它们分别构造行动表示和测量表示，通过 GoalGraph/RequirementGraph 对齐，但权力不能合并。被评 Agent 可以提交 `GoalRevisionProposal`、`RequirementProposal` 或 `OntologyRevisionProposal` 指出理解或测量遗漏；它不能自行批准新维度、修改 acceptance rule 或选择对自己有利的正式 Judge。任何批准都会提升 schema/version，并使旧 Observation、Intent 和 Commitment 显式迁移或失效。

详细对象模型、现有评测对照和跨领域研究候选见[任务测量研究文档](../research/AGENT_TASK_MEASUREMENT_RESEARCH_2026-07-21.md)。

### 2.6 类比不直接产生架构

来自生物、物理、金融或社会系统的概念，只有在声明原定义、系统边界、目标变量、尺度/单位、因果机制、可证伪预测、简单基线和失效条件后，才能进入实验实现。

缺少上述信息的概念保留为叙事隐喻。即使概念具有功能类比，也必须接受消融：若普通阈值、队列、UCB、局部广播或其他简单机制等成本下同样有效，则不主张生物机制具有额外价值。

## 3. 系统分层与权力边界

### 3.1 Harness：事实、安全与资源权威

Harness 负责：

- 发布目标、需求 schema、验收条件和硬约束；
- 维护公共事实、Residual、Evidence、Claim 和 Artifact 状态；
- 检查权限、副作用、依赖、预算和并发限制；
- 对 Intent/Bid/Action 做合法性准入，而不是替 Agent 生成内容；
- 维护 grant/reserve/spend/return/settlement；
- 调用 Evaluation Plane 中确定性或冻结版本的检查器/Judge；
- 记录事件、因果父 ID、状态版本和 source hash；
- 处理超时、幂等、取消、回滚、终态和 fail-safe；
- 生成所有 Agent 可见的公共环境快照。

Harness 不负责：

- 为每个 Agent 选择具体需求；
- 直接生成完整 Agent-requirement Allocation 矩阵；
- 替 Agent 决定自身适配度；
- 为所有 Agent 指定通信对象；
- 直接修改 Agent 的局部表型；
- 把中央策略的决定记录成 Agent Intent。

### 3.2 Field：共享信号介质

Field 不再是中央 allocator 的别名。它从公共、可验证状态生成局部可见信号，例如：

- requirement residual pressure；
- 当前拥塞和重复工作信号；
- 未覆盖或低置信覆盖信号；
- 资源稀缺和准入成本；
- 风险、争议和 taint 警告；
- 环境变化或 schema 变化通知。

Field 输出的是 `LocalFieldObservation`，而不是 `AllocationDecision`。不同 Agent 可以因私有状态不同，对同一公共信号产生不同 Intent。

Field 的计算必须满足：

- 只使用声明过的公共输入；
- 版本化且可重放；
- 不读取其他 Agent 未公开的私有状态；
- 不携带隐式角色指令；
- 不输出 Agent 排名、requirement-agent assignment、完整 Allocation 或通信拓扑；
- 保持多通道可解释性，不把资源、残差、风险和信用静默压成一个标量；
- 可被 `no-field`、局部广播或简单标量信号替换，以便做因果消融。

### 3.3 Local Agent：局部控制器

每个 Agent (A_i) 持有私有状态：

```text
Z_i(t)
  ├─ capability_posterior
  ├─ uncertainty
  ├─ local_experience
  ├─ active_commitments
  ├─ requirement_preferences
  ├─ peer_interaction_state
  └─ state_version / provenance_window
```

Agent 可以：

- 读取授权范围内的公共任务状态和局部 Field 观测；
- 选择是否响应某个需求；
- 形成 Intent 和 Bid；
- 拒绝不适合、证据不足或风险过高的工作；
- 请求或提供结构化通信；
- 在承诺获得准入后执行动作；
- 根据自身行动、公共反馈和通信结果提出局部状态更新。

Agent 不能：

- 直接修改公共 Residual 或 Claim 状态；
- 自行铸造、转移或结算真实资源；
- 绕过 Harness 执行工具副作用；
- 把自己的判断写成已验证事实；
- 读取未授权的其他 Agent 私有状态；
- 修改自身权限、正式 Goal/Requirement、MeasurementGraph/MeasurementSpec 或正式 evaluator。

### 3.4 Admission 与冲突处理

多个 Agent 可以独立对同一需求投标。Harness 中的 Admission 层只执行公开、确定性的治理规则：

- 合法性与依赖检查；
- 资源和并发上限；
- 重复工作阈值；
- 已声明的探索最低配额；
- 对等条件下稳定、可重放的 tie-break；
- 风险或争议状态下的 hard stop。

Admission 不根据隐藏全局效用替 Agent 生成最优分工。若需要中央 UCB/Field 优化器，它作为明确的对照 arm 运行，不混入局部主体性主路径。

通信关系也采用提案和准入，而不是中央预建完整拓扑：Agent 发出 Offer/Request，对端接受后形成具有 scope、TTL 和资源配额的临时边。Harness 可以因权限、成本或风险拒绝该边，但不替双方选择交流对象。

### 3.5 Environment 与 Evaluation Plane

Environment 提供工具、文件、测试、日志、数据库状态和其他可观察结果。Evaluation Plane 把 `EnvironmentState + Evidence + Trajectory` 映射为 `accepted`、`rejected`、`unknown` 或 `disputed`，并生成版本化 `EvaluationResult` 和 Feedback。

Evaluation Plane 不是单个自由裁量的 LLM Agent，而是按以下优先级组合：

1. 环境原生最终状态；
2. 确定性测试、形式规则和安全不变量；
3. Evidence 来源、依赖和一致性检查；
4. 隔离、冻结、版本化和校准过的独立 Judge；
5. 无法自动判定时的人工升级。

Judge 不得与被评 Agent 共享可变私有状态，也不能修改 RequirementGraph、MeasurementSpec、Ledger、权限或实验分组。Judge 的模型、Prompt、采样支持状态、输入顺序和版本必须记录；Judge 不确定性不能静默转换成 accepted。

首轮外部执行采用两个主 provider：Codex/ChatGPT-auth 只承担 Subject，DeepSeek V4 Pro 只存在于外置 Evaluation Plane 中承担 Judge。subscription-backed Subject 可以先做 exploratory run；若用于 formal，必须封存所有可观测请求/响应与配置，并明确把黑盒限制写进 replay claim：系统只能重放 sealed Subject artifact 之后的评测，不能声称重新生成相同 Subject 输出。DeepSeek V4 Pro thinking 模式的 `temperature` 记为 `ignored`、seed 记为 `unsupported`，仍须通过 J-CAL/J-AUDIT；不得以虚构 seed 补足可重复性。两个 provider 只接收去标识且非敏感的批准输入，hidden gold、凭证、真实身份和敏感业务内容不得外发。第三 provider 只允许预注册为 shadow/fallback，不能在同一 comparison block 内替换主要 provider 或进入主效应判定。

用户是 lock 的签名 authority，独立 reviewer 审 gold 和 preflight。签名 metadata 表示批准动作，不是信任根；正式可信性仍须来自受信 transport/签名根，以及内容 hash、raw evidence、角色分离、ACL/隔离证明和独立审查。

EvaluationResult 影响公共事实、Residual、信用和后续 Field，但不能直接改写 Agent 私有状态。Agent 必须通过 `LocalStateUpdate` 明确消费哪些评测结果并形成何种变化。

MEAS0 先实现冻结测量包，不在首轮引入动态选择。只有固定 Evaluation Plane 通过后，后续 MEAS1 才允许比较固定全量、固定最小和主动风险加权测量：系统依据关键性、不确定性、后果、信号冲突与预期成本选择下一项 MeasurementSpec，并在证据足够或预算耗尽时停止。预算耗尽不能把关键 `unknown` 转成 accepted。

### 3.6 Organization Memory 与 Prior Retriever

任务内实际形成的 commitment/communication/evidence topology 属于 O1 任务表型。它不能因一次成功直接成为跨任务正式先验。O2 组织记忆只保存经过独立评价和 held-out 复验的可重构组织资产，例如：

- 条件化 organization recipe；
- communication、verification、aggregation 和 takeover motif；
- 必要功能与证据接口；
- 可变成员、工具、并行度和局部边；
- 适用域、失败域、成本、不确定性和 source evidence；
- 降级、解体、版本失效和重新认证条件。

运行时 archive 必须有固定容量或复杂度预算。完整运行图和私有状态可以进入不可变审计存档，但默认不能全部进入正式检索面。

`OrganizationPriorRetriever` 可以根据公开任务条件返回少量候选先验、预测净收益、不确定性、失败域和 canary 建议。它不能：

- 强制某个 Agent 成为组织成员；
- 直接产生 requirement-agent assignment；
- 生成不可修改的正式通信图；
- 绕过 Intent/Bid/Refusal 和 Admission 创建 Commitment。

候选先验以 affordance/offer 的形式进入 Agent 可见范围。Agent 根据自身私有状态和当前 Field 决定接受、拒绝或提出修改；Harness 只做权限、预算、并发和安全准入。中央 task-aware topology selector 保留为强基线，不混入 Biofield 主路径。

## 4. 公共合同

### 4.1 保留合同

以下已实现语义继续保留，并在未来重构中保持兼容或提供显式迁移：

- `TaskSpec`；
- `RequirementSpec`；
- `ActionObservation`；
- `FeedbackEvent`；
- `ResourceEvent`；
- `ResidualSnapshot`；
- `RequirementGraph`、`MeasurementSpec` 与 `EvaluationResult`；
- `ExperimentResult`；
- run lifecycle、artifact sealing 和终态后写保护。

### 4.2 LocalFieldObservation

```text
LocalFieldObservation
  observation_id
  agent_id
  task_id
  requirement_schema_version
  public_state_revision
  visible_requirement_signals[]
  congestion_signals[]
  resource_terms[]
  risk_flags[]
  source_event_ids[]
  field_policy_version
  created_at / expires_at
```

观测必须是对公共状态的版本化投影。相同公共事件流、Agent 可见性和 Field 版本必须得到相同观测。

### 4.3 AgentIntent

```text
AgentIntent
  intent_id
  agent_id
  observation_id
  local_state_version
  target_requirement_id
  proposed_action_family
  expected_evidence_type
  expected_marginal_progress
  confidence / uncertainty
  requested_resource_bounds
  dependency_refs[]
  expires_at
```

Intent 表达“想做什么及其局部依据”，不产生资源、承诺或公共事实变化。

### 4.4 AgentBid

```text
AgentBid
  bid_id
  intent_id
  capacity_commitment
  estimated_cost_vector
  requested_budget_vector
  expected_completion_window
  duplication_tolerance
  communication_needs[]
```

Bid 必须声明成本和不确定性。缺少成本上界或目标需求的 Bid 不得进入正式准入。

### 4.5 AgentCommitment

```text
AgentCommitment
  commitment_id
  bid_id
  admitted_resource_grant_ids[]
  allowed_tools[]
  accepted_scope
  causal_parent_ids[]
  status
  deadline
```

Commitment 由 Harness 对合法 Bid 准入后产生。Action 必须引用有效 Commitment；过期、取消或终态 Commitment 不能再次执行。

### 4.6 AgentRefusal

```text
AgentRefusal
  refusal_id
  agent_id
  observation_id
  local_state_version
  target_requirement_id
  reason_code
  bounded_explanation
  retry_conditions[]
```

Refusal 是一等事件，不能被静默当成失败。需要区分：能力不足、证据不足、依赖未满足、预算不足、风险拒绝和当前拥塞。

### 4.7 CommunicationOffer / CommunicationRequest

结构化通信至少声明：

- sender / intended receiver or audience；
- related requirement / commitment；
- payload schema 和大小；
- evidence refs / provenance；
- token 或字节成本；
- expiry；
- read/write visibility。

Harness 检查权限、配额和格式，但不替 Agent 选择交流对象。自由文本仅作为对照或受限 payload，不作为唯一公共合同。

### 4.8 LocalStateUpdate

```text
LocalStateUpdate
  update_id
  agent_id
  previous_state_version
  next_state_version
  update_kind
  source_event_window[]
  changed_fields[]
  before_hash
  after_hash
  reversibility / rollback_ref
```

模型可提出更新内容，Harness 只验证 schema、来源、大小、版本连续性和禁止字段。局部状态更新不能改变公共事实、安全边界或 Ledger。

### 4.9 UpdateSurfaceManifest

每个 run 在开始前冻结允许变化的表面：

```text
UpdateSurfaceManifest
  manifest_version
  mutable_surfaces[]
  frozen_surfaces[]
  per_surface_schema_versions
  per_surface_size_and_rate_limits
  promotion_rules
  invalidation_rules
  rollback_policy
```

任何 `LocalStateUpdate` 或经验写入都必须命中 manifest 中的允许路径。权限、正式 GoalGraph/RequirementGraph、MeasurementGraph/MeasurementSpec、evaluator、Ledger、事件 schema 和实验评分默认列入 `frozen_surfaces`。

### 4.10 ExperienceUpdateRecord

跨任务保留的经验不能只体现为“某个文件变了”。每次经验编译和写入都记录：

```text
ExperienceUpdateRecord
  experience_update_id
  agent_id
  source_event_window[]
  compiler_policy_version
  destination_surface
  previous_version
  candidate_hash
  validation_status
  promoted_version | rejected_reason
  expiry / invalidation_conditions
  rollback_ref
```

原始 trace、候选经验和被正式提升的经验必须区分。只有 `promoted` 记录能够影响后续正式评测；`rejected` 和 `quarantined` 记录仍保留审计证据。

### 4.11 OrganizationSnapshot

每个评测 checkpoint 生成：

- 活跃 Agent 与状态版本；
- requirement-commitment 关系；
- 通信边；
- 重复工作和拒绝分布；
- 各 Agent 的实际成本和被接受贡献；
- 中央预设的角色、路由和拓扑信息；
- 由经验产生的结构变化。

该快照用于区分“结构确实发生变化”与“最终分数偶然变化”。

### 4.12 TaskMeasurementBundle

每个正式任务在执行前冻结一个版本化测量包：

```text
TaskMeasurementBundle
  task_frame_ref
  goal_graph_version
  task_ontology_version
  requirement_graph_version
  measurement_graph_version
  measurement_specs[]
  acceptance_rules[]
  evaluator_versions[]
  deterministic_check_refs[]
  judge_refs[]
  metamorphic_relations[]
  uncertainty_and_escalation_rules
  measurement_budget
  outcome / process / evidence / cost / safety dimensions
  bundle_hash
```

`MeasurementSpec` 必须绑定目标 requirement、measurand、观测来源、执行程序、单位或尺度、预期覆盖、判定规则、不确定性路径、校准引用和成本估计。正式运行中修改测量包会产生新版本和新的 comparison block，不得追溯性重算旧 arm 来获得有利结果。

### 4.13 OrganizationPrior

```text
OrganizationPrior
  prior_id / prior_version
  lifecycle_status
  niche_descriptor
  applicability_contract
  required_function_interfaces[]
  organization_motifs[]
  mutable_dimensions[]
  prohibited_bindings[]
  cost_and_risk_profile
  positive_and_negative_transfer_evidence[]
  source_run_ids[]
  evaluator_and_environment_versions
  confidence / uncertainty
  invalidation_and_revalidation_rules
  rollback_ref
```

`OrganizationPrior` 不得绑定具体任务答案、未授权私有状态或永久 Agent ID。它只描述候选组织的条件、接口和证据，不产生执行权。

### 4.14 OrganizationArchiveRecord

```text
OrganizationArchiveRecord
  prior_id / prior_version
  lifecycle_status
  archive_slot / niche_id
  candidate_parent_ids[]
  admission_evidence[]
  held_out_block_refs[]
  counterfactual_ablation_refs[]
  net_value_vector
  uncertainty
  last_applicable_at / last_validated_at
  negative_transfer_events[]
  compatibility_manifest
  retirement_or_quarantine_reason
```

生命周期为 `candidate → probation → active → dormant → quarantine → retired`。长期未命中只能降低优先级或进入 dormant；退休还必须依据同 niche 支配、适用任务上的负迁移、版本失配、证据过期或需求加权保守净价值不足。退出运行时 archive 不删除审计证据。

## 5. 最小局部主体性闭环

```text
Harness 发布 TaskFrame / GoalGraph / RequirementGraph / hard constraints
        ↓
Evaluation Plane 冻结 MeasurementGraph / MeasurementSpec / AcceptanceRule
        ↓
Field 从公共状态生成 LocalFieldObservation
        ↓
Agent 结合私有 Z_i 产生 Intent / Bid / Refusal
        ↓
Harness 做确定性合法性、预算和并发准入
        ↓
AgentCommitment
        ↓
Agent 执行 Action，产生 EnvironmentState / Artifact / Evidence / Cost
        ↓
Evaluation Plane 产生 accepted / rejected / unknown / disputed
        ↓
Harness 更新公共事实、Residual 和 Ledger
        ↓
Agent 提出版本化 LocalStateUpdate
        ↓
下一轮局部观测、选择、通信或终止
```

闭环中的因果关系必须由稳定 ID 连接：

```text
observation
  → intent
  → bid | refusal
  → commitment
  → action
  → evidence
  → feedback
  → residual/resource update
  → local state update
  → next observation
```

任一缺失父事件、版本跳跃、资源越界或终态后写入都必须 fail closed。

## 6. 资源、可交付权利、进展、信用与价格

本节恢复并强化后期历史架构中已经形成的分层：真实资源、任务残差、贡献信用和动态价格不是同一个“能量”。新的分层进一步加入可交付权利和 exergy-like 可用能力，但不把物理学名词直接当成 Agent 运行时事实。

### 6.1 真实资源账本

真实资源保持向量单位：token、模型调用、GPU/CPU 时间、墙钟时间、工具调用、字节、人工时间、数据访问和货币成本。不同资源不在底层强制折算成单一“能量”。

底层记录至少包含：

```text
ResourceVector
  resource_type / unit
  amount
  location_or_executor
  availability_window
  quality_or_capability_constraints
  provenance
```

所有通信、反思、状态更新和失败重试都计入成本。多 Agent 不得通过漏记协调成本获得虚假优势。

资源状态只能通过版本化 `ResourceEvent` 变化。grant、reserve、spend、return 和 abnormal settlement 必须保持守恒、幂等和单一终态；同一 settlement ID 不得用于另一个 Agent，终态 Agent 不得再次消费或结算。

### 6.2 可用能力是上下文投影

同量资源对不同任务、模型、工具和时间窗口并不等价。允许从底层向量派生一个 exergy-like 的“当前可用能力”估计，用于回答某组资源在当前条件下能完成多少可验证工作。

该估计必须：

- 显式声明任务、环境和时间参照；
- 保留输入向量和转换路径；
- 不覆盖底层真实单位；
- 记录估计不确定性；
- 只作为 Bid、Admission 或分析信号，不成为新的守恒量。

Biofield 不主张 Agent 价值可以由物理 exergy 直接计算。这里是受约束的功能类比，不是价值理论。

### 6.3 可交付权利

Agent 获得的不是新资源所有权，而是经过准入、具有上限和有效期的执行权利：

```text
ResourceClaim
  claim_id
  grantee
  resource_vector
  allowed_scope
  reservation_window / ttl
  reliability_or_preemption_class
  parent_grant
  settlement_rule
```

Harness 独占 grant、reserve 和 settlement。Agent 可以 Bid、接受 Commitment、消费、返还或放弃权利，但不能自行铸造、转让或扩张资源。`ResourceClaim` 过期、撤销、部分消费和违约必须有显式终态。

### 6.4 任务进展

系统只维护基于当前 GoalGraph/RequirementGraph、MeasurementGraph/MeasurementSpec、证据和环境观测的估计残差 `D_hat(t)`，不把它称为真实世界残差。只有 accepted EvaluationResult 可以直接减少正式 Residual；rejected、unknown 和 disputed 进入失败、补证、争议或重验证路径。

Requirement 的新增、拆分、合并或语义改变必须提升 `requirement_schema_version`。旧 Intent、Bid、Commitment 和局部观测不能静默跨 schema 使用；必须显式迁移、重新观测或失效。

### 6.5 贡献信用

信用是可撤销的未来选择或资源参考，不是真实资源，不自动具有转让和兑付能力。信用必须绑定：

- Action；
- Evidence；
- EvaluationResult/Feedback；
- Requirement；
- Agent；
- state/version window。

后续 Evidence 失效时，相关信用必须能进入 provisional、tainted、quarantined 或 revoked。

Evidence 失效还必须沿版本化派生关系重新计算受影响 Claim、Residual 和后续 Artifact。重验证预算不足时保留 unknown 或 quarantined 状态，不把未知自动改成 accepted。

### 6.6 动态价格与局部压力

价格只是在当前任务和资源条件下，对稀缺、拥塞、机会成本和风险的派生信号。它不是资源本身，也不是贡献信用。

首轮可以把价格或压力用于：

- 向 Agent 暴露资源稀缺；
- 对超长 reservation 或拥塞通信增加成本；
- 比较不同转换路径的机会成本；
- 形成可消融的 Field 输入。

首轮禁止：

- 让价格更新直接创造资源；
- 让 Agent 用信用购买权限或绕过 hard stop；
- 用一个综合价格替代 outcome、cost、risk 和 safety 向量；
- 把动态价格称为已经实现的通用能量货币。

### 6.7 风险

首轮不把风险压成可优化的一个价格。风险由权限、隔离、审批、准入、hard stop、rollback 和安全非退化评测处理。风险价格只能作为观察或机会成本信号，不能取代安全不变量。

### 6.8 Run 与 Artifact 生命周期

run 创建时必须使用唯一 ID；已有目录、artifact 或 checkpoint 不得静默覆盖。config、event、metrics、summary 和 source hashes 通过 schema 校验后写入；finalize 产生终态 manifest 和逐文件 SHA-256，之后所有写操作必须失败。

公共状态只由已提交事件重放得到。模型文本、未准入提案和私有草稿不能绕过事件流直接改变正式终态。

## 7. 经验与演化层级

### 7.1 E0：Episode 内适应

同一任务内根据 Feedback 改变下一步 Intent、通信或动作。它证明闭环适应，不证明跨任务学习。

### 7.2 E1：Agent 经验适应

跨任务保留经来源约束的经验摘要、技能引用或关系记录。它必须在后续任务中被实际检索或消费，并能通过消融归因。

### 7.3 E2：组织演化

把经验证的 O1 候选提升为组织先验，并管理其 probation、active、dormant、quarantine 和 retired 生命周期。E2 是当前核心长期研究对象。它必须使用有界 archive、held-out 证据、反事实结构归因、负迁移记录和版本兼容规则。

### 7.4 E3：组织策略演化

改变 Agent 如何选择需求、评估自身能力、请求通信或更新局部状态。机制变化必须版本化，并在 held-out 任务上验证，不能只在产生它的任务上自证成功。

改变 organization generator、Retriever 或淘汰策略也属于 E3。它只有在固定规则的 E2 先通过后才允许单独预注册。

### 7.5 E4：Harness / Meta-evolution

只有当一个功能独立、持续存在的 meta-layer 把更新策略、评测协议或自身规则作为长期优化对象时，才使用 `meta-evolution`。首轮 Biofield 不实现它。

正式 GoalGraph/RequirementGraph、MeasurementGraph/MeasurementSpec、evaluator、Ledger、权限和 safety gates 在 SI0 之前保持外部冻结。任何未来 META0 都必须先具备 evaluator isolation、受限可变面、回滚和重新认证。

## 8. 安全与持续治理

局部主体性增加新的可变面：私有状态、Intent、Bid、通信边、经验写入和组织拓扑。每个可变面都必须有：

- schema；
- provenance；
- 大小与资源上限；
- 版本；
- admission；
- invalidation；
- rollback 或明确不可逆说明；
- 轨迹级审计记录。

首轮安全不变量：

1. Agent 提案不能绕过工具权限和资源准入；
2. 私有状态不能直接改变公共事实；
3. 通信不能隐式获得更高权限；
4. 正式 GoalGraph/RequirementGraph、MeasurementGraph/MeasurementSpec、AcceptanceRule 和 evaluator 版本不能由被评 Agent 修改；
5. 重放相同已提交事件得到相同公共终态；
6. 任一物质更新后仍可回到最近 sealed checkpoint；
7. 能力或效率提升伴随安全指标恶化时，不得登记为通过。

## 9. 基线与因果对照

O1 价值实验至少包含以下 arm：

| Arm | 行动产生方式 | 是否有私有状态 | 是否有 Field | 用途 |
|---|---|---:|---:|---|
| Single | 单 Agent 处理全任务 | 可选但冻结 | 否 | 多 Agent 净收益基线 |
| Fixed | `predefined_role` | 否 | 否 | 已验证 F0 基线 |
| Central | Equal/UCB/Field 产生分配 | 后验仅供中央使用 | 中央输入 | 中央优化基线 |
| Local-no-field | Agent 产生 Intent/Bid | 是 | 否 | 局部主体性主效应 |
| Local-field | Agent 产生 Intent/Bid | 是 | 是 | Biofield 信号增量效应 |

关键因果差分：

- `Local-no-field - Central`：局部行动权的影响；
- `Local-field - Local-no-field`：Field 信号的增量影响；
- `Local-field - Fixed`：动态组织相对预设角色的总影响；
- `Local-field - Single`：多 Agent 在全部协调成本计入后的净收益。

各 arm 必须保持模型版本、采样配置、工具、任务顺序、TaskMeasurementBundle/evaluator、总 token/调用预算和停止规则一致。无法完全匹配时，差异必须作为处理变量记录，而不是藏在实现细节中。

O2 组织记忆实验还必须增加：

| Arm | 组织复用方式 | 用途 |
|---|---|---|
| Local-cold-start | 每题从零形成 O1 | 测量组织记忆增量 |
| Local-field-no-retention | 有 Field，但不跨题保留组织 | 分离 Field 与 O2 |
| Cosine-unbounded-snapshot | 固定相似度阈值 + 无限完整快照 | 原始设想对照 |
| LRU/LFU-cache | 按时间或使用频率淘汰 | 简单缓存基线 |
| Bounded-archive | 有限 niche + held-out admission + Prior Retriever | O2 目标方案 |
| Central-task-adaptive | 中央按任务选择/生成拓扑 | 强中央路由基线 |
| Per-query-search | 每题重新搜索，完整计入搜索成本 | 昂贵上界 |

O2 不能从 O1 单次最优结果直接推导。Discovery、archive admission、frozen evaluation、drift 和 recurrence 必须使用隔离 task blocks。

## 10. 组织形成与涌现的最低证据

“出现了不同通信图”只证明结构差异。要主张组织形成，至少需要：

- 角色或任务偏好不是 system prompt 预写；
- 多次任务后结构具有可重复模式；
- state reset、通信冻结或 Field 移除会产生可预测性能变化；
- Agent ID 和候选顺序置换后结论仍成立；
- 与中央 allocator、固定角色和单 Agent 做等成本比较；
- 组织收益不能被某个单 Agent 的个体能力差异完全解释；
- 在 held-out 任务或 drift 后仍表现为可迁移组织能力。

只有组织结构带来超出额外计算的因果收益，才允许使用“collective capability”或“emergent organization”。否则只报告“局部协调策略”或“动态结构变化”。

以上只支持 O1。要主张 O2，还必须满足：

- 组织资产不是完整任务答案或固定 Agent ID 快照；
- 入库依据来自候选产生阶段之外的 held-out block；
- archive 容量或复杂度预算固定，收益不会依靠无限增长；
- 关键 motif 的 edge/node removal 或 topology swap 造成可预测退化；
- leave-one-family-out、伪相似任务和 drift 上分别报告正迁移、拒绝复用和重新分化；
- 相对 cold-start、LRU/LFU、中央 task-adaptive 和 per-query search 报告完整成本；
- dormant 组织在真正相关任务重现时可被重新认证，而低频关键结构不因 age-only 规则被误删。

## 11. 纵向自改进评测

同一 evolving system 必须跨 checkpoint 评测：

```text
T0：未消费 adaptation stream 的初始系统
  ↓
Adapt：允许积累局部经验和组织状态
  ↓
T1：replay + held-out 评测
  ↓
Delay / Drift：时间延迟、任务变化、schema 或资源变化
  ↓
T2：再次 replay + held-out + safety 评测
```

最低指标：

- **Held-out gain**：经验流之外任务的变化；
- **Backward retention**：旧任务能力是否保留；
- **Longitudinal stability**：T1 收益是否在 T2 存活；
- **Improvement efficiency**：单位增益的计算、交互和监督成本；
- **Path attribution**：收益来自 Field、私有状态、通信、Skill 还是其他路径；
- **Safety non-regression**：权限、错误接受、资源越界和攻击成功率是否恶化。

只在 adaptation stream 上提高，不登记为自改进证据。

## 12. 当前实现事实与目标差距

### 12.1 已实现且保留

- R0 公共合同和版本化任务夹具；
- Residual 状态机及 Evidence 失效语义；
- Ledger 守恒、幂等终止和异常结算；
- run lifecycle、schema validation、SHA-256 sealing 和终态写保护；
- Equal/UCB/Field/privileged reference 合成对照；
- `predefined_role` 的 F0 contract/model 闭环；
- 真实 `action → evidence → feedback → residual → reallocation → settlement` 轨迹；
- verifier-bound `f0.native.v2`、Evidence→Feedback 复评、Ledger/Residual primitive replay、migration、原子 checkpoint、完整执行 source closure、失败 CostVector 和 Gate 0 canonical evidence；
- 静态测量封存、R1/R2 evaluator，以及 MEAS0 N=36/五臂、36/36 task-native、typed evidence/decision closure、case-indexed artifacts、正式 artifact/readiness contracts 和 foundation run/seal/replay；
- MEAS0 派生 Judge、人工 review/adjudication、OS preflight evidence、正式指标和独立 36×5 formal runner primitives；所有 fake/test-only evidence 和 backend 均在生产验证边界拒绝；
- 局部行动/通信/状态治理、公开 multi-Bid resolver、deterministic OrganizationSnapshot，以及统一三 Agent success、agent action failure/recovery、`governance_paths`、config preregistration seal；runner 任意阶段终态失败保留与 replay 由独立 failure-injection tests 覆盖；
- history-conditioned 路由的负面/混合证据和 `shadow/log-only` 边界。

### 12.2 部分实现与尚未实现

- `MEAS0-S0`、R1/R2 evaluator 和 N=36/180 foundation 已实现，当前 36 case 均有 task-native MeasurementPlan。formal artifact layout、固定 comparison block/readiness binding、派生 Judge corpus/qualification/quarantine、盲审/仲裁/agreement、preflight command/log evidence、描述性指标/攻击分母和独立 36×5 runner 都已有确定性离线合同与 test-only 回归；
- 上述 formal 增量仍是 contract-only：canonical v27 foundation lock 已把完整本地 import closure纳入 29-source closure。formal runner v6 保留 Price/StageBudget/StageCost 与 receipt ancestry；readiness 新增 J-CAL/J-AUDIT 各 288-call exact invocation membership、独立 transport/ledger/qualification 和 source/template/entity provenance 隔离。固定 lifecycle 只从 ledger/checkpoint/qualification 推导，Python-only backend 与 write-once formal store支持 typed `execute/replay/summarize`。production oracle/readiness 只序列化 raw authorization，回放时必须注入外部 verifier；runner/outcome/store 从 production mode、FORMAL_READY binding 和证据类派生资格，不能靠 Boolean 升级。当前 package 仍为 candidate，且没有生产 trust roots/keys、真实 Judge 调用、受保护 corpus、批准 price/budget、正式 detection oracle、真实盲审/仲裁、可信 OS ACL/隔离证据、经签名并独立复核的 formal comparison lock 或 N=36 Pilot/confirmatory 运行。因此 Gate M 仍为 `FAIL`；
- 进程级 evaluator isolation、真实 JudgeCard 校准和生产 `unknown/disputed` 人工升级路径；
- multi-Bid resolver 与 OrganizationSnapshot 已实现；单 selected Bid 的 Grant/Commitment、ActionAuthorization→Harness executor/settlement 已接通，仍缺多 Commitment 原子物化；
- 通信 payload 的交付、receipt、single consume、字节/消息/资源结算与行为变化已实现；跨周期通用累计 quota 仍可扩展；
- `LocalStateUpdate`、`UpdateSurfaceManifest` 和 `ExperienceUpdateRecord` 已实现提案/编译/提交、消费门和 apply/replay/rollback；accepted Feedback 已可确定性更新 LocalState 并在 replay 中重新编译核验；
- OrganizationSnapshot 已实现合同/builder，并可从单周期事件流自动投影；完整多 Agent 结构仍待实现；
- `OrganizationPrior`、`OrganizationArchiveRecord` 和有界 archive；
- `OrganizationPriorRetriever`、canary、abstention 和冷启动回退；
- O1/O2 分离的 discovery/selection/transfer/drift/recurrence 任务流；
- 生产级任意分支统一 orchestrator 和多 Commitment 原子物化；当前 LA1 scripted technical package 已由三 Agent success、agent action failure/recovery 和真实治理路径复合证据覆盖，runner 终态失败及 authoritative failure summary 另由 deterministic failure-injection tests 覆盖，但 formal Gate 1 activation 仍受 Gate M 依赖约束；详见 [LA1 Scripted Technical V4](../../results/LA1_SCRIPTED_TECHNICAL_V4.md)；
- T0/T1/T2 纵向评测；
- 组织收益的等成本因果消融。

因此，当前结果支持 E0 Gate 0，证明 MEAS0 canonical v27 foundation 的 schema-v2 自包含 29-source 离线判决闭包、trust/cost/oracle ancestry、36/180、36/36 native 与三次 replay hash 一致，并表明正式证据、指标与 runner 的接口可以在 test-only 条件下 fail closed；它不证明真实 Judge 或 formal/confirmatory evidence 已取得，也不证明多信号 arm 优于简单基线、真实模型形成组织或产生净收益。MEAS0 在 production gold/detection/trust inputs、生产 backend、正式 comparison lock 和正式 Pilot/confirmatory 完成前不能升级 Gate M；依据冻结 DAG，LA1 formal Gate 1 也不能在 Gate M 失败时激活，更不能被写成 D/O1/O2 科学证据。

## 13. 实现顺序与架构门槛

1. **E0**：Gate 0 已由 canonical sealed run 支持；保持 `f0.native.v2` 公共重放回归；
2. **MEAS0**：canonical v27 foundation 已用 schema-v2 自包含 lock 绑定 29 个 source 和批准规则，封存 trust/price/checkpoint、Judge StageCost、receipt→artifact→ledger 和 exact-180 candidate outcome sidecar 的 typed/hash-bound formal 边界、36/180、36/36 task-native 与三次一致 replay hash；全部 formal primitive 仍仅 source-bound/contract-tested，Gate M 为 `FAIL`。下一步必须先落实 production trust roots、受保护 J-CAL/J-AUDIT corpus、正式 price/budget 与 fault-specific detection oracle，再形成正式 comparison lock，接入 production Subject/Judge backend，完成 DeepSeek V4 Pro protected/trusted J-CAL/J-AUDIT，并取得真实人工 gold、正式隔离/preflight、签名与独立复核后运行正式 Pilot/confirmatory；
3. **LA0**：已冻结主要合同、版本、因果父子关系和权限矩阵；
4. **LA1**：§7.3/§7.5 scripted technical criteria 已支持；formal Gate 1 activation pending Gate M。保持 success/failure-recovery/governance-paths 与 checkpoint 回归，后续可补多 Commitment 原子化；
5. **LA2**：替换为本地模型，仅验证真实模型能否稳定消费合同；
6. **DIFF0**：用 state reset/swap、ID/顺序置换证明差异来自真实局部经验；
7. **ORG0**：运行 Fixed/Central/Local-no-field/Local-field/Single 等成本 O1 对照；
8. **ORG1**：运行 bounded archive、原始无限快照、LRU/LFU、中央 selector、cold-start 和 per-query search 的 O2 对照；
9. **SI0**：对通过的 E1/E2 策略运行长任务序列和 T0/T1/T2；
10. **SAFE0**：对私有状态、通信、组织先验、反馈和准入做攻击与回滚验证；
11. **META0**：只有 SI0 和 SAFE0 都通过后才允许提出，不进入当前实现承诺。

**EN0** 能量经济模拟和 **BIO0** 生物动力学消融作为独立支线运行。它们不阻塞 E0/LA0；具体机制只有在各自通过并保持 Harness 不变量后，才可作为 ORG0 的预注册附加 arm，而不是静默混入主路径。

详细输入、指标和停止门槛见 [实验执行协议](../experiments/EXPERIMENT_PROTOCOL.md)。

## 14. 主张登记与停止原则

| 主张 | 当前状态 | 升级条件 |
|---|---|---|
| Harness 闭环可运行 | supported | 已有 F0 contract/model 证据 |
| 中央 allocator 可作为比较策略 | supported as baseline | 保持同接口与可重放 |
| Harness 公共状态可由事件确定性重放 | supported for `f0.native.v2` | E0 Gate 0 已通过；不外推模型或组织能力 |
| 目标、计划、实际 episode 与正式测量可以独立治理 | engineering scaffold only | MEAS0 多图合同、36/36 task-native foundation 和 formal contract-only primitives 已落盘；仍需生产 backend、真实外部证据及正式状态/规则/Judge 对照通过 |
| Agent 可安全产生局部 Intent/Bid | supported for scripted engineering | LA1 §7 technical package 已支持；formal Gate 1 pending Gate M，且不外推真实模型或组织净收益 |
| 本地模型可稳定消费局部主体合同 | untested | LA2 通过 |
| 局部经验能造成可因果验证的功能分化 | untested | DIFF0 reset/swap/ID-order 门槛通过 |
| Field 对局部决策有增量价值 | untested | ORG0 中优于 Local-no-field |
| 局部主体性优于中央分配 | untested | ORG0 等成本因果对照通过 |
| 形成了有价值的 O1 任务内组织 | untested | ORG0 等成本差分和结构消融通过 |
| 形成了有界、可迁移的 O2 组织记忆 | untested | ORG1 held-out/drift/recurrence 与 archive 门槛通过 |
| 系统发生经验驱动自改进 | untested | SI0 六类指标通过 |
| 系统实现 meta-evolution | out of scope | 需要独立 meta-layer 与持续安全治理 |
| 通用能量货币适用于 Agent 生态 | independent hypothesis | EN0 相对多维账本基线通过 |
| 生物启发机制有独立增量价值 | independent hypothesis | BIO0 单机制消融通过 |

出现以下任一情况时停止扩大 Biofield 主张，保留 Harness 和更简单策略：

- 局部合同在 scripted agents 下仍无法确定性运行；
- 正式评测仍主要依赖被评 Agent 自评，或 Judge 偏差无法校准；
- 本地模型无法稳定生成合法 Intent/Bid，且修复只依赖预写角色；
- 局部策略在等成本下持续输给 Fixed/Central；
- Field 相对 no-field 没有稳定增量；
- 收益在 state reset、Agent ID 置换或 held-out 任务上消失；
- 协调成本吞噬任务收益；
- 能力提升伴随安全退化且无法通过治理消除；
- 只有修改正式 Goal/Requirement、MeasurementGraph/MeasurementSpec、evaluator 或测试集才能维持“改进”。
- 只有把多维资源、信用和风险压成一个有利标量，结果才成立；
- 生物命名去除后，机制不能优于对应的简单算法基线。

负结果仍是有效结果。若局部主体性失败，本项目仍可产出一个确定性、可审计的 Agent Experiment Harness，以及关于中央分配、局部决策和组织涌现边界的实证结论。
