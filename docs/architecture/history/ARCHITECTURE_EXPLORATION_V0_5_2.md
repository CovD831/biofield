# 自组织 Agent 能量场架构：执行前修订 v0.5.2

## 0. 文档定位

本文是 v0.5.1 的执行前修订，不覆盖 v0.5.1，也不重复完整架构。

当前文档关系：

- `ARCHITECTURE_EXPLORATION_V0_5_1.md`：完整技术架构、能量循环和并行实验设计；
- `ARCHITECTURE_EXPLORATION_V0_5_2.md`：开始编码和运行实验前必须采用的最新合同；
- 更早版本：用于追踪思路演化，不再作为实现依据。

v0.5.2 吸收了新一轮对抗性审查中成立的部分，同时拒绝以下不可靠修复：

- 不使用固定 `l_i=1/(2N)`、`u_i=2/N` 作为通用预算规则；
- 不把语义图上的 supports/contradicts 机械转换成置信度加减；
- 不认为常数 \(\epsilon\) 会形成固定的 \(\epsilon/Capacity\) 分配下限；
- 不在 Agent 崩溃时退回已经消耗的资源；
- 不用需求维度相关系数阈值自动合并语义维度；
- 不把固定任务数与种子数声称为完整 power analysis。

---

## 1. 本轮必须修正的核心问题

### 1.1 可靠覆盖

原 Congestion controller 使用：

\[
Coverage_{-i,k}
=
\sum_{j\ne i}A_{j,k}\hat Q_{j,k}
\]

这会把高均值、高不确定性的 Agent 当成可靠覆盖，从而过早排斥其他 Agent。

v0.5.2 将“预期效用”和“可靠覆盖”分开。

#### 方案 A：Lower Confidence Bound

在 \(\hat Q\) 被约束到非负区间、\(\sigma\) 表示后验标准差时：

\[
ReliableQ_{j,k}
=
\max(0,\hat Q_{j,k}-\kappa\sigma_{j,k})
\]

\[
ReliableCoverage_{-i,k}
=
\sum_{j\ne i}A_{j,k}ReliableQ_{j,k}
\]

#### 方案 B：达标概率

如果可以估计能力后验：

\[
ReliableCoverage_{-i,k}
=
\sum_{j\ne i}A_{j,k}
P(Q_{j,k}\ge q_{min})
\]

第一轮优先实现 LCB，因为合同更简单；达标概率作为后续对照。

#### 防止未知维度拥挤

高不确定性会同时产生：

- 低可靠覆盖；
- 高探索吸引。

这可能让多个 Agent 同时涌入一个尚未验证的维度。因此还需要：

- 单需求并发探索上限；
- 重复探索预算；
- 已有独立尝试数；
- 高风险需求的额外验证副本。

可靠覆盖不是让所有未知方向获得无限重复，而是避免未经验证的占位被错误当成有效覆盖。

### 1.2 探索机会与贫困陷阱

provisional credit 参与预算分配可能形成：

```text
早期信用低
→ 预算减少
→ 验证机会减少
→ 不确定性无法下降
→ 长期保持低信用
```

但永久为每个 Agent 提供固定最低预算会阻止无效 Agent 被修剪。

v0.5.2 使用阶段化探索总额：

\[
E_{explore}(t)
=
Schedule(phase, uncertainty, environment\_change)
\]

Agent 级最低份额只是该探索总额的分配结果：

\[
l_i(t)
=
E_{explore}(t)\cdot ExploreShare_i(t)
\]

`ExploreShare` 优先考虑：

- 尚未获得最小尝试次数的 Agent—需求对；
- 高不确定性且高任务价值的方向；
- 环境变化后可能失效的旧能力估计；
- 早期坏运气导致的低信用；
- 已验证低效方向的降权。

探索保障应优先作用于 Agent—需求对，而不是仅保证每个 Agent 获得任意任务。

### 1.3 Allocation 上下限

预算投影仍使用：

\[
q=Project_{\mathcal C}(Softmax(z))
\]

