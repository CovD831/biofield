# F0 最小真实闭环 Pilot v1

## 结论

F0-contract 与 F0-model 的第一阶段门槛通过。

规范运行使用本地 `qwen3:8b`、固定角色和确定性 R1 verifier。在首周期注入一个结构合法但内容为空的 fact artifact 后，verifier 正确拒绝；下一周期仍分配给 fact 角色，新证据被接受并显式失效旧 rejection，随后路由依次进入 conflict 和 decision，最终完成闭环。

本结果支持：真实 action、证据、反馈、残差、再分配、资源结算和终态封存可以在同一最小运行中连接起来。它不支持动态分工、history-conditioned 路由、场动力学或多 Agent 净收益已经成立。

## 运行配置

| 项目 | 值 |
|---|---|
| 任务 | `cold_chain_readiness` v1 |
| 模型 | 本地 `qwen3:8b` |
| 路由 | `predefined_role` |
| 角色 | fact / conflict / decision |
| seed | 9000；真实调用为 9001、9002、9003 |
| action budget | 4 |
| token budget | 50,000 |
| 单动作 token reservation | 8,192 |
| max cycles | 4 |
| 故障注入 | cycle 0 返回空 `key_facts` |
| 规范 run | `runs/f0-model/f0-model-20260714-v5-canonical` |

命令：

```bash
PYTHONPATH=src .venv/bin/python -m biofield.f0_model \
  --output-directory runs \
  --run-id f0-model-20260714-v5-canonical \
  --task-id cold_chain_readiness \
  --model qwen3:8b \
  --seed 9000 \
  --action-budget 4 \
  --token-budget 50000 \
  --token-reservation 8192 \
  --max-cycles 4 \
  --inject-invalid-first
```

## 规范运行结果

| 指标 | 结果 |
|---|---:|
| terminal status | `completed` |
| cycles | 4 |
| accepted / rejected feedback | 3 / 1 |
| residual revision | 4 |
| 实际模型调用 | 3 |
| input / output tokens | 1,896 / 269 |
| spent tokens | 2,165 |
| 模型总延迟 | 24.92 秒 |
| 公共事件数 | 42 |
| final state SHA-256 | `6273a57072b1bf52e79d0039bbf26802c91dc960df619468b23aa9aed33ff572` |

分配—反馈序列：

| cycle | role / requirement | feedback | 对下一周期的影响 |
|---:|---|---|---|
| 0 | fact / `fact_extraction` | rejected | fact 保持未满足，下一周期继续分配 fact |
| 1 | fact / `fact_extraction` | accepted，并失效 `feedback-000` | fact 满足，解锁 conflict |
| 2 | conflict / `contradiction_resolution` | accepted | conflict 满足，解锁 decision |
| 3 | decision / `decision_synthesis` | accepted | 全部必需维度满足，运行完成 |

资源账本对 action units 和 tokens 分别执行预留、消费和未用额度返还。最终两类资源均满足 `accounted = expected`；故障注入动作消费 1 action unit，但没有伪造模型 token 消费。

每次真实模型调用均写入 `model_invocation` 公共事件，包含：

- request fingerprint；
- effective seed；
- provider payload/response hash；
- provider model ID 和 done reason；
- input/output token；
- provider 分段延迟。

最终 `finalization.json` 对 config、events、metrics 和 summary 逐文件封存 SHA-256；封存后拒绝追加事件或再次 finalize。

## F0-contract 覆盖

新增合同测试覆盖：

- 正常三周期完成；
- action 失败后终止且不解锁下游；
- 无效证据被拒绝且不能宣告完成；
- 预算不足时不执行未获资源的 action；
- accepted recovery feedback 显式失效旧 rejection；
- 终态后拒绝再次执行；
- config/event/metrics schema 强制校验；
- finalize 必须等待完整产物并在完成后封存运行。

完整测试基线为 `188 passed`，`compileall` 通过。

## 探索过程中发现并修复的问题

### 1. 任务值合同缺失

第一次真实运行连续三次停留在 fact：模型正确读取中文材料，但输出中文事实句；答案键却要求 `failed`、`expired`、`hold` 等英文规范值，而任务 schema 只声明任意字符串。

处理方式不是放宽 verifier，也不是公开正确答案，而是给任务增加公开候选合同，例如：

- generator test：`passed | failed | unknown`；
- certificate：`valid | expired | missing`；
- readiness：`proceed | hold | insufficient_evidence`。

模型仍需从材料中选择值，答案键继续独立验收。

### 2. Ollama grammar 不支持复杂 `oneOf`

第二次运行在推理前被 provider 拒绝：按 fact ID 使用 `oneOf` 的精细 JSON Schema 无法被 Ollama grammar compiler 解析。

provider 侧 schema 因此缩减为 fact ID enum、字符串 value 和 citations；每个 fact 的精细值合同放入 Prompt，确定性 verifier 保持不变。该兼容处理没有扩大执行权限或降低 acceptance 门槛。

### 3. accepted 不能隐式覆盖旧 rejection

最初的受控恢复测试中，新 accepted feedback 与旧 rejection 同时 active，B0 正确投影为 `disputed`。F0 现在要求恢复 feedback 显式填入 `invalidates_feedback_ids`，避免用“最后写入获胜”破坏证据历史。

## 早期运行审计

| run | 结果 | 主要信息 |
|---|---|---|
| v1 | `max_cycles`，3 cycles，2,485 tokens | 暴露公开值合同缺失；verifier 没有误接受中文自由文本 |
| v2 | `failed`，1 cycle，0 tokens | 暴露 Ollama grammar 不支持精细 `oneOf`；预留 token 全部返还 |
| v3 | `completed`，3 cycles，2,155 tokens | 无故障成功 episode 通过 |
| v4 recovery | `completed`，4 cycles，2,165 tokens | 故障—恢复通过，但尚未写 provider audit 公共事件 |
| v5 canonical | `completed`，4 cycles，2,165 tokens | 规范结果；包含完整 provider audit 和文件封存 |

这些运行不合并成统计样本。它们分别用于发现合同问题、provider 兼容问题、成功路径和受控恢复路径。

## 边界与下一步

F0 仍是单任务、单模型、固定角色的工程门槛，只证明闭环可运行。下一批应并行启动：

1. E0：从 v5 的 42 个真实事件重放终态和账本；
2. A1/F-eval：相同成本比较单 Agent 与固定角色多 Agent；
3. B1/D1：向 feedback 注入错误、延迟和 disputed，测恢复与降级；
4. L0：消费真实轨迹比较无历史、原始历史、结构化统计和必要时的 latent 表示。

opaque ID 和更多人工 history 探针仍不回到主线。
