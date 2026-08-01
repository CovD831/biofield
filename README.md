# Biofield Architecture Experiment

这是一个独立的研究项目，用于验证相近初态的 Agent 能否在受治理的 Harness 中因局部经验形成功能分化（D），在任务内形成有净收益的局部组织（O1），并使少量候选经 held-out 证据、有限容量和可撤销选择压力成为可复用、可退役的组织资产（O2）。正式工作同时包含确定性离线实验和低成本真实模型探针；项目不依赖 OpenPilot 主运行时、权限系统或 metadata 合同。

本项目于 2026-07-20 从 OpenPilot 工作区的隔离实验目录迁出。来源和 Git 边界见 [`docs/project/MIGRATION_PROVENANCE.md`](./docs/project/MIGRATION_PROVENANCE.md)。

核心命题见 [`docs/research/BIOFIELD_CORE_RESEARCH_THESIS.md`](./docs/research/BIOFIELD_CORE_RESEARCH_THESIS.md)，当前实现和证据状态见 [`docs/STATUS.md`](./docs/STATUS.md)，完整文档导航见 [`docs/README.md`](./docs/README.md)。

当前架构规格见 [`docs/architecture/ARCHITECTURE_EXPLORATION_FINAL.md`](./docs/architecture/ARCHITECTURE_EXPLORATION_FINAL.md)，版本关系见 [`docs/architecture/README.md`](./docs/architecture/README.md)。Harness 保留事实、安全、资源、准入和回滚权威，Evaluation Plane 独立管理正式测量与评测，Agent 产生 Intent/Bid/Refusal/Communication，Field 只提供非处方性的局部公共条件，不输出角色、分配或拓扑。跨任务只保存有界、可重构的 organization prior/recipe/motif 和证据，不无限保存每次完整拓扑。

能量经济、任务测量和生物启发的扩展研究见 [`docs/research/ENERGY_MEASUREMENT_BIO_RESEARCH_AGENDA_2026-07-21.md`](./docs/research/ENERGY_MEASUREMENT_BIO_RESEARCH_AGENDA_2026-07-21.md)。任务测量支线的对象模型、现有方法对照、主动测量、蜕变测试和因果评测候选另见 [`docs/research/AGENT_TASK_MEASUREMENT_RESEARCH_2026-07-21.md`](./docs/research/AGENT_TASK_MEASUREMENT_RESEARCH_2026-07-21.md)，MEAS0 的冻结设计见 [`docs/experiments/MEAS0_DESIGN_V1.md`](./docs/experiments/MEAS0_DESIGN_V1.md)。当前 canonical foundation 为 `runs/meas0/pilot/meas0-foundation-20260731-v27`：v11 run shell 调用独立的 v9 foundation runner，完成 F01–F18 × 两任务 × 五臂的 36 cases / 180 results，36/36 case 为 task-native，三次 replay hash 一致。schema-v2 lock 内嵌设计字节并绑定 29 个 source；formal runner v6 的 Price/StageBudget/StageCost、receipt ancestry、四阶段 checkpoint、可插拔 verifier/price re-derivation、exact-180 outcome sidecar、证据驱动 lifecycle 和 formal run store 已 source-bound。正式 readiness 还要求 J-CAL/J-AUDIT 各自 48×6=288 个独立 probe calls 的精确成员关系；旧 96-call corpus 只能用于离线回归。当前没有真实 production authority、Judge、formal 或 confirmatory evidence，Gate M 仍为 `FAIL`。

可直接执行的实验顺序、公共夹具、运行产物和判定门槛见 [`docs/experiments/EXPERIMENT_PROTOCOL.md`](./docs/experiments/EXPERIMENT_PROTOCOL.md)。该协议是当前架构的执行细化，不是新的架构版本。

2026-07-21 的路线调整记录见 [`docs/experiments/EXPERIMENT_ROADMAP_REVIEW_V1.md`](./docs/experiments/EXPERIMENT_ROADMAP_REVIEW_V1.md)，它不再决定当前顺序。R0-min → F0-contract → F0-model 已完成；新主线是 E0/MEAS0/LA0 → LA1 → LA2 → DIFF0 → ORG0/O1 → ORG1/O2 → SI0/SAFE0，EN0/BIO0 独立运行，不再继续扩大 A0a 或中央 allocator 探针。

