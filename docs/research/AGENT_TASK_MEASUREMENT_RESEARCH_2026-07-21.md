# Agent 任务测量研究：从静态打分到主动证据获取

日期：2026-07-21

## 0. 文档地位

本文记录 Biofield 任务评测支线截至 2026-07-21 的当前思考，修正此前“任务分解产生评测坐标系”的过强表述，并提出 MEAS0 之后可证伪的跨领域研究方向。

本文不是当前代码能力声明。更新于 2026-07-30：当前代码已实现两个 R1 evidence-task evaluator 和真正 Pilot R2 `channel_order_ingest@1` 的 deterministic Python/SQLite evaluator 纵切；它们分离 subject/protected 输入并从实际 bytes/state 产生证据。正式 F01–F18 五臂 Pilot、evaluator source hash、进程级 ACL、Judge/人工校准和主动测量尚未实现。正式权力边界仍由[当前架构规格](../architecture/ARCHITECTURE_EXPLORATION_FINAL.md)决定；当前实现顺序和门槛由[实验协议](../experiments/EXPERIMENT_PROTOCOL.md)决定，现实进度见[项目状态页](../STATUS.md)。

本研究坚持两条边界：

1. 现有方法的重新组合不自动构成科学创新；
2. 跨领域概念只有产生新的可执行机制、预测或实验对照，才从启发升级为架构主张。

## 1. 问题重述

Agent 任务评测不只是“给最终回答打分”。一个完整任务 episode 至少包含：

```text
任务输入与上下文
  → Agent 的任务理解
  → 计划与任务分解
  → 环境状态、动作和工具返回
  → 代码、文件、数据库变更等产物
  → 最终回答与用户可见结果
  → 后续副作用、恢复和跨次表现
```

评测需要回答不同问题：

- 用户目标是否真正完成；
- 完成路径是否合规、安全；
- 结果是否由 Agent 的行动造成，而非偶然或外部进程；
- 证据是否充分、可追溯且没有被污染；
- 成功是否可重复，并在合理扰动下保持；
- 为得到结论消耗了多少评测资源；
- 当前证据不足时，系统是否能够输出 `unknown`，而不是猜测成功。

因此，本研究对象不是一个更强的 Judge，而是一个独立的任务测量系统。

## 2. 修正后的对象模型

### 2.1 五类图，而不是一个“共同坐标系”

任务理解、任务分解、任务执行和任务评测共享上游 `TaskContract`，但分别形成不同表示：

```text
TaskFrame
  对意图、目标状态、初始状态、范围、约束、能力、风险和不确定性的当前理解

GoalGraph
  哪些目标、约束和用户可见结果应当成立

PlanGraph
  Agent 计划通过哪些观察、决策、行动、验证和恢复步骤达到目标

EpisodeGraph
  实际发生的状态转换、动作、工具调用、产物、证据和回答

MeasurementGraph
  用哪些观测、测试、规则、Judge 或人工判断 GoalGraph，以及这些观测如何组合
```

`RequirementGraph` 保留为 `GoalGraph` 中冻结、可被正式判定的 requirement 子图。它描述“什么必须成立”，不再代表 Agent 的任务分解或执行计划。

五类图之间存在引用关系，但不能合并：

```text
TaskFrame ──→ GoalGraph ──→ RequirementGraph
     │              │                │
     └────→ PlanGraph                └────→ MeasurementGraph
                    │                            │
                    └────→ EpisodeGraph ─────────┘
```

### 2.2 潜在空间、实现轨迹和证据填充

Agent 形成初始任务模型 `M_0` 后，可将所有可能执行历史记为：

\[
\Omega(M_0)=\{\text{可能的状态、动作、轨迹、产物和结果}\}
\]

真实执行只实现其中一条不断增长的历史：

\[
h_{t+1}=h_t\oplus(a_t,o_{t+1},s_{t+1})
\]

执行过程中不同对象发生不同变化：

- `EpisodeGraph` 随事件追加而增长；
- 测量证据从 `unknown` 逐步被填充；
- Agent 的可能性判断通常因新证据收缩；
- 发现新对象、约束或风险时，`TaskFrame` 和 `GoalGraph` 可能扩维；
- 外部环境状态被 Agent 或其他进程改变。

因此，不笼统声称“任务空间不断扩大”。必须说明讨论的是潜在历史、Agent 信念、现实状态还是评测证据。

