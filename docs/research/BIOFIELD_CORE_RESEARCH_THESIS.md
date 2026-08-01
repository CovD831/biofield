# Biofield 核心研究命题

状态：**normative research thesis**

日期：2026-07-30

本文冻结 Biofield 当前要回答的核心研究问题、概念边界、组织记忆方向和最低证据要求。它是研究主张的第一权威来源，但不是当前代码能力声明，也不替代具体合同、实验样本和数值门槛。

系统权力和运行时合同以[当前架构规格](../architecture/ARCHITECTURE_EXPLORATION_FINAL.md)为准；实验执行以[实验协议](../experiments/EXPERIMENT_PROTOCOL.md)为准；实现和证据状态以[项目状态页](../STATUS.md)为准。

本文不改写历史架构版本和已完成结果。它收敛并取代当前文档体系中对以下问题的重复或冲突表述：

- Biofield 的核心究竟是中央 allocator、即时动态拓扑，还是长期组织形成；
- Field 是否可以直接产生 Agent 分配或通信拓扑；
- 历史组织应保存完整快照、固定模块，还是可重构先验；
- 任务匹配器是否拥有最终组织决定权；
- 组织保留与 Harness 自进化是否属于同一层级。

---

## 1. 一句话核心命题

> 在 Harness 保留事实、安全、资源、准入和最终提交权的条件下，相近初态的 Agent 能否因不同局部经验形成可因果验证的功能分化，通过局部互动产生组织，并使其中少量组织在有限容量、独立 held-out 证据和可撤销选择压力下成为可匹配、可复用、可退役的组织资产，从而在等成本条件下获得持续净收益？

这个命题包含四个不可相互替代的部分：

1. **局部分化**：差异来自局部经验和状态，而不是预写角色、Agent ID、菜单位置或中央分配；
2. **任务内组织**：Agent 自己产生 Intent、Bid、Refusal 和通信关系，形成实际任务拓扑；
3. **跨任务选择保留**：候选组织经过独立评价、复验、竞争、冷却和淘汰，形成有界组织记忆；
4. **净价值与可逆性**：收益在全部协调成本计入后成立，并能在不适用或环境变化时退回冷启动、重新分化或回滚。

## 2. 三个必须分开的研究对象

### 2.1 D：功能分化

功能分化是：

```text
相近初态
  → 不同局部经历
  → 不同私有状态
  → 不同选择和行为
  → 稳定但可逆的条件转换能力
```

分化不能用自报角色名称、向量距离或一次不同选择单独证明。最低证据包括：

- state reset 后差异减弱或消失；
- state swap 后行为差异随状态而不是 Agent ID 迁移；
- 候选顺序、菜单、标签和 Agent ID 置换后方向保持；
- 差异出现在实际动作、工具成功谱、Bid/Refusal、证据质量和成本上；
- 在新任务、资源变化或失败恢复后仍能调整，而不是永久锁定。

通过上述门槛后，才允许使用“功能生态位”或“分化”。

### 2.2 O1：任务内即时组织

O1 是单个 episode 内形成的临时分工、承诺和通信拓扑。它回答：

- Agent 能否在没有中央生成具体 Intent 的情况下覆盖任务需求；
- 通信边能否由证据供给、信息需求和局部选择形成；
- Refusal、冲突投标、失败接管和资源不足能否改变后续组织；
- 临时结构是否比固定工作流或中央分配产生可归因的不同结果。

O1 可以每个任务结束后完全消失。它证明局部协调或即时自组织，不证明长期组织形成。

### 2.3 O2：跨任务组织选择与保留

O2 是本项目更重要、也更难的研究对象：

```text
O1 候选组织
  → 独立评价和反事实归因
  → probation
  → held-out 复验
  → 保留 / 修改 / 拒绝
  → 后续任务检索和局部重组
  → 漂移后的冷却、重新认证、再分化或退休
```

O2 不是“保存每次成功运行”，也不是“动态生成一个图”。它要求局部产生的组织能够被压缩为少量、有限、可迁移、可撤销的组织先验。

只有 O2 在产生阶段之外的任务族上具有正的保守净收益，才允许使用“组织记忆”“组织演化”或“固化的组织路径”。

## 3. 非目标与禁止偷换

Biofield 当前不主张：

