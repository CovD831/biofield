# C1 Allocator Pilot v1 结果

> 此版本保留作审计。规范结果已由 [C1 Pilot v2](./C1_PILOT_V2.md) 取代；v2 补齐了控制器参数、代码哈希、动作空间和版本化事件信封。

## 状态

- 日期：2026-07-13
- 证据等级：`exploratory`
- 配置：3 Agent、4 个需求维度、30 cycle、种子 0–9
- 任务结构：`complementary`、`homogeneous`、`switch`
- 对照：Equal、UCB、Field、Synthetic Oracle
- 有效原始运行：`runs/c1-pilot-v1/paired-seeds-0-9-warming-fix/`
- 被替代运行：`runs/c1-pilot-v1/paired-seeds-0-9/`。该运行暴露出 Warming 的主观测可能永远不覆盖第四维，因此只保留作审计，不进入结论。
- 技术判定：通过。120 个策略运行均完成，无非法 allocation、NaN、Inf 或崩溃。
- 科学判定：混合结果；不能宣称 Field 普遍优于 UCB。

所有表格中，最终残差和残差面积越低越好。

## 均值汇总

| 任务结构 | 策略 | 最终残差 | 残差面积 | 总进展 | 成本 |
|---|---|---:|---:|---:|---:|
| Complementary | Equal | 0.5700 | 69.7270 | 3.4300 | 90 |
| Complementary | UCB | 0.3363 | 66.7861 | 3.6637 | 90 |
| Complementary | Field | **0.2734** | 67.0527 | **3.7266** | 90 |
| Complementary | Oracle | 0.0000 | 42.5560 | 4.0000 | 66 |
| Homogeneous | Equal | 0.0520 | 62.6156 | 3.9480 | 90 |
| Homogeneous | UCB | **0.0418** | **62.6004** | **3.9582** | 90 |
| Homogeneous | Field | 0.0660 | 62.6497 | 3.9340 | 90 |
| Homogeneous | Oracle | 0.0151 | 61.1797 | 3.9849 | 90 |
| Switch | Equal | 0.5700 | 69.7270 | 3.4300 | 90 |
| Switch | UCB | **0.3322** | 66.8772 | **3.6678** | 90 |
| Switch | Field | 0.6831 | 69.0085 | 3.3169 | 90 |
| Switch | Oracle | 0.0000 | 42.5560 | 4.0000 | 66 |

## 配对结果

Field 相对 UCB 的配对均值差：

| 任务结构 | 最终残差差（Field − UCB） | 残差面积差（Field − UCB） | 解释 |
|---|---:|---:|---|
| Complementary | −0.0629 | +0.2666 | 最终残差 10/10 更低，但残差面积只在 3/10 更低；探索前期开销抵消部分后期收益 |
| Homogeneous | +0.0241 | +0.0493 | 最终残差 0/10 更低，残差面积只在 3/10 更低 |
| Switch | +0.3510 | +2.1312 | 两项均为 0/10 更低；Recovery/Warming 明显过度探索 |

## 当前结论

1. Field 的收益具有任务结构和时间口径条件：能力互补时最终残差出现稳定正向信号，但前期探索成本使残差面积没有优于 UCB。
2. 能力同质时 Field 没有收益；它为本来不存在的专业化支付了额外探索成本。
3. `switch` 暴露了具体失败：环境变化后将旧观测折半会重新进入强 Warming，未知方向获得主尝试，但探索持续过久，最终表现甚至落后 Equal。
4. Equal、UCB 和 Field 都满足“可运行”的技术门槛，但 Field 没有满足承担 F0 的机制门槛；第一次闭环使用 UCB。
5. Oracle 只是读取隐藏真值的一步最优参考，不是可部署策略。

## 下一步

- 先增加逐周期 allocation、覆盖缺口、饥饿、Warming 持续时间、切换后恢复周期和 Router 成本指标；
- 预先冻结一个 Recovery 消融实验，比较“保留旧后验、折扣旧后验、重置旧后验”，并比较 Warming 的硬主尝试比例；不在当前 10 个种子上反复调参；
- 使用独立种子或新 fixture 做确认，防止在 Pilot 上过拟合；
- C1 技术门槛通过后，B1 可以开始注入残差误差；
- F0 使用 UCB 先打通闭环，Field 作为并行对照继续研究。