### 2.3 任务理解的公共字段

首轮候选 `TaskFrame`：

```text
TaskFrame
  task_id / version
  user_intent
  desired_state
  known_initial_state
  entities_and_scope
  constraints_and_permissions
  available_capabilities
  uncertainties_and_ambiguities
  risk_and_reversibility
  required_artifacts
  evidence_expectations
  provenance
```

任务理解不是一次性完成。Agent 可以依据新观测提交版本化修订，但正式目标、权限和测量规则的改变必须经过外部治理。

### 2.4 任务分解依据什么

`PlanGraph` 不由评分项直接反向复制，而由以下信息共同产生：

1. 目标状态与初始状态之间的差异；
2. 环境和工具的因果/能力模型；
3. 动作依赖、权限和禁止事项；
4. 当前信息缺口和歧义；
5. 风险、可逆性、预算和停止条件；
6. 为形成可信交付所需的验证步骤。

通用节点类型暂定为：

```text
Observe / Interpret / Decide / Act / Verify / Recover / Communicate
```

验证步骤可以属于执行计划，但正式 `EvaluationResult` 仍由独立 Evaluation Plane 产生。执行者提供验证候选不等于拥有结算权。

## 3. 测量而不是单一打分

### 3.1 从目标属性到测量方法

设 `GoalGraph` 中一个目标属性为：

```text
“指定渠道订单已经被正确、合规地接入”
```

它可能对应多个操作化观测：

```text
代码编译和静态合同
字段映射单元测试
隔离环境中的服务集成
真实任务等价的端到端状态变化
幂等性、权限与副作用检查
最终交付说明和证据完整性
```

这些观测都不是目标本身，只是对目标的有限测量。`test_passed == true` 只证明某个测试程序在特定环境中返回成功，不自动证明完整用户目标成立。

### 3.2 多个测量视图

同一 `EpisodeGraph` 可以被不同测量视图观察：

| 视图 | 主要对象 | 典型方法 |
|---|---|---|
| 最终状态 | 数据库、文件、应用、外部对象 | state predicate、getter |
| 代码与产物 | 源码、配置、报告、模型产物 | 编译、测试、schema、静态分析 |
| 轨迹与政策 | 动作顺序、授权、确认、副作用 | 状态机、时序规则、minefield |
| 因果归因 | 动作是否导致结果 | 父事件、前后状态、重放、消融 |
| 语义与意图 | 自由文本是否真正满足用户要求 | rubric、受限 Judge、人工 |
| 成本与资源 | 时间、token、工具、监督 | CostVector |
| 可靠性与鲁棒性 | 重复与扰动后的表现 | repeated trials、stress tests |
| 认识不确定性 | 证据是否充分、一致、可追溯 | provenance、coverage、unknown |

这些视图通常有损、重叠且不可逆，更适合称为测量投影，而不是严格数学意义上的多个完整坐标系。

### 3.3 通过条件是可行域

简单总分：

\[
Score=w_rR+w_bB+w_oO+w_jJ
\]

允许高语义得分抵消安全违规，也会对相关信号重复计分。目标方案使用非补偿式判定：

\[
\mathcal{F}=\{z\mid
z_{critical}=pass,\
z_{safety}=pass,\
z_{evidence}\neq unknown,\
z_{normal}\ge\tau\}
\]

也就是：

- evaluator 无效或被污染：`invalid`；
- 关键目标或安全规则失败：`fail`；
- 关键证据不足：`unknown`；
- 确定性事实与语义 Judge 冲突：`disputed`；
- 进入可行域后，才用成本、效率和语义质量比较可行解。

### 3.4 可靠性、鲁棒性、韧性与泛化分开报告

```text
Reliability     基本相同条件下重复运行是否一致
Robustness      在合理的措辞、参数、顺序、延迟或噪声扰动下是否保持
Resilience      故障发生后是否能够检测、恢复并重新取得有效结果
Generalization  新任务、新环境或新分布下是否仍然成立
```

同条件 `pass^k` 主要测可靠性；改变输入和环境后再做 repeated trials 才进入鲁棒性；注入超时、状态漂移和工具失败主要测韧性。四者不能用一个“多跑几次”指标替代。

### 3.5 Evaluator validity 与 integrity 分开