v0.5.1、v0.5.2 及更早版本保留在 [`docs/architecture/history/`](./docs/architecture/history/) 作为设计演进和审计记录，不再要求实现时交叉读取。

## 当前边界

- 当前代码已实现局部观测/提案、单/多 Bid Admission、ActionAuthorization、Commitment 生命周期、Communication Permit 和局部状态/经验治理；多 Bid public resolver 只使用资源、并发、重复、dependency、exploration、risk 和 stable `bid_id` tie-break，不读取隐藏效用。统一三 scripted-agent episode 已证明：同一非处方 Field 与不同私有状态产生不同 Intent/Bid/Refusal；通信 Evidence 的 delivery/receipt/consume 会改变后续合法行为；Refusal/takeover、accepted/rejected/disputed、失败结算后重组和 checkpoint resume 均有确定性、可重放的失败/攻击纵切。LA1 §7.3/§7.5 scripted technical criteria 已达到，但由于 MEAS0 Gate M 尚未通过，正式 Gate 1 仍未激活。多 Commitment 已支持同一 resolver decision 下的全量预检、稳定排序、精确资源守恒、全成或全不成的不可变 proposal 构造与 typed replay；它尚不声称外部 ledger/event sink 的事务持久化，任意分支的生产级统一 orchestrator 仍是后续工程能力。
- 当前代码也尚未实现 OrganizationPrior、OrganizationArchive、prior retriever、probation/niche/lifecycle，因而尚无 O2 运行时能力。
- 当前代码已实现 MEAS0-S0、R1/R2 task-native evaluator 和 36×5 foundation。canonical v27 的 29-source closure 还绑定 formal runner v6：plan/auth/request 绑定 Price、StageBudget 与 pre-ledger，artifact/run 绑定 receipt 与 final ledger，ledger 是唯一 stop 权威，失败但已发生的 attempt 仍入账。readiness 现场重验 raw trust、checkpoint 和 price receipts；J-CAL/J-AUDIT 分别要求 288-call exact invocation membership 和严格 corpus provenance 隔离；生命周期只由 ledger/checkpoint/qualification 推导；formal package store 原子 write-once。当前 candidate detection 仍固定 `formal_eligible=false`。完成性审计确认：单进程 production primitive 可以注入，但完整 Pilot→confirmatory→Gate 的 production/raw-closure replay 仍有 phase readiness 顺序、confirmatory、gold/hard-gate 派生、retained-failure、checkpoint target 等缺口；当前已补上非claim evidence-derived lifecycle 的 canonical-bytes replay carrier，仍非正式证据；详见 [`results/MEAS0_COMPLETION_AUDIT_V1.md`](./results/MEAS0_COMPLETION_AUDIT_V1.md)。首轮 provider 边界与 Gate M 未通过的结论不变。
- D1–D12 已经通过 [`MEAS0 formal protocol amendment V3`](./docs/experiments/MEAS0_FORMAL_PROTOCOL_AMENDMENT_V3.md) 获准进行离线 TDD 实现。该批准不授权真实 provider、外部成本、受保护 production data、正式 Pilot/confirmatory 或 Gate M 证据。
- V3 离线实现已加入 typed checkpoint/readiness、冻结预算验证、exact-36 Pilot input/plan candidate、保护证据 vault、reviewed-Gold 结构顺序锁、retained-failure、strict typed-source restore，以及 exact-144/720 confirmatory **结构承诺及原子 write-once store**、始终 `UNKNOWN/NOT_EVALUATED` 的 Gate 诊断、typed 七文件 public slice、test-only transport membership、D11 typed authority inventory、独立的 36×5 V3 nonclaim outcome package 和 D12 self-contained source-closure candidate（source-lock/wheel/sdist/dependency-lock/environment/build metadata 的 exact-byte binding 与 canonical-bytes restore）。B8a public slice 与 evidence-derived lifecycle 现在也有要求独立 typed ancestry 的严格 canonical-bytes replay carrier。D11 将 backend `detection_signals` 永久隔离为 audit-only；formal legacy adapter 现在在入口 fail closed，尚未声称 typed-source replacement；除现有 typed evidence 可闭合的 F18 `budget_exhausted` 外，缺失权威来源的 oracle signals 均显式 `UNAVAILABLE`。全量测试、构建和隔离 wheel import smoke 已通过；详见 [`MEAS0 V3 offline implementation progress V1`](./results/MEAS0_V3_OFFLINE_IMPLEMENTATION_PROGRESS_V1.md)。这些对象仍不证明真实执行、可信时间、成本、detection 或结果，不具 production authority；D12 candidate 的 opaque bytes 不是 source-restoration verification，source-restoration、完整 raw closure、D11 typed-source replacement、confirmatory outcome、formal hard Gate 与 Gate M transition 均未闭合。
- 新 F0 使用 verifier-bound `f0.native.v2`；native replay 从 Evidence 内容/hash 和受绑定 R1 fixture 独立重算 Feedback disposition，再重演 Residual/Ledger 与四类终态。事件不暴露 hidden gold。schema migration、原子 checkpoint 持久化、并发 write-once、发布中断和缺失 settlement 攻击均已通过；E0 Gate 0 已通过。`native.v1` 和 legacy 仅兼容重放，显式不能声称 Evidence→Feedback 已复验。
- Harness 是事实、安全、权限、资源、事件和终态权威；目标架构允许 Agent 产生合法行动提案，但不允许 Agent 直接修改公共 Residual、Ledger、MeasurementSpec、evaluator 或权限。
- Equal/UCB/FieldAllocator 继续作为中央分配基线；目标 Biofield 主路径中的 Field 只生成局部观测，不直接输出完整 Allocation 矩阵。