\[
\mathcal C(t)
=
\{q:\sum_iq_i=1,\;l_i(t)\le q_i\le u_i(t)\}
\]

但上下限随阶段变化：

| 阶段 | 下限 | 上限 | 目的 |
|---|---|---|---|
| 初始探索 | 较高 | 较低 | 保证验证机会，防止早期垄断 |
| 双向匹配 | 逐渐下降 | 逐渐放宽 | 根据证据形成分工 |
| 稳定利用 | 很低或部分为零 | 可较高 | 集中资源到高边际收益路径 |
| 环境变化 | 临时提高 | 临时收紧 | 重新探索 |

约束必须满足：

\[
\sum_i l_i(t)\le1\le\sum_i u_i(t)
\]

关键串行任务允许经过记录的上限豁免；豁免原因、期限和实际效果必须进入实验事件。

---

## 2. 场更新中的显式探索

### 2.1 移除每轮隐式 \(\epsilon\) 注入

v0.5.1 使用：

\[
\widetilde A_{i,k}
=
(A_{i,k}+\epsilon)\exp(\eta F_{i,k})
\]

常数 \(\epsilon\) 不会形成固定分配下限，因为当 \(F\rightarrow-\infty\) 时整个乘积仍趋近零。但每轮加入 \(\epsilon\) 会持续向所有维度注入质量，产生隐蔽的均匀化偏置。

v0.5.2 改为：

1. 初始 Allocation 使用严格正值；
2. 基础 mirror update 不再每轮添加 \(\epsilon\)；
3. 新增维度时显式注入初始探索质量；
4. 探索通过独立 mixing 控制。

基础更新：

\[
\widetilde A_{i,k}(t+1)
=
A_{i,k}(t)\exp(\eta F_{i,k}(t))
\]

探索混合：

\[
A_i^{final}(t+1)
=
(1-\zeta_t)A_i^{policy}(t+1)
+\zeta_tA_i^{explore}(U_t,\hat D_t)
\]

- \(\zeta_t\)：显式探索比例；
- \(A^{explore}\)：根据任务残差和不确定性生成的探索分布；
- 环境变化时允许临时提高 \(\zeta_t\)。

这样探索成本可直接观测，不隐藏在数值稳定项中。

### 2.2 修订后的局部驱动力

\[
F_{i,k}(t)
=
\beta\hat D_{t,k}\hat Q_{i,k}
+\chi U_{i,k}
-\lambda Congestion_{-i,k}^{reliable}
-\rho Cost_{i,k}
-\xi Risk_{i,k}
\]

`Congestion` 使用可靠覆盖。\(U\) 同时出现在探索力与可靠覆盖中，因此必须通过消融测量是否导致过度重复探索。

---

## 3. 信用机会与实验观测

### 3.1 不能只观察信用—预算比例

低信用、低预算可能表示正确修剪，也可能表示机会饥饿。单纯观察 provisional credit 与预算比例无法区分。

D1 增加以下指标：

- 每个 Agent—需求对的尝试次数；
- 尝试后的证据数量与权威等级；
- 不确定性下降速度；
- 高不确定性方向的最长饥饿周期；
- 真实高效 Agent 被早期排除的概率；
- 已验证低效 Agent 持续消耗的探索成本；
- 环境变化后旧赢家被重新评估的时间。

### 3.2 机会不足与能力不足

在合成任务中已知真实 \(Q^*\)，可以区分：

- `starved_high_quality`：真实能力高但没有获得机会；
- `correctly_pruned`：真实能力低且被合理降权；
- `over_explored_low_quality`：真实能力低但长期消耗探索预算。

真实任务中无法直接知道 \(Q^*\)，只能使用重复交叉执行、外部验收和 hindsight reference 近似判断。

---

## 4. 语义信念重验证

### 4.1 两张图保持分离

- 时间版本化派生 DAG：负责信用、预算和状态影响的 taint；
- 语义证据图：负责 Claim、Evidence 和关系的重验证。

### 4.2 语义边类型

```text
derived_from
supports
contradicts
references
conflicts_with
```

### 4.3 基础 Claim 被推翻时