- 动态拓扑本身就是新贡献；
- 多 Agent 数量增加天然带来组织收益；
- 向量分散、稀疏图或通信图变化等于功能分化；
- 频繁使用或高流量的路径天然值得固化；
- 任务 embedding 相似意味着组织拓扑可迁移；
- Field 可以向 Agent 发出角色、任务或拓扑指令；
- 组织检索器可以替 Agent 产生完整分工；
- 保存更多组织快照等于系统持续改进；
- O1 的即时协调等于 O2 的跨任务组织演化；
- O2 自动等于 Harness、评测器或安全规则的自进化；
- 生物电、器官、生态位或能量类比本身提供工程证据。

## 4. 目标系统的多时间尺度结构

Biofield 采用“稳定治理 + 慢速组织记忆 + 快速任务组织”的混合结构，而不是在固定人体与每题从零生成之间二选一。

```text
宪法层：Harness / Evaluation Plane
  长期冻结事实、安全、权限、资源、评测、准入、回滚
        ↓
条件层：Field
  发布局部公共残差、资源、风险、拥塞和覆盖缺口
        ↓
细胞层：Local Agent
  持有私有经验和能力后验，产生 Intent/Bid/Refusal/Communication
        ↕
器官样组织记忆
  保存经验证的组织先验、适用域、失败域和证据
        ↓
任务表型
  本次任务实际形成的 commitment / communication / evidence topology
```

### 4.1 宪法层

Harness 和 Evaluation Plane 持有不可由被评 Agent 直接修改的治理边界：

- Goal/Requirement 与正式测量规则；
- 权限、资源、Admission 和工具副作用；
- 公共事件、Residual、Ledger、终态和回滚；
- evaluator、acceptance rule、实验分组和通过门槛；
- artifact schema、source hash 和 sealing。

它们可以拒绝非法提案，但不替 Agent 产生全部合法行动。

### 4.2 细胞层

Agent 持有局部状态和行动候选产生权。Agent 的长期价值不由永久角色标签定义，而由条件转换能力定义：

```text
给定输入、环境和私有状态，
Agent 能以何种成本和风险产生多少可验证进展？
```

### 4.3 器官样组织层

器官样组织不是一个永久固定的 `Agent A → Agent B → Agent C` 邻接矩阵，而是经经验形成的条件化组织先验。它至少描述：

- 适用的任务条件、风险和资源范围；
- 必要功能、输入、输出和证据接口；
- 必要或可选的承诺、通信和验证关系；
- 可变 Agent 身份、并行数量、工具和局部边；
- 已验证的收益、成本、不确定性和适用范围；
- 失败域、降级、解体、回滚和重新认证条件。

具体任务仍由 Agent 根据当前 Field 和私有状态对组织先验进行接受、拒绝、修改和局部重组。

### 4.4 任务表型层

任务表型是一次运行真正发生的组织，包括：

- requirement-agent commitment；
- Agent 间 Offer/Request 和实际通信边；
- action/evidence/feedback 因果路径；
- 接管、取消、重复工作和争议；
- 真实成本和被接受贡献。

正式评价基于任务表型和环境证据，而不是基于组织先验的自我描述。

## 5. Field 的硬边界

Field 是共享条件介质，不是中央 Router 的别名。

### 5.1 允许的 Field 信号

- requirement residual 和未覆盖信号；
- 低置信、冲突、unknown/disputed 和证据缺口；
- 局部资源稀缺、预算压力和容量；
- 重复工作、拥塞和通信成本；
- 风险、taint、schema drift 和依赖阻塞；
- 时间压力、环境变化和已接受反馈造成的公共状态变化；
- 权限范围内可发现的通信机会。

### 5.2 禁止的 Field 内容

- “Agent A 应执行 requirement X”；
- Agent 排名、固定角色或隐藏能力真值；
- 完整 Allocation 矩阵；
- 预先确定的通信边或最终拓扑；
- 基于其他 Agent 未授权私有状态生成的指令；
- 隐藏的全局效用最优解；
- 只有服从某条路径才能获得的奖励暗示。

### 5.3 Field 合同

Field 必须满足：

- **agent-agnostic**：不包含具体 Agent 的行动结论；
- **local projection**：只暴露权限和局部范围内的公共状态；
- **versioned and replayable**：相同事件、可见范围和版本得到相同观测；
- **multi-channel**：不把资源、风险、残差和信用压成一个不可解释标量；
- **ablatable**：可被 no-field、原始公共状态、简单广播、延迟、噪声或置换替换；
- **non-prescriptive**：描述世界需要什么，不决定哪个 Agent 必须怎样响应。