- `dynamics.py` 中的早期向量代码定位为 `C-pre0`：不调用 LLM、网络、工具或 OpenPilot 模块，只测试 capability vectors 的分散、覆盖和数值稳定性。
- `C-pre0` 不是最终 allocator，也不能证明真实模型会分化或多 Agent 有净收益。
- 当前项目还已实现 R0 公共合同、S1/R1 夹具、R1 评分器和产物存储，带显式证据失效语义的 B0 残差状态机、D0a 资源账本，以及 C1 的 Equal/UCB/Field/privileged reference 合成对照。
- R0-min 已为 F0 实现统一运行终态/finalize、config/event/metrics schema 强制校验、逐文件 SHA-256 封存和终态后写保护；其他旧实验尚未迁移到该严格 lifecycle。D0a 已通过守恒与终止门槛，但 settlement event replay adapter 留给 E0。
- C1 当前只验证固定每 Agent 容量下的需求维度路由，不包含跨 Agent 能量预算份额 `q_i`。
- 正式 DAG 从第一批就并行运行低成本 A0 模型探针，避免在长时间离线开发后才发现模型侧假设不成立。
- A0 已接入本地 `qwen3:8b`。完整任务 T1 的回顾式 `behavior_signature` 饱和；A0a 固定顺序下观察到人工语义历史可以改变结构化候选动作选择，随后 60-call 位置与 tie-break 消融的严格稳健性门槛未通过。最新同批完整 2×2 菜单/Schema 轴定位完成 40/40 次调用：5/5 个 seed 呈 `menu_dominant`，fact-history control 20/20 跟随可见菜单第一项，conflict-history treatment 20/20 选择 cross-check；在当前 tie-off、canonical ↔ synth-first 设置中，schema enum 轴没有可见效应。四格中两个对角 cell 是相同 payload/seed 的再次调用，两个 off-diagonal cell 才是新增辨识单元；该结果不是 held-out 复现、普遍模型偏置或真实路由证据，也不能证明经验自然形成历史。
- 第一批不实现 hidden-state 通信、记忆热启动、主项目权限机制或完整 graph layer。
- 不把向量分散本身视为成功；必须同时衡量覆盖率与冗余。
- 当前 `C-pre0` 侧向抑制是显式两两计算，复杂度为 `O(N^2)`，不声称已经实现平均场近似。

## C-pre0 假设

在固定任务需求和计算周期下，侧向抑制策略应当比无抑制策略降低 Agent 间正余弦相似度，并且任务维度覆盖率下降不超过 5 个百分点。

以下任一情况出现时，当前假设视为未通过：

- 结果包含 NaN、Inf 或向量范数漂移；
- 固定随机种子不能复现结果；
- 冗余降低是以明显丢失任务覆盖为代价；
- 参数小幅变化就频繁导致坍缩或振荡；
- 后续对照实验中不能优于简单固定角色或贪心分配。

