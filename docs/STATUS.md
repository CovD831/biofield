# Biofield 项目状态

日期：2026-07-31

状态：**current implementation and evidence ledger**

本页只回答“代码现在有什么、证据支持什么、下一步做什么”。研究目标见[核心研究命题](./research/BIOFIELD_CORE_RESEARCH_THESIS.md)，目标系统边界见[当前架构规格](./architecture/ARCHITECTURE_EXPLORATION_FINAL.md)，实验细节见[实验协议](./experiments/EXPERIMENT_PROTOCOL.md)。历史结果仍以 [`results/`](../results/) 中的审阅报告为准。

## 1. 当前阶段

项目已经完成旧主线的确定性 Harness 地基、中央 allocator 基线、真实模型合同探针和 F0 闭环。新主线中，E0 Gate 0 已由 canonical v3 sealed run 和审阅报告支持；LA0 已补齐 decision/commitment ancestry；LA1 canonical v8 / runner v5 已满足 scripted 技术条件并补齐 governance native state provenance，但正式 Gate 1 仍等待 Gate M。MEAS0 当前 reviewed canonical foundation 为 `runs/meas0/pilot/meas0-foundation-20260731-v27`：v11 run shell + v9 foundation runner 产生 36 cases / 180 results，36/36 task-native，三次 replay hash 一致；v27 schema-v2 自包含 lock 绑定 29 个 source。Formal runner v6 已贯穿 Price/StageBudget/StageCost、transport receipt、四阶段授权 checkpoint、exact-180 outcome sidecar、288-call invocation membership、证据驱动 lifecycle 和 write-once formal store；当前没有真实 backend/root/key/receipt、受保护 corpus、正式 oracle、真实 Judge、formal 或 confirmatory evidence，Gate M 继续为 `FAIL`。

项目尚未进入真实模型功能分化或组织收益的实证阶段。当前最准确的阶段描述是：

> **研究命题已经收敛，E0 Gate 0 已通过；LA1 scripted 技术条件已满足但正式 Gate 1 等待 Gate M；MEAS0 foundation 工程已封存但 Gate M 未通过，D、O1、O2 三个核心科学主张均待实验。**

### 已批准且已有离线合同、但尚未正式执行的 MEAS0 配置

- 两个主 provider：Codex/ChatGPT-auth Subject 与只位于外置 Evaluation Plane 的 DeepSeek V4 Pro Judge；第三 provider 仅 shadow/fallback；
- subscription-backed Subject 可先做 exploratory run；formal 必须满足全部 readiness，并明确黑盒服务不能保证 provider-side generation replay，正式 replay 主张只覆盖 sealed Subject artifact 之后的评测；
- DeepSeek V4 Pro thinking 模式记录 `temperature=ignored`、`effective_seed=unsupported`，仍必须通过 J-CAL，confirmatory 前必须通过 J-AUDIT；
- 只向 provider 发送经 hash-bound attestation 声明为去标识、非敏感的内容；代码不自动判断内容，attestation 也不是信任根；
- 用户是签名 authority，独立 reviewer 审 gold/preflight；签名 metadata 不是信任根；
- paired cluster bootstrap：cluster 为同一 seed 的完整五臂结果，各 `task_id × fault_id` stratum 内四取四有放回，保持 paired；seed `9511`、10,000 replicates、percentile 双侧 95% 和预注册方向单侧 95%，不使用 BCa。

以上规则已有离线合同与聚焦测试，不是正式实验进度。Production readiness
仍未满足；上述规则已由 v27 foundation lock 做 source binding，但正式
comparison lock、真实外部证据和 formal/confirmatory run 仍须后续完成。
正式执行决策与仍缺失的生产输入集中记录在
[`MEAS0_FORMAL_DECISION_PACKET_DRAFT.md`](./experiments/MEAS0_FORMAL_DECISION_PACKET_DRAFT.md)，
批准后的规范性离线实现规则见
[`MEAS0_FORMAL_PROTOCOL_AMENDMENT_V2.md`](./experiments/MEAS0_FORMAL_PROTOCOL_AMENDMENT_V2.md)
和
[`MEAS0_FORMAL_PROTOCOL_AMENDMENT_V3.md`](./experiments/MEAS0_FORMAL_PROTOCOL_AMENDMENT_V3.md)。
完成性审计发现 V2 的 required order 与当前 all-at-once readiness 实现冲突，
并确认 confirmatory、Gold/hard-gate 派生、失败分母和 fresh replay 尚未闭合；
待确认的非规范方案见
[`MEAS0_CORRECTIVE_AMENDMENT_V3_DRAFT.md`](./experiments/MEAS0_CORRECTIVE_AMENDMENT_V3_DRAFT.md)、
[`MEAS0_FRESH_REPLAY_AND_INPUT_BINDING_DRAFT.md`](./experiments/MEAS0_FRESH_REPLAY_AND_INPUT_BINDING_DRAFT.md)
和
[`MEAS0_IMPLEMENTATION_TDD_PLAN_V1.md`](./experiments/MEAS0_IMPLEMENTATION_TDD_PLAN_V1.md)。
项目所有者已批准 D1–D12 用于离线实现；批准摘要见
[`MEAS0_V3_APPROVAL_CHECKLIST.md`](./experiments/MEAS0_V3_APPROVAL_CHECKLIST.md)。
来源草案本身仍是审议材料，其实质要求由 V3 amendment 按 hash 纳入。
以上文档均不授权真实 provider 调用；实际 roots、keys、受保护 corpus、价格、
预算、签署角色与正式 oracle 仍必须进入后续 formal lock。