## 6. 组织记忆不是无限拓扑仓库

### 6.1 保存单位

运行时组织记忆优先保存：

- canonical organization recipe；
- 可复用 communication/verification/takeover motif；
- 适用域和失败域描述符；
- 成本、风险和不确定性后验；
- source run、evidence 和反事实消融引用；
- 版本兼容和重新认证条件。

默认不保存可直接复用的完整私有状态、固定 Agent ID 绑定、具体任务答案或每次运行的完整邻接矩阵。

原始运行和完整图继续进入不可变审计存档，但审计历史不等于运行时可检索记忆。

### 6.2 有界 archive

运行时 archive 必须有预注册容量 `K` 或等价的字节/复杂度预算。候选组织按功能描述符进入有限 niche，例如：

- 分解深度和并行度；
- 通信密度和聚合方式；
- 独立验证强度；
- 专门化与贡献集中度；
- 故障接管模式；
- 成本、延迟和风险档位。

每个 niche 只保留有限 elite 和可选 probation challenger。新候选只能：

1. 填补尚未覆盖的有效 niche；
2. 在 held-out 净价值上支配同 niche 现有组织；
3. 提供无法由现有 motif 组合获得的关键覆盖或恢复能力。

### 6.3 生命周期

```text
candidate
  → probation
  → active
  → dormant
  → quarantine
  → retired
```

- `candidate`：来自一次或多次 O1 的组织候选；
- `probation`：合同有效，但只允许 shadow/canary；
- `active`：通过 held-out、成本和安全门槛，可进入正式检索；
- `dormant`：长期无适用机会、证据老化或暂不经济，但尚未被否定；
- `quarantine`：出现负迁移、版本不兼容、安全或证据问题；
- `retired`：退出运行时 archive，审计证据仍保留，可在新证据下重新认证。

长期未使用只能降低优先级或进入 dormant，不能单独成为删除依据。淘汰还必须考虑：

- 相同 niche 是否已有支配者；
- 在真正适用任务上的负迁移；
- 模型、工具、环境和 evaluator 版本变化；
- 证据新鲜度和重新验证成本；
- 未来需求概率乘以保守净价值是否低于持有成本。

低频但高损失场景所需的恢复或安全组织可以占独立风险 niche，不被普通 LFU/LRU 规则误删。

## 7. 组织选择器与 BTX/MoE 的关系

组织检索与 MoE/BTX 具有结构类比：

| MoE/BTX | Biofield |
|---|---|
| token / sample | 任务上下文、需求和公共状态 |
| expert | Agent、器官样组织或组织先验 |
| router score | 预计适用性和保守净收益 |
| top-k activation | 检索少量候选组织 |
| expert composition | 形成任务级协作结构 |
| load balancing | 探索配额、容量和赢家锁定控制 |

但组织检索器不得拥有 MoE router 式的最终激活权。其正式名称和权限边界是 `OrganizationPriorRetriever`：

```text
公开任务条件
  → 检索少量候选先验和证据
  → 作为 affordance / offer 发布
  → Agent 产生 Bid / Refusal / modification
  → Harness 做合法性、预算和并发准入
  → 形成任务表型
```

Retriever 可以输出：

- 候选先验；
- 适用域、失败域和版本要求；
- 预测净收益、不确定性和负迁移风险；
- 建议 canary 预算。

Retriever 不得输出：

- 强制 Agent 成员；
- 具体 requirement-agent assignment；
- 必须遵循的完整通信图；
- 绕过 Bid/Refusal/Admission 的 Commitment。

中央 topology selector 仍作为强基线。只有 `prior retrieval + local formation` 在等成本下提供独立增量，才支持 Biofield 的局部形成主张。

## 8. 筛选和匹配规则

### 8.1 组织净价值

候选组织的价值不能用流量、消息数、Agent 自评或一次成功代替。至少计算：

```text
NetValue
  = 独立 Evaluation Plane 测得的任务增量
  - model / token / tool / wall-time 成本
  - communication / coordination / retry 成本
  - unsafe proposal / failure / negative-transfer 风险
  - 保存、检索和重新认证成本
```

### 8.2 入库最低门槛

候选组织进入 active archive 前必须：

