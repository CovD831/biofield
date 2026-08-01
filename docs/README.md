# Biofield 文档导航

本目录集中保存当前研究命题、架构规范、实验协议、实现状态、架构演进和项目来源。根目录 `README.md` 负责项目使用入口，`results/` 继续保存经过审阅的实验结论，原始机器产物保存在被忽略的 `runs/`。

## 当前有效文档

| 主题 | 文档 | 地位 |
|---|---|---|
| 核心研究命题 | [Biofield 核心研究命题](./research/BIOFIELD_CORE_RESEARCH_THESIS.md) | D/O1/O2、非目标和证据边界的第一权威来源 |
| 架构边界与合同 | [局部主体性当前规格](./architecture/ARCHITECTURE_EXPLORATION_FINAL.md) | 当前唯一架构规范 |
| 实现与证据状态 | [项目状态](./STATUS.md) | 当前代码、Gate 和下一步的简明账本 |
| 架构版本关系 | [架构文档索引](./architecture/README.md) | 当前阅读入口 |
| Biofield 架构决策 | [从自分化到中心 Router](./architecture/BIOFIELD_LOCAL_AGENCY_REVIEW_2026-07-21.md) | 当前重设计的决策记录 |
| 扩展研究议程 | [能量经济、任务测量与生物动力学](./research/ENERGY_MEASUREMENT_BIO_RESEARCH_AGENDA_2026-07-21.md) | 独立假设、概念边界与集成门槛 |
| 任务测量研究 | [从静态打分到主动证据获取](./research/AGENT_TASK_MEASUREMENT_RESEARCH_2026-07-21.md) | TaskFrame/多图分离、现有评测对照与 MEAS0/1/2 假设 |
| MEAS0 预注册 | [任务测量平面实验设计 V1](./experiments/MEAS0_DESIGN_V1.md) | 冻结设计；canonical v27 foundation 的 schema-v2 自包含 lock 已绑定 29 个 source 与批准规则，结果为 36/180、36/36 native、三次 replay hash 一致；formal integration 仍为 contract-only/test-only，Gate M 未通过 |
| MEAS0 formal decision record | [正式执行决策包](./experiments/MEAS0_FORMAL_DECISION_PACKET_DRAFT.md) | D1-D4 已批准用于离线实现；生产 roots/keys/corpus/budget/oracle/roles 仍待 formal lock |
| MEAS0 formal protocol amendment | [正式协议修订 V2](./experiments/MEAS0_FORMAL_PROTOCOL_AMENDMENT_V2.md) | 已批准离线实现；不授权真实调用或正式证据，生产输入仍须 formal lock |
| MEAS0 formal protocol amendment V3 | [正式协议修订 V3](./experiments/MEAS0_FORMAL_PROTOCOL_AMENDMENT_V3.md) | D1–D12 已批准用于离线 TDD 实现；不授权真实调用、外部成本、正式执行或 Gate 证据 |
| MEAS0 正式链路完成性审计 | [Completion Audit V1](../results/MEAS0_COMPLETION_AUDIT_V1.md) | 纠正“只剩外部输入”的判断；记录 phase readiness、confirmatory、gold/hard-gate、retained failure、checkpoint、Gate transition 和 fresh replay 缺口 |
| MEAS0 corrective amendment 来源草案 | [V3 Draft](./experiments/MEAS0_CORRECTIVE_AMENDMENT_V3_DRAFT.md) | 历史审议材料；其实质 §§1–13 已由规范 V3 按 hash 纳入 |
| MEAS0 fresh replay/input binding 来源草案 | [Fresh Replay Draft](./experiments/MEAS0_FRESH_REPLAY_AND_INPUT_BINDING_DRAFT.md) | 历史审议材料；其实质 §§1–11 已由规范 V3 按 hash 纳入 |
| MEAS0 TDD 实施计划 | [Implementation TDD Plan V1](./experiments/MEAS0_IMPLEMENTATION_TDD_PLAN_V1.md) | 实施规划；按 B0–B10b 依赖分批开发、迁移、reseal 与验证 |
| MEAS0 V3 批准清单 | [Approval Checklist](./experiments/MEAS0_V3_APPROVAL_CHECKLIST.md) | D1–D12 的批准 provenance 与简明索引；规范文本以 V3 amendment 为准 |
| MEAS0 D12 source restoration | [D12 Source-Restoration Selection](./experiments/MEAS0_D12_SOURCE_RESTORATION_SELECTION_2026-08-01.md) | 已选择自包含 source archive/wheel/sdist/dependency closure；sealed artifacts 与正式 authority 尚未提供 |
| MEAS0 V3 离线实现进展 | [Offline Implementation Progress V1](../results/MEAS0_V3_OFFLINE_IMPLEMENTATION_PROGRESS_V1.md) | B1–B4 基础、冻结预算/Gold 结构顺序锁/failure variants、B5 exact-144/720 commitment package（含 typed-source canonical-bytes restore）、B6/B7/B8a/B9 部分离线结构层（transport reverification 也支持 typed canonical-bytes restore）、D11 typed-authority inventory（含 `judge_transport_membership_authority_valid=UNAVAILABLE` 与 `legacy_formal_detection_authority_valid=UNAVAILABLE`）和独立 36×5 V3 nonclaim outcome package；B8a public/protected carriers 与 composite membership carrier 均支持要求 typed ancestry 的严格 canonical-bytes replay carrier，但仍不提供 raw closure/source restoration/fresh replay/正式 authority；D12 self-contained source-closure candidate 支持 canonical-bytes restore；raw detection signals 仅为 audit；仍非真实执行、可信时间、成本、detection、结果或正式证据 |
| 实验合同、顺序与门槛 | [局部主体性实验协议](./experiments/EXPERIMENT_PROTOCOL.md) | 当前唯一实验执行细则 |
| 2026-07-21 路线决策 | [局部主体性路线图 v1](./experiments/EXPERIMENT_ROADMAP_REVIEW_V1.md) | 支持性决策记录；当前顺序已由 2026-07-30 协议取代 |
| 项目来源 | [迁移来源记录](./project/MIGRATION_PROVENANCE.md) | 审计记录 |
| E0 reviewed result | [E0 deterministic public replay Gate 0 V2](../results/E0_GATE0_V2.md) | canonical v3；原始 fixture 字节闭包；仅支持确定性 Harness 因果底座 |
| E0 historical result | [E0 deterministic public replay Gate 0 V1](../results/E0_GATE0_V1.md) | 历史 canonical v2；保留审计 |
| MEAS0 reviewed result | [MEAS0 foundation engineering V11](../results/MEAS0_FOUNDATION_V11.md) | canonical v27；trust receipt、Judge StageCost 与 artifact-derived oracle 全链仍 fail closed；36/180、三次 replay hash 一致；Gate M 未通过 |
| MEAS0 historical result | [MEAS0 foundation engineering V9](../results/MEAS0_FOUNDATION_V9.md) | 历史 canonical v23；保留审计 |
| MEAS0 historical result | [MEAS0 foundation engineering V8](../results/MEAS0_FOUNDATION_V8.md) | 历史 canonical v21；保留审计 |
| MEAS0 historical result | [MEAS0 foundation engineering V7](../results/MEAS0_FOUNDATION_V7.md) | 历史 canonical v20；保留审计 |
| MEAS0 historical result | [MEAS0 foundation engineering V6](../results/MEAS0_FOUNDATION_V6.md) | 历史 canonical v19；保留审计 |
| MEAS0 historical result | [MEAS0 foundation engineering V5](../results/MEAS0_FOUNDATION_V5.md) | 历史 canonical v18；保留审计 |
| MEAS0 historical result | [MEAS0 foundation engineering V4](../results/MEAS0_FOUNDATION_V4.md) | 历史 canonical v17；保留审计 |
| MEAS0 historical result | [MEAS0 foundation engineering V3](../results/MEAS0_FOUNDATION_V3.md) | 历史 canonical v16；保留审计 |
| MEAS0 historical result | [MEAS0 foundation engineering V2](../results/MEAS0_FOUNDATION_V2.md) | 历史 canonical v14；保留审计 |
| MEAS0 historical result | [MEAS0 foundation engineering V1](../results/MEAS0_FOUNDATION_V1.md) | 历史 canonical v12；保留审计 |
| LA0 reviewed result | [LA0 local-agency contract layer](../results/LA0_CONTRACT_V1.md) | deterministic offline contract criteria |
| LA1 reviewed result | [LA1 scripted local-agency technical result V4](../results/LA1_SCRIPTED_TECHNICAL_V4.md) | canonical v8、runner v5、native state provenance；正式 Gate 1 等待 Gate M |
| LA1 historical result | [LA1 scripted local-agency technical result V3](../results/LA1_SCRIPTED_TECHNICAL_V3.md) | 历史 canonical v7；保留审计 |
| LA1 historical result | [LA1 scripted local-agency technical result V2](../results/LA1_SCRIPTED_TECHNICAL_V2.md) | 历史 canonical v6；保留审计 |
| LA1 historical result | [LA1 scripted local-agency technical result V1](../results/LA1_SCRIPTED_TECHNICAL_V1.md) | 历史 canonical v5；保留审计 |
| 其他已完成实验 | [`results/`](../results/) | 已审阅结论与探索性结果索引 |