## 2. 已实现的代码事实

| 能力 | 当前实现 | 能说什么 | 不能说什么 |
|---|---|---|---|
| R0 contracts / artifacts | 版本化合同、运行终态、schema 校验、SHA-256 封存、终态后写保护 | 运行产物可以受控保存和审计 | 事件流已经完整可重放 |
| B0 Residual | Evidence/Feedback 驱动的确定性残差状态机和失效语义 | 反馈可以产生可追溯公共状态变化 | Agent 已自主形成组织 |
| D0a Ledger | grant/reserve/spend/return/settlement、守恒与幂等 | 资源结算合同可离线验证 | Agent 已自主决定资源制度 |
| C-pre0 | capability vector 分散、覆盖和稳定性实验 | 可诊断一个离线向量机制 | 真实模型已功能分化 |
| C1 | Equal/UCB/Field/privileged reference 合成 allocator 对照 | 有中央策略实验基线 | 当前 Field 具有局部非处方性价值 |
| A0/A0a | 本地模型结构化合同、位置/tie/menu/schema 偏差探针 | 已知模型可用边界和重要混杂因素 | 人工 history 是稳健经验路由 |
| F0 | `predefined_role` 的 action→evidence→feedback→residual→settlement 闭环 | 真实模型闭环和受控失败—恢复可运行 | 多 Agent、自组织、Field 增量或自改进成立 |
| E0 公共重放 | verifier-bound native v2、Evidence→Feedback 复评、Residual/Ledger/四终态、migration、原子 checkpoint、攻击回归、canonical v3 evidence package 与原始 fixture 字节闭包 | 当前 native F0 可从冻结 verifier 与 primitive events 重建 sealed hash；Gate 0 通过 | legacy/v1 也具有不存在的 verifier binding，或 E0 证明模型/组织能力 |
| MEAS0 v11 shell / v9 foundation runner / formal runner v6 | 36×5 foundation；formal Price/StageBudget/StageCost 与 receipt ancestry；四 checkpoint；exact-180 outcome；J-CAL/J-AUDIT exact invocation；lifecycle；sealed store | 离线 foundation 可重放；production raw evidence 回放必须由外部 verifier 重验；runner/outcome/store 从证据类派生资格；candidate 不可进入正式指标 | production authority、真实价格/调用、正式 Pilot、arm 优势、外部信任根或 Gate M 已通过 |
| LA0/LA1 | 单/多 Bid 治理、统一三 Agent episode、通信行为变化、Refusal/takeover、accepted/rejected/disputed、资源/非法准入、失败重组和 checkpoint | scripted 局部主体合同的十场景和失败路径工程可行；§7 技术条件满足 | 正式 Gate 1 已激活，或真实模型、组织净收益、并行拓扑、多 Commitment 原子物化成立 |

实现边界以 `src/biofield/` 和测试为准；旧的 `FieldAllocator` 是中央基线，不是目标架构中的局部 Field。

## 3. 当前实验 Gate