```text
Validity
  是否真的测到了目标性质：目标是否漏项、测试覆盖是否充分、替代正确路径是否被误拒绝

Integrity
  测量过程是否完整且未被污染：grader/test 是否被篡改、证据是否伪造、版本和来源是否可信
```

防作弊和 reward hacking 主要属于 integrity，但 evaluator bug、依赖漂移、证据链断裂和运行间非预期变化也属于该层。一个未被篡改但测错对象的 evaluator 具有 integrity，不具有 validity；一个设计正确但可被 Agent 修改的 evaluator 具有潜在 validity，不具有运行时 integrity。

### 3.6 代码是测量表达语言，不是真值空间

代码具有可执行、可重复和可审计优势，适合作为一种评测视图，也适合承载统一 Evaluation IR：

```text
StatePredicate
ArtifactTest
TracePredicate
TemporalConstraint
SemanticObservation

AND / OR / NOT / SEQUENCE / HARD_GATE / AT_LEAST_K / WEIGHTED_COVERAGE
```

但不采用“所有任务都还原成代码，代码通过即现实目标完成”的前提。测试仍受 oracle problem、覆盖缺口、环境不可见、对公开规则的投机和 evaluator bug 限制。统一层统一的是测量接口、证据格式和组合语义，不是把现实真值永久压缩成代码返回值。

## 4. 相对现有 Agent 评测的定位

现有工作已经分别证明了多种方法的价值：

