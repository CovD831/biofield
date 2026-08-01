# A0 T0/T1 本地模型 Pilot v1

## 结论

本轮证明了本地小模型实验链路可以稳定运行，但没有证明历史已经诱导出可用的功能分化。

- T0 同 seed 重复：4/4 调用成功；两项任务的结构化内容、行为签名、token 和评分均逐字复现。
- T1 核心技术 Pilot：32/32 调用成功；无传输、模型身份、截断、JSON、schema 或评分失败。
- 16 个配对的 `behavior_signature` 全部相同，均为 `contradiction_resolution / cross_check`。
- 这个全零差异不能直接写成“历史无效”。两项 R1 任务本身都强制要求跨材料找矛盾，当前自报式行为签名出现了测量饱和。
- 因此本轮判定为 `inconclusive_measurement`，不能进入 A0 的 `support` 或 `reject`，也不能据此解锁 F0 的科学门槛。

下一步不直接把当前设计扩到 240 次。先把 A0 拆成：

1. A0a：执行前的受限动作选择，直接记录模型选择的下一项工具动作；
2. A0b：保留当前 R1 完整任务，测量实际答案质量和行为结果向量。

后续状态：A0a 已完成首轮与 5-seed 扩样，结果见 [`A0A_ACTION_CHOICE_PILOT_V1.md`](./A0A_ACTION_CHOICE_PILOT_V1.md)。该后续通过了“人工冻结历史可控制下一路由动作”的技术门槛，但经验诱导与反馈闭环仍待 v2。

## 运行环境

| 项目 | 值 |
|---|---|
| 主机 | Apple M4，32 GB 内存 |
| 系统 | macOS 26.2 arm64 |
| Python | 3.13.9 |
| 运行时 | Ollama 0.31.2 |
| 模型 | `qwen3:8b` |
| 模型 digest | `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41` |
| 模型规格 | 8.2B，GGUF，Q4_K_M |
| 推理方式 | 本地 Metal/GPU，`think=false`，JSON Schema 输出 |
| 采样参数 | temperature 0.6，top_p 0.9，top_k 40，repeat_penalty 1.1 |
| 上下文与输出上限 | num_ctx 8192，num_predict 1024 |

模型文件存放在用户级 `~/.ollama/models`，没有写入 OpenPilot 项目目录。实验代码和运行产物仍位于隔离的 `experiments/biofield_architecture` 下。

## T0：同 seed 重复性

T0 使用同一模型、同一请求内容、同一 seed 4200，每项任务连续调用两次。预热调用不计入指标。

| 任务 | 完成 | 请求 token | 输出 token | R1 分数 | 内容逐字复现 | 行为签名复现 |
|---|---:|---:|---:|---:|---|---|
| software release readiness | 2/2 | 780 / 780 | 315 / 315 | 0.396667 / 0.396667 | 是 | 是 |
| cold chain readiness | 2/2 | 823 / 823 | 269 / 269 | 0.266667 / 0.266667 | 是 | 是 |

两个任务都选择 `contradiction_resolution / cross_check`。T0 只证明当前 Ollama 配置下固定 seed 可复现，不证明该行为坐标具有区分度。

机器可读产物：`runs/a0-t0/qwen3-8b-same-seed-v1/`。

## T1：四个核心条件技术 Pilot

### 设计

- 2 个 R1 任务；
- 1 个逻辑 Agent 标签；
- 每个条件 2 个配对重复；
- 4 个核心条件；
- 每个配对 2 个臂；
- 总计 16 个配对、32 次串行调用；
- control-first 与 treatment-first 各 8 个配对；
- 同一任务、Agent、重复中的四个条件共享 primary seed；只有 sampling-noise treatment 使用冻结的 alternate seed；
- 两臂相邻执行，无自动重试，失败保留在计划分母中。

机器可读产物：`runs/a0-core-pilot/qwen3-8b-core-technical-v1/`。

### 工程结果

| 指标 | 结果 |
|---|---:|
| 计划 / 完成调用 | 32 / 32 |
| 完成配对 | 16 / 16 |
| provider / JSON / schema 失败 | 0 |
| 输入 token 总数 | 25,412 |
| 输出 token 总数 | 9,027 |
| 平均单次墙钟时延 | 22.57 秒 |
| 32 次累计墙钟时延 | 722.32 秒 |
| 行为签名发生变化的配对 | 0 / 16 |

32 次调用都返回请求的模型 ID，且 `done_reason=stop`。8 组被设计为完全相同的 payload 在重复出现时都生成完全相同的结构化内容，没有发现内容复现违例。

### token 平衡

execution-history 条件的两段历史在目标模型上的实际请求 token 已满足协议要求：