| Gate | 状态 | 已有证据 | 主要缺口 |
|---|---|---|---|
| E0 公共事件重放 | **通过**（仅 `f0.native.v2`） | canonical `runs/e0/e0-20260731-v3`、四终态 verifier/primitive replay、checkpoint 等价、完整 source closure、封存与攻击回归；见 [`E0_GATE0_V2.md`](../results/E0_GATE0_V2.md) | legacy/v1 保持降级兼容；不外推模型或组织能力 |
| MEAS0 独立测量平面 | foundation engineering 与 V3 offline typed contracts 支持；**Gate M 未正式评估，项目状态保持 FAIL** | canonical v27 历史 artifact 保持不变；V3 已新增 B1–B4 基础、冻结预算验证、Gold 结构顺序锁、response-bound malformed/budget/protocol failure evidence、B5 exact-144/720 结构承诺及原子 store（含 canonical-bytes restore，仍要求 typed ancestry）、B6/B7 `UNKNOWN/NOT_EVALUATED` Gate 诊断、B8a typed 七文件 public slice（现有严格 canonical-bytes carrier 仍要求 typed Pilot/protected sources 与外部 closure hash），并新增 protected-only raw payload bundle candidate（绑定 typed vault membership、manifest/reference-index hash 和 exact test bytes，canonical restore 仍不提供 replay/authority）、public/protected 两侧的 composite membership carrier（仅绑定 package、common ancestry 与 carrier hashes，仍不提供 raw closure、source restoration、fresh replay 或正式 authority）、B9 test-only transport membership、D11 typed-authority inventory 与独立 36×5 V3 nonclaim outcome package；raw `detection_signals` 仅进入 audit-only 类型，缺失 authority 的 signal 显式 `UNAVAILABLE`；D11 结构清单还明确 `judge_transport_membership_authority_valid=UNAVAILABLE`（当前没有独立 production transport verifier/trust root）以及 `legacy_formal_detection_authority_valid=UNAVAILABLE`（formal legacy adapter 现已在入口 fail closed，仍尚未集成 typed-source replacement）；D12 已选定 source archive + wheel/sdist + dependency-lock/artifact + environment/build-metadata 的 self-contained closure，现有 candidate 支持 strict canonical-bytes restore，但真实 sealed artifacts、独立验证 handoff、fresh replay 与 source-restoration authority 仍缺失，且 opaque bytes 仅是 commitments；evidence-derived 四阶段 lifecycle 现有严格 canonical-bytes replay carrier，会对 typed checkpoint/ledger/authorization/qualification 重新推导 transition，但不产生 production evidence；成本和 outcome 均未验证；见 [`MEAS0_V3_OFFLINE_IMPLEMENTATION_PROGRESS_V1.md`](../results/MEAS0_V3_OFFLINE_IMPLEMENTATION_PROGRESS_V1.md) | 仍缺可信 Gold time/signature authority、authority-bound backend descriptor、D11 typed-source replacement 及多数 F01–F18 protected sources、legacy claim-bearing migration、真实 144×5 execution/outcome、生产 transport/cost verifier、完整 raw store/source closure、authority-bound seal、hard Gate 与 Gate transition；D12 source-restoration mechanism 已选择，但 exact sealed artifacts 与独立 verification handoff 仍未提供 |
| LA0 局部主体合同 | **通过**（作为 Gate 1 的合同层） | 单/多 Bid、OrganizationSnapshot、Action/Commitment/Communication/LocalState governance、AdmissionDecision round-trip、公共状态脱敏和权限 replay；多 Commitment 原子 proposal 在 LA1 工程层完成；见 [`LA0_CONTRACT_V1.md`](../results/LA0_CONTRACT_V1.md) | 外部 ledger/event sink 的事务持久化、任意生产分支的统一 orchestrator 与跨批次事务仍是后续并发组织增强 |
| LA1 scripted loop | **§7 技术条件满足；正式 Gate 1 等待 Gate M** | canonical success/agent-action-failure-recovery/governance v8 runs；runner v5 / metrics v2；两条 native state update provenance 2/2；十场景、checkpoint、治理路径和 CostVector；同一 multi-admission decision 的多 Commitment 支持全量预检、全成或全不成的不可变 proposal 构造、精确资源守恒与 typed replay；见 [`LA1_SCRIPTED_TECHNICAL_V4.md`](../results/LA1_SCRIPTED_TECHNICAL_V4.md) | Gate M 依赖未满足；proposal 不等于外部 sink 已原子提交；只证明 deterministic offline/scripted engineering，不证明真实模型、O1/O2 或生产级任意分支 orchestrator |
| LA2 真实模型合同 | 未开始 | A0/A0a 提供偏差边界 | 局部状态输入下的稳定合法输出 |
| DIFF0 功能分化 | 未开始 | A0a 只能作为反例/混杂证据 | state reset/swap、ID/顺序平衡、真实结果增量 |
| ORG0 / O1 | 未开始 | Fixed/Central/Single 基线部分存在 | Local/no-field/broadcast/Field 等成本对照和结构消融 |
| ORG1 / O2 | 未开始 | 只有设计 | 有界 archive、准入、迁移后验、生命周期、drift/recurrence |
| SI0 / E2 | 未开始 | 无纵向序列证据 | held-out gain、retention、plasticity、efficiency、归因 |
| SAFE0 | 未开始 | 现有合同有局部 fail-closed 测试 | 局部状态、组织 prior、archive 和 retriever 攻击 |
| EN0 / BIO0 | 未开始 | 早期数值代码和概念议程 | 独立预注册与单机制对照 |