1. 通过合同、权限、安全和 artifact 硬门槛；
2. 在多个 seed 和独立 task instance 上稳定；
3. 在产生候选时未使用的 held-out block 上成立；
4. 相对最简单适用基线具有正的保守净收益；
5. 通过 edge/node removal、topology swap 或等价消融证明关键结构有反事实贡献；
6. 不依赖 Agent ID、菜单顺序、任务答案或 evaluator 泄漏；
7. 改善 archive coverage，或支配同 niche 现有 elite。

### 8.3 匹配不是固定相似度阈值

固定 task embedding cosine 阈值不能决定零启动、热启动或冷启动。匹配器估计的是：

> 在当前任务和系统版本下，复用候选组织相对于冷启动、固定简单组织或现场搜索，预计增加多少净价值？

候选分数使用保守后验，例如：

```text
predicted mean net value
  - uncertainty penalty
  - negative-transfer risk
  - compatibility / revalidation cost
```

只对 top-M 候选运行小预算 canary。若任务 OOD、置信不足、版本不兼容，或 canary 不优于简单基线，则 abstain 并进入冷启动。

## 9. 经验与演化层级

必须按更新对象报告，不把所有变化都称为自进化：

| 层级 | 变化对象 | 当前用语 | 首轮状态 |
|---|---|---|---|
| E0 | episode 内承诺和通信边 | episode adaptation | 目标 |
| E1 | Agent 私有能力后验和关系偏好 | agent experience adaptation | 目标 |
| E2 | 组织先验、motif 和 archive 生命周期 | organizational evolution | 核心研究目标 |
| E3 | topology generator、retriever、淘汰策略 | architecture-policy evolution | 后续条件实验 |
| E4 | evaluator、Admission、安全和实验规则 | Harness/meta evolution | 冻结、禁止 |
| E5 | 模型参数 | model learning | 当前不做 |

O2 至少属于 E2。只有功能独立的长期机制开始修改“如何产生、检索和淘汰组织”时，才进入 E3。E4 在 ORG0、纵向评测和安全门槛通过前保持外部冻结。

## 10. 可证伪主张阶梯

| Gate | 主张 | 最低证据 | 失败后的收缩 |
|---|---|---|---|
| D | 局部经验造成真实分化 | reset/swap/ID-order 消融，行为随状态迁移 | 保留固定角色或中央分配 |
| O1 | Agent 能形成任务内组织 | scripted/model 局部提案闭环，中心不生成 Intent | 只保留 Harness |
| V1 | O1 在等成本下有价值 | 优于 Single/Fixed/Central 中至少一个强基线 | 报告局部协调但无净收益 |
| F | Field 有独立增量 | Local-field 优于 Local-no-field 和简单广播 | 删除复杂 Field |
| O2 | 候选组织可被筛选和复用 | bounded archive 在 held-out/drift/recurrence 上正迁移 | 每题冷启动或中央 selector |
| G | 组织先验具有泛化性 | leave-one-family-out 与伪相似任务上保守净收益为正 | 限定为 specialist |
| E2 | 组织演化持续成立 | 长序列 retention、plasticity、成本和安全通过 | 冻结 archive 或禁用热启动 |
| E3+ | 更新策略本身可演化 | 独立预注册、重新认证和回滚 | 不进入当前承诺 |

不得跳级。O1 成功不支持 O2；一次拓扑复用不支持泛化；O2 成功不支持 Harness 自进化。

## 11. 核心实验重置

新的科学主线以一个连续任务流为中心：

```text
Discovery
  产生任务内组织候选
    ↓
Selection
  独立 held-out、多 seed、边/节点消融
    ↓
Bounded Archive
  固定 K 个组织 niche / motif / prior
    ↓
Transfer
  同族、跨族、伪相似任务
    ↓
Drift
  Agent 缺席、资源、模型、工具或 schema 变化
    ↓
Recurrence
  低频旧任务重现，测试 dormant 恢复与重新分化
```

最低 arm：

1. `single`；
2. `fixed_best`；
3. `central_task_adaptive`；
4. `local_cold_start`；
5. `local_field_no_retention`；
6. `cosine_unbounded_snapshot`，作为原始方案对照；
7. `lru_lfu_cache`；
8. `bounded_organization_archive`，目标方案；
9. `per_query_search`，完整计入搜索成本的昂贵上界；
10. `oracle_topology`，只作不可部署参考。

最低指标：

- 等成本 NetValue；
- held-out positive transfer 和 negative-transfer rate；
- warm-start 节省的 cycle、token、调用和时间；
- archive 每 slot/byte 的收益与任务覆盖；
- `K` 增大时的收益饱和曲线；
- relative-to-oracle selection regret；
- fallback、cold-start 和 abstention rate；
- topology churn、retirement/reactivation precision；
- drift 后恢复时间；
- replay retention、长期 plasticity 和 safety non-regression。

