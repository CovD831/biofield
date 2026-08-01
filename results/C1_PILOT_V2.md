# C1 Allocator Pilot v2 结果

## 状态

- 日期：2026-07-13
- 证据等级：`exploratory`
- 范围：固定每个 Agent 的单位容量，只比较 Agent 内部如何把容量分配到需求维度；**不包含跨 Agent 的能量预算份额 `q_i`**
- 配置：3 Agent、4 个需求维度、30 cycle、种子 0–9
- 任务结构：`complementary`、`homogeneous`、`switch`
- 对照：Equal、UCB、Field、privileged discrete one-step reference
- 规范原始运行：`runs/c1-pilot-v2/paired-seeds-0-9-config-bound/`
- 被替代的 v2 运行：`runs/c1-pilot-v2/paired-seeds-0-9/` 的数值有效，但事件尚未携带时间和配置哈希，只保留作审计
- 被替代运行：`runs/c1-pilot-v1/paired-seeds-0-9-warming-fix/` 的数值有效，但配置没有完整记录控制器参数、代码哈希和版本化事件信封，因此由 v2 取代
- 技术判定：通过。120 个策略运行均完成，无非法 allocation、NaN、Inf 或崩溃
- 科学判定：混合结果；不能宣称 Field 普遍优于 UCB

规范 v2 运行固化了 fixture、实现版本、Field/UCB 参数、动作空间、`synthetic.py` 与 `allocator.py` 的 SHA-256，并为每条原始结果写入时间、配置哈希、确定性的 `event_id`、逻辑序号、payload 版本和因果父事件列表。配置哈希绑定 `run_id` 与启动时间，因此跨配置的相同数值不会复用事件 ID。

所有表格中，最终残差和残差面积越低越好。

## 均值汇总

| 任务结构 | 策略 | 最终残差 | 残差面积 | 总进展 | 成本 |
|---|---|---:|---:|---:|---:|
| Complementary | Equal | 0.5700 | 69.7270 | 3.4300 | 90 |
| Complementary | UCB | 0.3363 | 66.7861 | 3.6637 | 90 |
| Complementary | Field | **0.2734** | 67.0527 | **3.7266** | 90 |
| Complementary | Discrete reference | 0.0000 | 42.5560 | 4.0000 | 66 |
| Homogeneous | Equal | 0.0520 | 62.6156 | 3.9480 | 90 |
| Homogeneous | UCB | **0.0418** | **62.6004** | **3.9582** | 90 |
| Homogeneous | Field | 0.0660 | 62.6497 | 3.9340 | 90 |
| Homogeneous | Discrete reference | 0.0151 | 61.1797 | 3.9849 | 90 |
| Switch | Equal | 0.5700 | 69.7270 | 3.4300 | 90 |
| Switch | UCB | **0.3322** | 66.8772 | **3.6678** | 90 |
| Switch | Field | 0.6831 | 69.0085 | 3.3169 | 90 |
| Switch | Discrete reference | 0.0000 | 42.5560 | 4.0000 | 66 |

## 配对结果

Field 相对 UCB 的配对均值差：

| 任务结构 | 最终残差差（Field − UCB） | 残差面积差（Field − UCB） | 解释 |
|---|---:|---:|---|
| Complementary | −0.0629 | +0.2666 | 最终残差 10/10 更低，但残差面积只在 3/10 更低；前期探索开销抵消了部分后期收益 |
| Homogeneous | +0.0241 | +0.0493 | 最终残差 0/10 更低，残差面积只在 3/10 更低 |
| Switch | +0.3510 | +2.1312 | 两项均为 0/10 更低；Recovery/Warming 明显过度探索 |

## 当前结论

1. Field 的收益具有任务结构和时间口径条件：能力互补时最终残差出现稳定正向信号，但前期探索成本使残差面积没有优于 UCB。
2. 能力同质时 Field 没有收益；它为本来不存在的专业化支付了额外探索成本。
3. `switch` 暴露了具体失败：环境变化后将旧观测折半会重新进入强 Warming，未知方向获得主尝试，但探索持续过久，最终表现甚至落后 Equal。
4. Equal、UCB 和 Field 都满足“可运行”的技术门槛，但 Field 没有满足承担 F0 的机制门槛；第一次闭环使用 UCB。
5. 离散参考读取隐藏真值，而且动作空间不同；这里只报告到该参考的性能差距，不把它称为连续分配或全时域最优策略，也不计算带有上界含义的 regret。
6. C1 尚未验证能量注入、跨 Agent 预算份额、结算或赢家锁定；这些结论必须等待 D0a/E0/F0 及后续实验。

## 下一步

- F0 使用 UCB 先打通 `TaskSpec → ResidualSnapshot → allocation → action → feedback → ledger settlement → next cycle → acceptance`；
- 在 F0 中增加跨 Agent 预算份额 `q_i`，把“需求维度路由”和“能量预算路由”分成两个可独立消融的控制层；
- 预先冻结 Recovery 消融实验，比较保留、折扣和重置旧后验，并使用独立种子或新 fixture，避免在本 Pilot 上反复调参；
- 增加逐周期 allocation、覆盖缺口、饥饿、Warming 持续时间、切换后恢复周期和 Router 成本指标；
- C1 技术门槛通过后，B1 可以并行开始残差误差注入。