## 4. 当前主张登记

可以主张：

- 项目具有可测试的确定性 Harness、资源账本、残差和 artifact 地基；
- 本地模型可以参与受约束的 F0 闭环；
- 已识别并量化部分位置、菜单和 tie-break 混杂；
- MEAS0 canonical v27 foundation 已封存 schema-v2 自包含 29-source lock、execution ancestry、raw trust re-verification、Judge/StageCost ancestry、288-call exact invocation、独立 J-AUDIT、formal lifecycle/store primitives 与 artifact-derived detection、36/180、36/36 task-native及三次一致 replay hash；当前 package 仍是 candidate。production 单进程 primitive 可注入，但完整 serialized Pilot→confirmatory→Gate lifecycle 尚未结构可达。
- V3 D1–D12 的离线 TDD 已完成 B1–B4 基础、冻结预算、Gold 结构顺序锁和可由现有 typed authority 支持的 failure variants，并推进 B5/B6/B7/B8a/B9 的非权威结构切片及 D11 authority inventory：confirmatory 仍仅为 144×5 commitment，但已有 exact-prefix resume、canonical-bytes typed-source restore 与 cooperative-process 原子 write-once store；Gate 仅为 `UNKNOWN/NOT_EVALUATED` 诊断，public closure 仅闭合七个 typed 文件且已有严格 bytes carrier，transport 仅验证 membership 且 `cost_verified=false`；evidence-derived lifecycle 也已有要求独立 typed ancestry 的 canonical-bytes replay boundary；backend raw detection signals 与 typed projection 已在新 API 隔离，但尚未替换 legacy formal derive，并由 `legacy_formal_detection_authority_valid=UNAVAILABLE` 显式标记。E0/LA1 replay 也拒绝 symlinked run-directory alias。它们全部固定为 `simulated_nonclaim/test_only`；没有改变 canonical v27 历史结果、Gate M 或任何科学结论。
- LA1 §7.3/§7.5 scripted engineering 技术条件已满足；正式 Gate 1 仍等待 Gate M。

目前不能主张：

- 局部经验已经导致细胞式功能分化；
- Field 已经指导分化或具有独立增量；
- Agent 已经在无中央拓扑编排下形成有净收益的 O1；
- 组织已经经过筛选形成可泛化、有界的 O2；
- 系统、模型、Harness 或评测器已经自进化；
- Biofield 已优于单 Agent、固定编排或强中央 task-adaptive selector。

## 5. 当前执行顺序

```text
E0 + MEAS0 + LA0
        ↓
       LA1
        ↓
       LA2
        ↓
      DIFF0
        ↓
       ORG0 / O1
        ↓
       ORG1 / O2
        ↓
   SI0 + SAFE0
```

EN0、BIO0 和 MEAS1/MEAS2 保持独立支线，不阻塞主线。E3 组织生成器/检索策略自修改和 E4 Harness/meta 更新不在当前承诺内。

## 6. 最近验证