| 任务 | common | specialized | 相对差异 |
|---|---:|---:|---:|
| software release readiness | 780 | 781 | 0.13% |
| cold chain readiness | 823 | 824 | 0.12% |

role-induction 两臂也接近：software 为 781/784，cold-chain 为 824/827，差异都低于 0.4%。

history-clear 则不是等长干预：software 为 780/715，cold-chain 为 823/758，约有 8% 的上下文长度差。它只能解释成“移除历史的总体消融”，不能单独归因为历史语义。科学 Pilot 前必须增加等长 neutral filler history。

## 行为与质量结果

### 显式行为签名

四个条件、两个任务、两个重复、两个臂的 32 个签名全部是：

```text
requirement_id = contradiction_resolution
action_type    = cross_check
```

采样 seed 虽然显著改变了自由内容和输出长度，但没有改变签名或 R1 总分。这说明文本差异不能当成功能分化证据，同时也暴露了当前单一分类签名的天花板效应。

### R1 配对分数

下表是 treatment 减 control 的 R1 总分。每格包含两个冻结 seed 的结果。

| 任务 | sampling noise | execution history | history clear | manual prompt vs history |
|---|---|---|---|---|
| software release | 0, 0 | 0, -0.13 | +0.13, -0.13 | 0, +0.13 |
| cold chain | 0, 0 | +0.083333, +0.083333 | 0, 0 | -0.083333, -0.083333 |

跨任务聚合均值分别为：

- sampling noise：0；
- execution history：+0.009166；
- history clear：0；
- manual prompt vs history：-0.009166。

聚合均值掩盖了任务差异，不能单独解释。值得保留的弱信号是：cold-chain 任务中 specialized history 在两个 seed 上都让 contradiction score 增加 0.333333；相对该历史，manual prompt 两次都减少 0.333333。software 任务上的事实与引用分数方向则不稳定。

这仍不足以声称“历史优于 Prompt”：每格只有两个 seed、一个模型和一个逻辑 Agent；role-induction 也还是两个诱导包的比较，而不是严格的同语义跨通道实验。

## 对架构假设的含义

### 已证实的工程事实

- 本地小模型可以在不使用付费 API 的情况下进入 A0，避免无模型阶段过长。
- 模型 tag、digest、量化、请求 payload、seed、执行顺序、token、分段时延和失败可以完整审计。
- 固定 seed 的请求可精确复现；不同 seed 可以改变具体输出。
- 真实模型下 common/specialized 历史的 token 平衡成立。
- 当前 32 调用技术成本可接受，可以继续做更有区分度的小实验。

### 尚未证实

- 历史是否能让 Agent 的需求选择产生超过采样噪声的稳定分化；
- 这种分化能否改善任务覆盖或净收益；
- 动态历史诱导是否优于手动角色 Prompt；
- 三个 Agent 是否会形成互补分工；
- 结果能否迁移到目标面试公司实际使用的模型和 harness。

### 不能做出的负结论

不能把“32 个签名相同”直接写成“自组织不成立”。当前任务都要求找矛盾，模型选择同一主要工作是合理的；测量工具没有提供多个同等可行、会产生真实后果的下一步动作。

## 下一分支：A0a / A0b

### A0a：受限下一动作选择

把行为测量移动到执行之前。环境给出三个同等优先、前置条件都满足的未完成需求，只允许模型选择一个会被真实执行的下一动作：

- `inspect_facts`；
- `cross_check_conflicts`；
- `synthesize_decision`。

选择应以结构化 action/tool call 记录，不再让 adapter 从自由文本分类，也不再让模型在完成全部任务后回顾性自报“主要工作”。先比较 sampling、fact-history vs conflict-history、等长 neutral history、以及同语义的 history vs system prompt。

### A0b：完整 R1 执行

保留当前完整任务，但把行为结果改为确定性向量：

- critical fact score；
- citation score；
- contradiction score；
- decision score；
- token 和时延。

A0a 回答“历史能否改变下一动作”，A0b 回答“改变后实际做得怎么样”。只有二者配对，才不会把自报标签、任务能力和真实行为混在一起。

## 下一步门槛

1. 增加等长 neutral filler history，修复 history-clear 长度混淆；
2. 冻结 A0a 三动作 schema、seed 表和距离指标；
3. 先跑 2 任务 × 2 seed 的 A0a 技术检查；
4. 若动作选择不再饱和，再跑每条件 5 个配对重复；
5. 三个 Agent 标签只作为阻断变量，不能当作三个独立模型样本；
6. 若 A0a 仍不响应历史但手动角色稳定有效，冻结 `routing_mode=predefined_role` 降级方案；
7. 在完成这些步骤前，不运行当前签名设计的 240 次核心 Pilot，也不通过 A0 的 F0 科学门槛。