## 权威顺序

发生冲突时按以下顺序理解：

1. 核心研究命题决定研究对象、D/O1/O2 定义、非目标和主张边界；
2. 当前架构规格决定系统分层、权力边界和运行时合同；
3. 实验协议决定当前顺序、处理变量、产物和通过门槛；
4. 项目状态页汇总当前代码事实和 Gate，但不覆盖 sealed result；
5. 扩展研究议程和任务测量研究定义独立假设和集成条件，不覆盖核心命题或架构权力边界；
6. `results/` 记录已经获得的证据，不把 Pilot 自动升级成架构结论；
7. 路线图 v1、架构决策记录和 `architecture/history/` 解释思路如何演进，不作为当前执行优先级。

## 维护规则

- 行为、合同或 Gate 状态变化时，同步检查根目录 `README.md`、核心研究命题、当前架构规格、实验协议和状态页。
- 历史架构版本与已完成结果是审计记录，不为统一措辞而重写。
- 新实验结论进入 `results/`，原始输出进入 `runs/`。
- 新的架构讨论优先更新上述权威文档，并转化为测试、实验配置、限制或主张状态；不再为每次讨论新增一个并列“当前版本”。
- 必须区分“当前代码事实”和“目标架构”；可以精确描述已实现合同和工程 Gate，但不得把 LA1 Gate 1 写成真实模型能力、组织净收益或自组织科学结论。
- 更严格地说，当前 LA1 只达到 scripted technical criteria；在 MEAS0 Gate M 通过前，不写成正式 Gate 1 已激活。
- MEAS0 canonical v27 foundation 已用 schema-v2 自包含 lock 绑定 29 个 source，并封存 36/180、36/36 native 与三次一致 replay hash。Formal runner v6 的 Price/StageBudget/pre-final StageCost ledger、receipt→artifact→ledger 交叉绑定、四阶段 authorization checkpoint、exact-180 outcome sidecar、288-call exact invocation、证据驱动 lifecycle 和 write-once formal store 已进入 source closure。旧 96-call corpus 只能用于离线回归；production oracle/readiness 回放会保存 raw authorization 并要求外部 verifier 现场重验，runner/outcome/store 从证据类别派生资格。当前没有真实 roots、keys、verifier backend、受保护 corpus、价格/预算批准或正式 oracle，candidate evidence 仍为 `test_only/formal_eligible=false`。这里的绑定不表示 v27 产生了真实 Judge、formal/confirmatory evidence或 arm 效果；Gate M 仍为 `FAIL`。
- 必须区分 D 功能分化、O1 任务内组织和 O2 跨任务组织选择；任何一层的正结果都不自动证明下一层。
- 能量经济、任务测量和生物动力学分轨记录；任务测量还必须区分 GoalGraph、PlanGraph、EpisodeGraph 和 MeasurementGraph。未经各自门槛，不把功能类比写成已实现机制或统一理论。
