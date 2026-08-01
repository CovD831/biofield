# Biofield 架构文档索引

## 当前架构

[Biofield 核心研究命题](../research/BIOFIELD_CORE_RESEARCH_THESIS.md) 是“为什么研究、需要证明什么”的第一权威来源；[ARCHITECTURE_EXPLORATION_FINAL.md](./ARCHITECTURE_EXPLORATION_FINAL.md) 是“系统如何分层、谁拥有什么权力”的当前唯一架构规范。2026-07-30 的收口把研究对象明确拆为 D 功能分化、O1 任务内组织和 O2 跨任务组织选择，并保持四个运行时权力/功能层：

- **Harness** 负责目标、公共事实、权限、Ledger、准入、事件、终态和回滚；
- **Evaluation Plane** 负责冻结 MeasurementSpec，并按环境状态、规则、证据和隔离 Judge 产生正式 EvaluationResult；
- **Local Agent** 根据局部观测和私有状态产生 Intent、Bid、Refusal、Communication 和状态更新提案；
- **Field** 只传播版本化的残差、拥塞、资源和风险信号，不再直接生成完整 Allocation 矩阵。

Harness 可以拒绝非法行动，但不替 Agent 产生全部合法行动。Agent 可以提出行动和局部状态变化，但不能直接修改公共事实、资源或安全边界。

O1 是每个任务内形成的临时 commitment/communication/takeover 拓扑；O2 是候选组织经过 held-out 评价、有限容量竞争、检索、漂移重认证和退役后形成的有界组织记忆。O2 保存的是可重构 prior/recipe/motif 与证据，不是每道题的完整 Agent-ID 拓扑。

当前代码已实现 verifier-bound native F0 replay、R1/R2 deterministic evaluator 纵切，以及 LA0 单/多 Bid、Action/Commitment/Communication/LocalState governance 和 OrganizationSnapshot。E0 Gate 0 已通过；LA1 §7.3/§7.5 scripted technical criteria 已有 sealed evidence，但 formal Gate 1 仍等待 MEAS0 Gate M。MEAS0 只有 foundation/contract-only 工程证据，Gate M 未通过；没有 D、O1 或 O2 科学证据。其他地基是确定性 Harness、`predefined_role` F0 和中央 allocator 基线。准确状态见[项目状态页](../STATUS.md)。

[能量经济、任务测量与生物动力学研究议程](../research/ENERGY_MEASUREMENT_BIO_RESEARCH_AGENDA_2026-07-21.md) 保留并收紧早期能量和生物启发：真实资源、可用能力、可交付权利、信用和价格不得合并成一个标量；宏观能量经济 EN0 与生物动力学 BIO0 独立验证，只有通过各自门槛才可作为主架构附加实验。

[Agent 任务测量研究](../research/AGENT_TASK_MEASUREMENT_RESEARCH_2026-07-21.md) 修正“任务分解与评测共享同一坐标系”的旧表述：TaskFrame/GoalGraph、PlanGraph、EpisodeGraph 和 MeasurementGraph 分离；MEAS0 先建立固定多信号基线，主动测量、蜕变测试、心理测量和因果重放分别作为条件后续研究。

## 架构决策记录

[BIOFIELD_LOCAL_AGENCY_REVIEW_2026-07-21.md](./BIOFIELD_LOCAL_AGENCY_REVIEW_2026-07-21.md) 复盘了架构从自分化、自组织构想逐步转向中心 Router 的过程，区分了已经解决的资源/残差/信用语义问题与需要纠正的决策权集中问题。

它的核心判断已经被当前规格采纳。该文档保留为什么改变方向的论证；当前规格定义改变后的合同和边界。

## 历史演进

以下文档保留原文件名和原始内容，仅用于追踪设计变化：

| 阶段 | 文档 | 主要变化 |
|---|---|---|
| Blueprint | [biofield_architecture_blueprint.md](./history/biofield_architecture_blueprint.md) | 自分化构想与中央 TRouter 同时存在 |
| v0.2 | [ARCHITECTURE_EXPLORATION_V0_2.md](./history/ARCHITECTURE_EXPLORATION_V0_2.md) | 把场动力学收缩为候选分配策略，离散 runtime 保留最终控制权 |
| v0.3 | [ARCHITECTURE_EXPLORATION_V0_3.md](./history/ARCHITECTURE_EXPLORATION_V0_3.md) | 拆分真实资源、任务残差、信用和动态价格，仍保留局部任务选择 |
| v0.4 | [architecture_exploration_v0_4.md](./history/architecture_exploration_v0_4.md) | 加入 Verifier 纠错、组织级失败和操作协议，中央权力扩大 |
| v0.5 | [ARCHITECTURE_EXPLORATION_V0_5.md](./history/ARCHITECTURE_EXPLORATION_V0_5.md) | 转向并行、可证伪的中央 allocator 实验 DAG |
| v0.5.1 | [ARCHITECTURE_EXPLORATION_V0_5_1.md](./history/ARCHITECTURE_EXPLORATION_V0_5_1.md) | 强化残差误差、本体不确定性、taint 和 allocator 基线 |
| v0.5.2 | [ARCHITECTURE_EXPLORATION_V0_5_2.md](./history/ARCHITECTURE_EXPLORATION_V0_5_2.md) | 冻结执行前合同、显式探索、可靠覆盖和负结果叙事 |

历史文档不是当前规范，也不因本次重设计而改写。

## 推荐阅读顺序

1. [核心研究命题](../research/BIOFIELD_CORE_RESEARCH_THESIS.md)，理解 D/O1/O2、Field 边界和有界组织记忆；
2. 当前规格的“研究问题”“权威与智能分离”“公共合同”和“当前实现事实”；
3. [实验协议](../experiments/EXPERIMENT_PROTOCOL.md)和[项目状态页](../STATUS.md)，理解实验 Gate 与现实进度；
4. 架构决策记录，理解为什么从中央 Allocation 回到局部主体性；
5. [扩展研究议程](../research/ENERGY_MEASUREMENT_BIO_RESEARCH_AGENDA_2026-07-21.md)与[任务测量研究](../research/AGENT_TASK_MEASUREMENT_RESEARCH_2026-07-21.md)，理解独立支线；
6. 只有需要追踪概念来源时，才回看路线图 v1 和历史版本；
7. 已完成实证以 [`results/`](../../results/) 为准。