- 全量离线测试验证为 `1104 passed`（2026-07-31）；MEAS0 子集为 `653 passed`；本轮新增/修改文件的 Ruff lint、format 与 `git diff --check` 通过（仓库其余历史文件仍有既存 format drift）；
- wheel 与 source distribution 已成功构建；wheel 在仓库外 virtualenv 安装后，MEAS0 formal runner v6、trust/checkpoint/price、outcome evidence store、LA1 runner v5 与包内 fixtures 均可导入；
- 仓库外安装验证使用已安装 wheel 路径而非源码 checkout；该轮构建和安装验证未被写入 canonical run seal；
- 当前源码工作区中的 canonical E0 v3 replay 为四终态 `verified=true`，canonical LA1 v8 三场景 replay 哈希与 reviewed 结果一致；E0/LA1 replay 现在先拒绝 symlinked run-directory alias；MEAS0 v27 仍保存其历史 `36 cases / 180 results`、36/36 native 和三次一致 replay 记录，但当前 checkout 因 `meas0_formal_lifecycle.py` source drift 按 lock 正确拒绝 replay，未绕过或重封；
- `native.v2` 的 Evidence→Feedback→Residual/Ledger 在四类终态与 sealed hash 一致；
- R2 channel-order、MEAS foundation v9 decision closure、v11 pre-create formal guard、36/36 task-native、Judge/human/preflight/formal metrics/formal runner 合同，以及统一三 Agent Gate episode、OrganizationSnapshot 和 multi-Bid resolver 均有离线失败/篡改/顺序置换回归；
- MEAS0 N=36/五臂运行仍明确标记为 foundation，不是正式 Pilot；
- E0 规范结论见 [`E0_GATE0_V2.md`](../results/E0_GATE0_V2.md)；
- [`E0_GATE0_V1.md`](../results/E0_GATE0_V1.md) 保留为历史审计；
- MEAS0 foundation 当前规范结论见 [`MEAS0_FOUNDATION_V11.md`](../results/MEAS0_FOUNDATION_V11.md)；[`MEAS0_FOUNDATION_V10.md`](../results/MEAS0_FOUNDATION_V10.md)、[`MEAS0_FOUNDATION_V9.md`](../results/MEAS0_FOUNDATION_V9.md)、[`MEAS0_FOUNDATION_V8.md`](../results/MEAS0_FOUNDATION_V8.md)、[`MEAS0_FOUNDATION_V7.md`](../results/MEAS0_FOUNDATION_V7.md)、[`MEAS0_FOUNDATION_V6.md`](../results/MEAS0_FOUNDATION_V6.md)、[`MEAS0_FOUNDATION_V5.md`](../results/MEAS0_FOUNDATION_V5.md)、[`MEAS0_FOUNDATION_V4.md`](../results/MEAS0_FOUNDATION_V4.md)、[`MEAS0_FOUNDATION_V3.md`](../results/MEAS0_FOUNDATION_V3.md)、[`MEAS0_FOUNDATION_V2.md`](../results/MEAS0_FOUNDATION_V2.md) 与 [`MEAS0_FOUNDATION_V1.md`](../results/MEAS0_FOUNDATION_V1.md) 保留为历史审计；
- MEAS0 正式链路完成性审计见 [`MEAS0_COMPLETION_AUDIT_V1.md`](../results/MEAS0_COMPLETION_AUDIT_V1.md)；它不改变 v27 foundation 机器结果，只纠正“仅剩外部输入”的完成性判断；
- LA1 scripted 技术结论见 [`LA1_SCRIPTED_TECHNICAL_V4.md`](../results/LA1_SCRIPTED_TECHNICAL_V4.md)；[`LA1_SCRIPTED_TECHNICAL_V3.md`](../results/LA1_SCRIPTED_TECHNICAL_V3.md)、[`LA1_SCRIPTED_TECHNICAL_V2.md`](../results/LA1_SCRIPTED_TECHNICAL_V2.md) 与 [`LA1_SCRIPTED_TECHNICAL_V1.md`](../results/LA1_SCRIPTED_TECHNICAL_V1.md) 保留为历史审计；
- LA0 合同层结论见 [`LA0_CONTRACT_V1.md`](../results/LA0_CONTRACT_V1.md)；[`LA1_SCRIPTED_TECHNICAL_V1.md`](../results/LA1_SCRIPTED_TECHNICAL_V1.md) 保留为历史审计；
- F0 规范结果见 [`F0_PILOT_V1.md`](../results/F0_PILOT_V1.md)；
- A0a 的位置与菜单混杂见 [`A0A_POSITION_TIE_ABLATION_V1.md`](../results/A0A_POSITION_TIE_ABLATION_V1.md) 和 [`A0A_MENU_SCHEMA_AXIS_V1.md`](../results/A0A_MENU_SCHEMA_AXIS_V1.md)；
- C1 规范结果见 [`C1_PILOT_V2.md`](../results/C1_PILOT_V2.md)。

文档更新不改变上述实验结果。只有新的 sealed run 和审阅报告才能改变 Gate 状态。

## 7. 状态维护规则

- 代码或正式实验状态变化时更新本页，不把目标设计写成已实现能力；
- 每个 Gate 只依据其预注册证据升级，不从下游结果反推上游已经通过；
- 原始机器输出进入 `runs/`，审阅结论进入 `results/`；
- 历史架构和结果不为统一措辞而重写；
- 若状态页与代码或 sealed result 冲突，以代码、机器产物和审阅结果为事实来源，并修正本页。