## 12. 已决定事项

以下内容从本文起视为当前研究决定：

1. Biofield 的差异化核心从一般动态组织收缩为 D + O1 + O2，重点是 O2；
2. Field 永远不直接输出完整分配、角色或通信拓扑；
3. Harness 和 Evaluation Plane 保持事实、资源、安全、准入、评测和回滚权威；
4. 组织记忆保存可重构先验、motif 和证据，不默认保存固定 Agent 邻接矩阵；
5. 具体任务保留局部再组织、拒绝和冷启动权；
6. 运行时 archive 必须有界，审计历史与运行记忆分离；
7. 高频流量和使用次数不构成固化证据；
8. 固化依赖 held-out、反事实边际贡献、成本和安全；
9. 固定 cosine 阈值不作为正式组织匹配规则；
10. `OrganizationPriorRetriever` 只检索候选，不产生 Commitment；
11. 中央 selector、固定组织和每题搜索都是必须保留的强基线；
12. E1/E2 可以成为首轮可变面，E4 Harness/meta 规则冻结。

## 13. 开放问题

以下问题尚未决定，必须通过实现预检或实验冻结：

- organoid 的最小表示是子图、生成规则、接口合同还是组合；
- 是否需要长期稳定 Agent identity，以及它能否跨模型版本迁移；
- archive niche 的描述符、容量 `K` 和复杂度预算；
- motif 的图同构、行为等价和去重算法；
- Agent 接受、拒绝和修改组织先验的最小合同；
- Retriever 使用规则、contextual bandit、学习模型还是混合方法；
- canary 预算、abstention 和负迁移阈值；
- dormant、quarantine、retired 的重新认证条件；
- specialist 与 general organization 的配额和价值比较；
- 什么任务族、漂移和 recurrence 足以支持外部泛化主张；
- O2 通过后是否值得启动 E3 architecture-policy evolution。

开放问题不得在代码中以隐式默认值提前固化。涉及实验结论的选择必须预注册、版本化并保留替代基线。

## 14. 与已有研究的关系

已有工作表明：

- [ROMA](https://proceedings.mlr.press/v119/wang20f.html) 可在 MARL 中学习 specialized、dynamic、identifiable roles；
- [DyLAN](https://arxiv.org/abs/2310.02170) 可按实际贡献选择团队；
- [GPTSwarm](https://arxiv.org/abs/2402.16823) 可优化 Agent 图的节点和边；
- [G-Designer](https://proceedings.mlr.press/v267/zhang25cu.html) 可按 query 生成 task-adaptive topology；
- [AFlow](https://proceedings.iclr.cc/paper_files/paper/2025/file/5492ecbce4439401798dcd2c90be94cd-Paper-Conference.pdf) 可搜索并在 held-out test 上选择 agent workflow；
- [ADAS](https://proceedings.iclr.cc/paper_files/paper/2025/file/36b7acf6f6010652b3f2a433774a66fe-Paper-Conference.pdf) 可让历史 agent/workflow archive 反哺后续设计；
- [QueenBee Planner](https://arxiv.org/abs/2606.27492) 已探索可检索、可改进的通信拓扑技能和 Preserve/Modify/Avoid；
- [MEAL](https://openreview.net/forum?id=Mxg6mo1Xzj) 表明短任务序列会掩盖长期多 Agent retention/plasticity 失效。

因此，“动态拓扑”“自动工作流”或“保存历史结构”本身不是 Biofield 的独立贡献。当前未被上述工作整体回答、也是本项目要验证的组合是：

> 局部经验导致的分化和局部组织，能否在不把决定权重新交给中央 Router 的前提下，经有限 archive、独立证据、跨任务竞争和可逆生命周期形成持续净收益。

## 15. 文档与实现纪律

- 本文只在核心研究命题发生实质变化时修改，不为每个实现批次复制版本；
- 架构合同、实验门槛和实现状态分别维护，不在本文堆叠 CLI 或测试细节；
- 当前代码事实不得从目标架构反推；
- 行为变化遵循 TDD，文档变化同步检查架构、实验协议、状态页和导航；
- 历史架构和已完成结果不为统一当前措辞而重写；
- 负结果可以删除机制、降低主张或停止分支，但不删除审计证据。