## 运行测试

从本目录运行：

```bash
python -m venv .venv
.venv/bin/python -m pip install '.[dev]'
.venv/bin/python -m pytest -q
```

项目使用自己的 `.venv`。普通单元测试不需要 Ollama、真实模型或网络。

构建 wheel 和源码包：

```bash
.venv/bin/python -m build
```

## 运行离线实验

从本目录运行；`run-id` 必须唯一，已有运行不会被静默覆盖：

```bash
RUN_ID="manual-$(date +%Y%m%d-%H%M%S)"

.venv/bin/python -m biofield.pre0 \
  --output-directory runs --run-id "$RUN_ID"

.venv/bin/python -m biofield.synthetic \
  --output-directory runs --run-id "$RUN_ID"
```

MEAS0-S0 的离线决策表回归不调用模型或网络；它只验证合同、五 arm 输入边界和融合规则：

```bash
.venv/bin/python -m biofield.meas0 \
  --output-directory runs --run-id "meas0-s0-manual"
```

该命令写出的 artifact 会显式标记 `decision_table_conformance` 和 `not_a_meas0_pilot_result`。

E0 的完整四终态 sealed source → lock → run → replay 工作流：

```bash
.venv/bin/python -m biofield.e0_run sources \
  --output-directory runs/e0-sources --source-set-id "e0-manual"

.venv/bin/python -m biofield.e0_run prepare \
  --lock-directory runs/e0-locks --lock-id "e0-lock-manual" \
  --completed runs/e0-sources/f0-contract/e0-manual-completed \
  --failed runs/e0-sources/f0-contract/e0-manual-failed \
  --budget-exhausted runs/e0-sources/f0-contract/e0-manual-budget_exhausted \
  --max-cycles runs/e0-sources/f0-contract/e0-manual-max_cycles

.venv/bin/python -m biofield.e0_run run \
  --lock runs/e0-locks/e0-lock-manual/e0.lock.json \
  --output-directory runs --run-id "e0-manual"

.venv/bin/python -m biofield.e0_run replay --run runs/e0/e0-manual
.venv/bin/python -m biofield.e0_run summarize --run runs/e0/e0-manual
```

MEAS0 v11 shell 暴露 `foundation|formal` 两种模式，但当前只有 foundation
可以成功进入运行；production formal 除缺少真实 Judge/human/preflight、签名和
独立复核证据外，CLI 本身也没有 production verifier/backend 注入与独立重放
入口。下面的 foundation 运行会明确封存
`pilot_foundation_only_not_a_formal_meas0_pilot_result`，不能作为 Gate M
或 arm 优越性证据：

```bash
.venv/bin/python -m biofield.meas0 prepare \
  --design docs/experiments/MEAS0_DESIGN_V1.md --phase pilot \
  --lock-directory runs/meas0/locks --lock-id "meas0-foundation-lock-manual"

.venv/bin/python -m biofield.meas0 run \
  --lock runs/meas0/locks/meas0-foundation-lock-manual/preregistration.lock.json \
  --output-directory runs --run-id "meas0-foundation-manual" \
  --execution-mode foundation

.venv/bin/python -m biofield.meas0 replay \
  --run runs/meas0/pilot/meas0-foundation-manual
.venv/bin/python -m biofield.meas0 summarize \
  --run runs/meas0/pilot/meas0-foundation-manual
```

LA1 scripted 技术包按场景 prepare/run/replay；它不调用真实模型，也不等于正式
Gate 1：

```bash
.venv/bin/python -m biofield.la1_artifacts prepare \
  --output-directory runs --run-id "la1-success-manual" --scenario success
.venv/bin/python -m biofield.la1_artifacts run \
  --run-directory runs/la1-scripted/la1-success-manual
.venv/bin/python -m biofield.la1_artifacts replay \
  --run-directory runs/la1-scripted/la1-success-manual
```

## 运行本地模型 Pilot

先启动 Ollama 并确认已安装 `qwen3:8b`。模型文件应放在用户级目录，不要放入仓库：

```bash
OLLAMA_MODELS="$HOME/.ollama/models" ollama serve
OLLAMA_MODELS="$HOME/.ollama/models" ollama pull qwen3:8b
```

另开终端后可运行本地模型 Pilot；每次使用新的 `run-id`。这些命令是显式的本地模型验证，不属于普通离线测试：