- `derived_from` 后代进入 `needs_revalidation`；
- `supports` 和 `contradicts` 关系触发重新评估；
- 不因为“反对了错误 Claim”就自动提高某 Evidence 的可信度；
- 不因为某 Evidence 曾支持错误 Claim 就直接宣布它本身错误；
- 只有重新运行适用 Verifier 后才更新置信度；
- 信用回滚仍沿派生 DAG，不沿全部语义边传播。

面试前不实现通用概率信念传播。`needs_revalidation`、队列和确定性重验证已足够表达风险。

---

## 5. Branch A 修订

### 5.1 A0 增加手动分化基线

A0 条件扩展为：

1. 相同 system prompt、相同输入、相同历史；
2. 相同 system prompt、不同输入；
3. 相同 system prompt、不同执行历史；
4. 不同 system prompt、相同任务；
5. 交换 Agent 标识；
6. 交换任务；
7. 清空执行历史；
8. 手动角色 Prompt 与历史诱导分化直接比较。

需要分别估计：

- 采样效应；
- 任务输入效应；
- system prompt 效应；
- 执行历史效应；
- Agent 标签效应。

如果只有不同 system prompt 能产生稳定功能差异，应将架构定位为：

> 反馈驱动地路由预定义角色 Agent。

不能继续声称角色主要由执行历史自发分化。

### 5.2 A1 按任务结构报告效应

不再使用“没有明显负收益”作为通过条件。

任务结构至少分为：

- 低可分解；
- 高可分解；
- 强依赖；
- 环境变化；
- 信息分区。

每类分别报告：

- 单 Agent；
- 手动固定角色；
- 多 Agent 独立采样后选择；
- 动态分工；
- 任务质量差；
- 实际成本差；
- 延迟差；
- 配对效应和不确定区间。

结论必须写成条件性适用范围，例如：

> 动态分工在高可分解和环境变化任务中产生正收益，在强依赖任务中因协调成本产生负收益。

不能通过挑选获胜任务类别声称总体成立。

---

## 6. Branch C 修订

### 6.1 Oracle 与 hindsight 分离

#### 合成任务

真实 Agent—需求转换效率 \(Q^*\) 已知，可以计算：

```text
synthetic oracle
```

它表示在当前合成环境中的可达上界。

#### 真实任务

真实 \(Q^*\) 不可观测。事后根据所有运行结果选择最优分配只能称：

```text
real-task hindsight reference
```

它不是可在线实现的 oracle，也可能因有限样本高估可达收益。

### 6.2 C0 当前基线

合成环境：

1. 固定均分；
2. UCB 或 Thompson Sampling；
3. 场动力学；
4. synthetic oracle。

真实闭环：

1. 单 Agent；
2. 手动固定角色；
3. 固定均分；
4. UCB 或 Thompson Sampling；
5. 场动力学；
6. real-task hindsight reference，仅作事后参考。

---

## 7. Branch D0 异常终止合同

### 7.1 Action 终态

```text
succeeded
failed
timed_out
abandoned
cancelled
```

### 7.2 部分结算

Agent 异常终止时：

1. 实际已消耗 token、时间和工具成本进入 `Spent`；
2. 未使用 reserve 通过 `return` 退回 SharedPool；
3. 不确定但可能已经产生的外部成本进入 reconciliation queue；
4. 未完成 Action 记录明确终态；
5. 部分 Artifact 进入 `quarantined`；
6. quarantined Artifact 经验证后可被提升、拒绝或保留；
7. 无证据支持的 provisional credit 进入 expired；
8. 已有可验证证据的 provisional credit 保留并单独结算。

### 7.3 必测故障

- grant 后、执行前崩溃；
- 模型已计费但响应超时；
- 产生 Artifact 后、写账前崩溃；
- retry 导致重复响应；
- late response 在任务已经取消后到达；
- OOM；
- API 限流；
- Verifier 失败但 Agent 成功；
- 账本事件重复投递。

### 7.4 幂等和 reconciliation