- [WebArena](https://arxiv.org/abs/2307.13854)、[AppWorld](https://arxiv.org/abs/2407.18901)和 [OSWorld](https://arxiv.org/abs/2404.07972)强调环境最终状态与可执行 evaluator；
- [ToolSandbox](https://arxiv.org/abs/2408.04682)以 milestone DAG 和 minefield 同时描述部分进展与禁止行为；
- [tau-bench](https://arxiv.org/abs/2406.12045)用最终数据库状态和 `pass^k` 区分偶然成功与可依赖成功；
- [AgentDojo](https://arxiv.org/abs/2406.13352)将 utility 与 security 作为正交结果轴；
- [PaperBench](https://openai.com/index/paperbench/)使用层级 rubric，并另建 JudgeEval 对 Judge 进行人工校准；
- [AgentRewardBench](https://arxiv.org/abs/2504.08942)说明规则评测和不同 Judge 都会遗漏某些有效路径或错误类型，且不存在跨环境始终最优的单一 Judge。

Biofield 当前方案中，单个组件并不新。相对优势候选在于以下组合：

1. Evaluation Plane 是独立权力层，不是另一个自由裁量 Agent；
2. 状态、规则、轨迹、语义和人工信号有证据优先级，不能相互任意补偿；
3. `unknown/disputed` 是正式状态，而非失败的异常分支；
4. evaluator 本身接受版本、重放、污染、防篡改和偏差审计；
5. 评测成本进入公共 CostVector；
6. EvaluationResult 可以进入 Residual、信用和后续经验更新，因此必须比一次性 benchmark 更严格；
7. Agent 可以提议目标或本体缺口，但不能自行批准对自己有利的测量规则。

这些目前是待验证的架构优势，不是已获得的实验优势。如果混合 Evaluation Plane 不优于更简单的 `rules_state`，保留简单基线。

## 5. 跨领域迁移候选

### 5.1 测量科学：测量对象、校准、不确定性与溯源

测量科学区分：

```text
Measurand       想测的性质
Measurement     测量过程
Indication      仪器输出
Uncertainty     测量后仍存在的不确定性
Traceability    结果如何通过不中断的比较链关联到参考
DecisionRule    如何据此作出判定
```

[NIST 对计量溯源的定义](https://www.nist.gov/metrology/metrological-traceability)强调，traceability 是测量结果的属性，不是仪器名称或一次校准天然赋予的属性。迁移到 Agent 评测后，每个正式结果应携带：

```text
claim / measurand
observed_value
measurement_method
evidence_refs
coverage
uncertainty
calibration_ref
decision_rule
evaluator_version
```

可检验预测：相对于只保存 pass/fail 的 evaluator，显式不确定性和溯源链应降低错误接受，并提高冲突定位与重放成功率。

### 5.2 心理测量：难度、区分度和自适应选题

借鉴 Item Response Theory 的有限部分：

- 任务具有难度；
- 任务对不同能力具有不同区分度；
- 平均通过率不能完整表示多维 Agent 能力；
- 可以根据当前能力不确定性选择下一项高信息任务。

不直接套用经典单维 IRT。Agent 数量少、任务数量多、能力多峰且 scaffold 与模型耦合，可能违反传统假设。近期 [Agent psychometrics](https://arxiv.org/abs/2604.00594)尝试联合任务与 Agent 特征；[对 AI 评测中 IRT 可靠性的审查](https://arxiv.org/abs/2607.15190)则指出小样本和异常能力分布会扭曲参数和排名。

首轮只研究任务难度、区分度和自适应选择，不把一个标量 latent ability 当作完整 Agent 能力。

### 5.3 软件测试：蜕变关系缓解 Oracle Problem

当无法写出完整正确答案时，仍可声明输入变换前后的不变量。软件测试中的 [Oracle Problem](https://discovery.ucl.ac.uk/id/eprint/1471263/)与[蜕变测试](https://vuir.vu.edu.au/33046/8/TSEmt.pdf)提供以下迁移：

```text
等价改写用户表述       → 实质任务结果不应变化
交换无关字段顺序       → 工具语义不应变化
幂等任务重复执行       → 不应重复产生副作用
收紧权限               → 不应通过绕过权限保持同一结果
注入一次可恢复超时     → 可增加合理重试，但最终状态应一致
替换 Agent ID/候选顺序 → 不应产生无关系统偏好
删除关键证据           → PASS 应降为 UNKNOWN
```

蜕变测试测量“在什么变化下不应该改变”，区别于只测同条件重复性的 repeated trial。

### 5.4 控制与诊断：Evaluator 作为状态观察器

任务真实完成状态往往部分不可观察。Evaluation Plane 可以被建模为通过多种传感器估计隐藏任务状态的 observer：

- 状态、测试、日志、轨迹和 Judge 是不同传感器；
- 信号冲突形成诊断 residual；
- 不可观测的关键目标不能被宣称为已完成；
- 系统可以主动选择下一项测试，提高关键状态的可观测性。

该迁移只有在产生“何时补测、补测什么”的算法和对照结果时才成立；仅把 evaluator 改叫 observer 属于叙事隐喻。

### 5.5 因果推断：从最终状态到行动归因

最终状态正确不表示结果由 Agent 的正确行动造成。候选方法：

- 动作与状态变化的因果父 ID；
- 执行前后状态和时间顺序；
- 固定初始状态下的 replay；
- 删除关键动作后的消融；
- 环境独立变化和其他执行者对照。

目标是同时报告：

```text
final_state_correctness
causal_attribution_confidence
```

### 5.6 审计与会计：声明—证据结算

Agent 的“已完成”声明不直接铸造正式信用，而产生待验证责任：

```text
CompletionClaim
  → VerificationLiability
  → independent Evidence / state / trajectory
  → accepted / rejected / unknown / disputed
  → settlement
```

可维护三类相互对照的记录：

```text
行动账：Agent 声称并执行了什么
状态账：世界实际发生了什么
证据账：系统为什么相信该状态
```

三者无法对齐时不能结算为完成。这里结算的是可追溯的认识论信用，不是能量货币，也不引入真实金融行为。

## 6. 主动、风险加权的任务测量

### 6.1 核心机制

固定评测包默认运行所有检查。候选创新是让 Evaluation Plane 根据当前证据选择下一项最有价值的测量：

\[
VOI(m)=
\frac{\mathbb{E}[\text{measurement }m\text{ 对决策损失的降低}]}{Cost(m)}
\]

候选节点压力可先使用可解释启发式，而不立即声称最优贝叶斯决策：

\[
P_i=
\frac{
Criticality_i\cdot Uncertainty_i\cdot Consequence_i\cdot Disagreement_i
}{ExpectedMeasurementCost_i}
\]

执行顺序：

```text
运行便宜的 schema / rule / state 检查
        ↓
当前证据能否安全决定？
  ├─ 能：停止并结算
  └─ 不能：定位高风险、高不确定或高冲突 Goal 节点
                  ↓
        选择预期信息价值/成本最高的下一测量
                  ↓
       集成测试、重放、蜕变测试、Judge 或人工
                  ↓
        达到判定条件，或预算耗尽后输出 UNKNOWN
```

### 6.2 与 Biofield 原始思想的有限连接

未验证目标形成“测量压力”，证据到达后压力降低，信号冲突时压力升高，评测预算优先流向高风险且高信息价值的节点。这个机制与“资源流向高残差区域”存在功能类比，但只有在相同错误率下减少成本，或相同成本下降低错误接受时，才主张具有工程价值。

不把 `P_i` 称为物理能量、膜电位或货币。若普通优先队列、固定测试序列或简单风险阈值等成本下同样有效，则保留更简单实现。

## 7. 目标合同草案

```text
TaskMeasurementBundle
  task_frame_ref
  goal_graph_version
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
  bundle_hash

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

MeasurementObservation
  measurement_id
  status
  observed_value
  evidence_refs
  provenance
  coverage
  uncertainty
  cost
  evaluator_version

EvaluationResult
  result_id
  requirement_results[]
  outcome: pass / fail / unknown / disputed / invalid
  safety_and_policy
  collateral_damage
  reliability_and_robustness
  semantic_quality
  total_measurement_cost
  evidence_trace
  causal_attribution
```

Judge 是一种 `MeasurementSpec`，不是最终结算器。多 Judge 一致只能描述稳定性；Judge 信用来自独立人工 gold、受控故障注入、扰动测试和版本化校准，不通过递归 Judge 建立。

## 8. 实验序列

### 8.1 MEAS0：固定多信号测量基线

目的：先证明独立、可重放、非补偿式 Evaluation Plane 是否优于更简单基线。

比较：

```text
self_eval
judge_only
state_only
rules_state
fixed_evaluation_plane
```

重点指标：false accept、unsafe success、false reject、unknown/disputed、成本、Judge 稳定性、测量溯源完整性和 repeated-trial reliability。

### 8.2 MEAS1：蜕变测试与主动测量

MEAS0 通过后再比较：

```text
fixed_full_suite
fixed_minimal_suite
adaptive_risk_weighted_suite
```

三组共享相同 GoalGraph、候选 MeasurementSpec、最大预算和错误注入。主动方案只改变测量选择与停止策略。

主要指标：

- 相同 false accept 上的平均评测成本；
- 相同成本下的 false accept / false reject；
- 达到稳定结论所需测量次数；
- 故障定位和信号冲突诊断；
- metamorphic mutation score；
- 预算耗尽时的 `unknown` 校准。

### 8.3 MEAS2：心理测量与因果归因

只有积累足够 Agent × task × repeated-run 数据后才启动：

- 估计任务难度和区分度；
- 比较固定任务集与自适应任务选择；
- 检查模型、scaffold、工具和环境造成的 differential performance；
- 运行关键动作消融和反事实重放；
- 区分最终状态正确与可归因的任务完成。

## 9. 当前最小研究主张

当前只允许提出以下待验证主张：

1. 多信号、非补偿式测量可能降低 Judge-only 的错误接受；
2. 任务目标、执行计划、真实 episode 和测量图分离，可能减少目标遗漏和自证循环；
3. 显式不确定性与溯源链可能提高争议定位和重放能力；
4. 蜕变关系可能在缺少完整 oracle 时提供额外错误检出；
5. 主动风险加权测量可能在相同错误率下降低评测成本；
6. 因果重放可能区分真实完成与偶然正确状态。

不允许声称：

- 已建立通用 Agent 能力标尺；
- RequirementGraph 完整表达了用户意图；
- 代码或测试空间等于现实真值空间；
- 多 Judge 投票解决了 Judge 信用问题；
- 一个动态压力公式已经构成生物机制；
- 主动测量必然优于固定测试包。

## 10. 需要继续回答的问题

1. `TaskFrame` 中哪些字段可以跨任务复用，哪些必须保持领域特定？
2. GoalGraph 与正式 RequirementGraph 的批准权如何分离而不制造过高人工成本？
3. 如何测量 MeasurementGraph 自身的覆盖率，而不是只测 evaluator 实现正确性？
4. 主动测量如何避免只选择容易通过、却忽略低概率高损失失败的测试？
5. 评测预算耗尽时，什么条件允许停止为 `unknown`，什么条件必须人工升级？
6. 如何防止动态选择 evaluator 导致不同 arm 接受了不可比较的证据？
7. 哪些任务允许因果重放，哪些任务只能保存近似归因证据？
8. 任务难度是 Agent 无关属性，还是 Agent—scaffold—环境条件下的关系量？

这些问题进入实验前必须预注册最简单基线、失败条件和允许的主张范围。