```bash
.venv/bin/python -m biofield.a0_t0 \
  --output-directory runs --run-id "a0-t0-manual" \
  --warmup-already-completed

.venv/bin/python -m biofield.a0_action_probe \
  --output-directory runs --run-id "a0a-manual" \
  --repeats 5 --agents agent.a

.venv/bin/python -m biofield.a0_action_bias \
  --output-directory runs --run-id "a0a-position-tie-manual" \
  --repeats 5

.venv/bin/python -m biofield.a0_action_axis \
  --output-directory runs --run-id "a0a-menu-schema-axis-manual" \
  --repeats 5

.venv/bin/python -m biofield.f0_model \
  --output-directory runs --run-id "f0-model-manual" \
  --task-id cold_chain_readiness --model qwen3:8b \
  --action-budget 4 --token-budget 50000 --max-cycles 4 \
  --inject-invalid-first
```

当前已审阅的 Gate/工程结果：

- [`results/E0_GATE0_V2.md`](./results/E0_GATE0_V2.md)（canonical v3；原始 fixture 字节闭包；仅支持确定性 Harness 因果底座的 E0 Gate 0）
- [`results/E0_GATE0_V1.md`](./results/E0_GATE0_V1.md)（历史 canonical v2；保留审计）
- [`results/MEAS0_FOUNDATION_V11.md`](./results/MEAS0_FOUNDATION_V11.md)（canonical v27；trust/cost/oracle formal integration、三次 replay hash 一致；Gate M 未通过）
- [`results/MEAS0_COMPLETION_AUDIT_V1.md`](./results/MEAS0_COMPLETION_AUDIT_V1.md)（正式链路完成性审计；记录仍需设计确认与实现的 P0 缺口）
- [`results/MEAS0_FOUNDATION_V9.md`](./results/MEAS0_FOUNDATION_V9.md)（历史 canonical v23）
- [`results/MEAS0_FOUNDATION_V8.md`](./results/MEAS0_FOUNDATION_V8.md)（历史 canonical v21）
- [`results/MEAS0_FOUNDATION_V7.md`](./results/MEAS0_FOUNDATION_V7.md)（历史 canonical v20；保留审计）
- [`results/MEAS0_FOUNDATION_V6.md`](./results/MEAS0_FOUNDATION_V6.md)（历史 canonical v19；保留审计）
- [`results/MEAS0_FOUNDATION_V5.md`](./results/MEAS0_FOUNDATION_V5.md)（历史 canonical v18；保留审计）
- [`results/MEAS0_FOUNDATION_V4.md`](./results/MEAS0_FOUNDATION_V4.md)（历史 canonical v17；保留审计）
- [`results/MEAS0_FOUNDATION_V3.md`](./results/MEAS0_FOUNDATION_V3.md)（历史 canonical v16；保留审计）
- [`results/MEAS0_FOUNDATION_V2.md`](./results/MEAS0_FOUNDATION_V2.md)（历史 canonical v14；保留审计）
- [`results/MEAS0_FOUNDATION_V1.md`](./results/MEAS0_FOUNDATION_V1.md)（历史 canonical v12；保留审计）
- [`results/LA0_CONTRACT_V1.md`](./results/LA0_CONTRACT_V1.md)（LA0 deterministic contract layer）
- [`results/LA1_SCRIPTED_TECHNICAL_V4.md`](./results/LA1_SCRIPTED_TECHNICAL_V4.md)（canonical v8、runner v5、native state provenance；正式 Gate 1 等待 Gate M）
- [`results/LA1_SCRIPTED_TECHNICAL_V3.md`](./results/LA1_SCRIPTED_TECHNICAL_V3.md)（历史 canonical v7）
- [`results/LA1_SCRIPTED_TECHNICAL_V2.md`](./results/LA1_SCRIPTED_TECHNICAL_V2.md)（历史 canonical v6）
- [`results/LA1_SCRIPTED_TECHNICAL_V1.md`](./results/LA1_SCRIPTED_TECHNICAL_V1.md)（历史 canonical v5；保留审计）

其他已完成的探索性结果：