所有资源事件需要 `idempotency_key`。对于无法立即确认实际消费量的调用，先保留 reserve，待供应商或本地运行记录确认后完成 reconciliation。

---

## 8. 任务维度依赖

### 8.1 不假设统计独立

Simplex 只表示有限容量如何分配，不代表需求维度在统计或语义上独立。

任务需求可以包含：

```text
requires
synergizes_with
conflicts_with
```

### 8.2 面试前范围

- B0 记录已知依赖；
- Demo 至少包含一个串行依赖；
- 不按相关系数自动合并维度；
- 不实现高阶交互效用模型；
- 如果可加性假设明显失败，将该任务标记为超出当前 allocator 模型适用范围。

---

## 9. 样本量与统计声明

### 9.1 Pilot 优先

先运行小规模 pilot 估计：

- 任务内方差；
- 随机种子方差；
- 最小有意义效应；
- 单次运行成本。

随后决定正式任务数和重复次数。

### 9.2 配对设计

尽可能让不同策略在相同任务、相同输入版本和相同随机种子组上比较，以减少任务差异带来的方差。

### 9.3 时间不足时

如果无法获得足够统计效力：

- 报告全部原始运行；
- 报告效应大小和不确定区间；
- 标记为 exploratory evidence；
- 不使用“证明”“显著优于”等结论；
- 不因单个成功种子更新主张状态为 supported。

固定 `5 个任务 × 3 个种子` 可以作为资源下限示例，但不能被称为普遍有效的 power analysis。

---

## 10. 更新后的执行优先级

### 开始实验前完成

1. A0 增加 system prompt 手动分化基线；
2. A1 改成按任务结构报告效应；
3. Congestion 使用可靠覆盖；
4. 探索从隐式 \(\epsilon\) 改成显式 mixing；
5. D0 加入异常终止和部分结算；
6. C0 区分 synthetic oracle 和 real-task hindsight；
7. ExperimentResult 支持 effect size、interval 和 `exploratory` 标记。

### Pilot 后校准

- \(\kappa\)：可靠覆盖置信折扣；
- \(\zeta_t\)：探索混合比例；
- \(l_i(t),u_i(t)\)：预算上下限；
- 正式样本量；
- 任务类型分层；
- 误差安全工作区间。

### 面试后再考虑

- 通用 belief propagation；
- 需求拆分、合并和语义漂移；
- 通用风险价格；
- 学习型神经 Router；
- hidden-state 通信；
- 异构模型对齐；
- 长期组织记忆。

---

## 11. 负结果叙事

如果 UCB 或固定分配优于场动力学：

> 当前模型规模和任务下，反馈驱动分配本身有效，但连续场没有提供足以覆盖复杂性的额外收益。因此实现选择更简单控制器；研究沉淀是残差误差阈值、资源账本、任务结构适用范围和统一评估框架。

如果只有 system prompt 能形成分工：

> 当前模型中，执行历史不足以稳定诱导功能分化；系统更准确的定位是反馈驱动地路由预定义角色，而不是完全涌现角色。

如果多 Agent 只在高可分解任务中获胜：

> 架构收益依赖任务结构。高可分解和环境变化任务适合动态分工，强依赖和低复杂度任务应选择单 Agent 或固定流水线。

如果残差误差使反馈失效：

> 反馈控制存在明确的误差工作区间。超过阈值时，自适应分配会放大错误，系统应降级到固定分配或请求外部校正。

负结果不通过增加超参数隐藏。它直接更新主张状态和默认控制器选择。

---

## 12. v0.5.2 开始实现的门槛

文档层面完成以下检查后即可开始：

- 可靠覆盖公式和变量范围明确；
- system prompt 基线进入 A0；
- A1 不再使用“明显负收益”汇总判定；
- synthetic oracle 与 hindsight 分开；
- D0 包含异常终止；
- 探索成本显式可观测；
- 语义重验证不自动传播未经校准的置信度；
- pilot 结果不会被表述为统计证明。

后续不再因为新的概念讨论无限延迟实验。未进入当前门槛的问题记录为开放限制，在执行中用数据决定是否升级。