- [`results/C_PRE0_PILOT_V1.md`](./results/C_PRE0_PILOT_V1.md)
- [`results/C1_PILOT_V2.md`](./results/C1_PILOT_V2.md)（规范结果）
- [`results/C1_PILOT_V1.md`](./results/C1_PILOT_V1.md)（仅保留审计）
- [`results/A0_T0_T1_PILOT_V1.md`](./results/A0_T0_T1_PILOT_V1.md)
- [`results/A0A_ACTION_CHOICE_PILOT_V1.md`](./results/A0A_ACTION_CHOICE_PILOT_V1.md)（规范结果）
- [`results/A0A_POSITION_TIE_ABLATION_V1.md`](./results/A0A_POSITION_TIE_ABLATION_V1.md)（位置稳健性严格门槛未通过）
- [`results/A0A_MENU_SCHEMA_AXIS_V1.md`](./results/A0A_MENU_SCHEMA_AXIS_V1.md)（同批完整 2×2 将当前顺序效应定位到可见菜单轴）
- [`results/F0_PILOT_V1.md`](./results/F0_PILOT_V1.md)（真实模型成功路径与受控失败—恢复闭环）

`runs/` 保存机器可读原始产物并被 Git 忽略；结论摘要进入 `results/`。策略表现差仍记录为有效实验结果，不记成运行失败。

当前离线测试基线以 [`docs/STATUS.md`](./docs/STATUS.md) 的最近验证为准：全量 `pytest -q` 为 `1104 passed`。E0 canonical v3 已为 Gate 0 提供 reviewed support；MEAS0 canonical v27 foundation 已封存 schema-v2 自包含 29-source lock、36/180 结果、36/36 native 与三次一致 replay hash，但正式链路完成性审计发现 production lifecycle 仍有离线协议与实现缺口，不能再表述为“只等待外部输入”；Gate M 仍未正式评估，项目状态保持 FAIL。LA1 canonical v8 已达到 §7.3/§7.5 scripted technical criteria，但正式 Gate 1 受 Gate M 依赖约束而尚未激活。工程结果不代表 D、O1/O2、Field 增量或任何科学主张已通过。

## 当前启动顺序

1. E0：已通过；维持 `f0.native.v2` replay/checkpoint Gate 回归；
2. MEAS0：canonical v27 foundation 已用 schema-v2 自包含 lock 绑定 29 个 source 和批准规则，并封存 36/180、36/36 native 与三次一致 replay hash；raw trust、receipt/StageCost、exact J-CAL/J-AUDIT invocation、artifact-derived candidate oracle、formal lifecycle 和 sealed store 已贯穿离线边界但仍只到 source-bound/contract-tested。先确认并实现 completion audit 中的 phase-specific readiness、144×5 confirmatory、gold/hard-gate 派生、retained-failure、typed checkpoint target、Gate transition 和完整 production/raw-closure replay，再落实 production trust roots、受保护 corpus、正式 provider/human/isolation/signature 输入并运行正式 Pilot/confirmatory；
3. LA0：已具备局部观测、Intent/Bid/Commitment/Refusal、通信、状态更新和 Admission 合同；
4. LA1：scripted technical criteria 已达到，多 Commitment 原子 proposal 构造已补齐；维持统一三 Agent episode、原子 proposal 与分支攻击回归，后续再补外部 sink 的事务提交，等待 Gate M 后再判断正式 Gate 1；
5. LA2：使用本地模型验证合同稳定性，不先声称组织价值；
6. DIFF0：用 state reset/swap、ID/顺序平衡和真实结果验证经验导致的功能分化；
7. ORG0：每题冷启动，运行 Single/Fixed/Central/Local-no-field/Broadcast/Local-field 等成本 O1 对照与结构消融；
8. ORG1：比较冷启动、固定阈值快照、LRU/LFU、有界 archive、per-query search 和强中央 selector，验证 O2 的准入、迁移、漂移、复活与退役；
9. SI0/SAFE0：运行 T0/T1/T2 纵向评测、prior/archive 攻击、回滚和安全非退化检查；
10. MEAS1/MEAS2：仅在 MEAS0 通过后，独立比较主动测量、蜕变测试、任务难度/区分度与因果重放，不阻塞 LA0/LA1；
11. EN0/BIO0：独立验证能量经济分层和单一生物机制，不把正结果作为主线默认前提；
12. 只有 DIFF0、ORG0、ORG1、SI0 和 SAFE0 按各自门槛通过后，才允许提出 E3/META0。
