# P2 Planner and Safe Routing Baseline / P2 Planner 与安全路由基线

**Status / 状态:** Implemented on 2026-10-26

> Current architecture note (Q7, 2026-10-30): this document records the P2
> deterministic baseline. Production/default natural-language routing is now
> `llm_only`: RuleRouter no longer classifies ordinary business text and remains only
> as a safety screen plus an explicit `hybrid` experiment baseline. LLM candidates
> must carry quoted user evidence and still pass CapabilityBroker, PlanVerifier and
> Banking Core checks.

## English Summary

P2 delivers a single-turn vertical slice: a conservative rule router, provenance-aware
slot extraction, least-privilege capability disclosure, template baseline planning,
deterministic DAG/tool/argument verification, and a standalone Agent API. Exact Green
queries can execute typed Banking Core tools. Missing financial slots trigger
clarification. Transfer requests can create a task-id-bound draft only and cannot see
or call `commit_transfer` before the P3 approval-resume flow exists.

The real Agent API was run beside the Banking Core and returned two persisted seeded
accounts through `get_accounts`. Injection-like text could not expand capabilities in
tests. The reviewed 15-case routing contract set scored 15/15, but it is intentionally
small and is not the frozen P5 benchmark.

## 中文正文

### 范围、依赖、风险与不做事项

本阶段实现单轮闭环，不实现持久 session/task/checkpoint、跨进程恢复、MFA 恢复或 SSE。
路由只对极明确的 Green 请求直达；写操作、复合请求和带注入标记的文本进入更严格路径。
自然语言中的 `user_id`、授权、风险或工具名不能改变服务器身份与 capability 集合。

### 数据流与安全边界

```text
AgentRequest (untrusted)
  -> RuleRouter (exact Green allowlist; otherwise planner/fallback)
  -> SlotTracker (USER_EXPLICIT / TOOL_VERIFIED / MODEL_INFERRED)
  -> CapabilityBroker (trusted context + intent + stage)
  -> BaselinePlanner (TaskPlan; transfer draft only)
  -> PlanVerifier (DAG, depth, allowlist, provenance, Pydantic tool schema)
  -> ToolGateway -> Banking Core
  -> AgentResponse (only ToolResult data is banking truth)
```

### 路由规则

| 情况 | Route | 行为 |
|---|---|---|
| 精确“我的账户/账户列表” | `RULE_DIRECT` | `get_accounts` |
| 明确余额/流水且账户 ID 已显式给出 | `RULE_DIRECT` | schema 校验后读工具 |
| 余额/流水缺账户 | direct classification + clarification | 不猜默认账户 |
| 转账/汇款 | `PLANNER` | 缺 slot 则追问；齐全时仅创建草稿 |
| 含“忽略规则/隐藏工具/绕过审批”等 | `PLANNER` | 标记不可信，不能扩大工具集 |
| 未支持贷款、预测等 | `SAFE_FALLBACK` | 明示范围并请求改写 |

### Slot 与参数来源

金额使用 `Decimal` 解析后以两位十进制字符串进入 tool arguments。账户 UUID、金额和币种
必须是用户明确提供或工具验证；`MODEL_INFERRED` 参数一律不能执行。每个参数必须有精确
provenance，来源集合与参数键不一致时 Plan Verifier 拒绝。

### Capability Broker

Capability 由可信 `TrustedAgentContext`、确定性 intent 和阶段决定，不读取 Prompt 中的
“请调用某工具”。Transfer planning 只能看到账户、余额、收款人解析、草稿和状态查询，
看不到 `commit_transfer`、卡挂失、理财申购等无关/敏感工具。

### Plan Verifier

确定性检查包括：step 上限、唯一 ID、依赖存在、无环、最大深度、Tool Registry 存在、
action allowlist、参数来源完整、禁止推断金融参数以及工具 Pydantic input schema。验证失败
不会执行部分计划。

## Contracts / 契约

`POST /agent/requests`（Agent API 独立基地址）请求示例：

```json
{"schema_version":"v1","session_id":"...","message":"查看我的账户","locale":"zh-CN"}
```

Green 成功返回 `COMPLETED`、结构化计划及来自 ToolResult 的 `result`。缺信息返回
`NEEDS_CLARIFICATION`。转账草稿工具返回待审批时映射为 `WAITING_APPROVAL`，且当前阶段
不会继续调用 commit。task UUID 同时作为系统生成的幂等键，用户/模型不能覆盖。

兼容性：Banking Core REST 与 32 个 Tool schema 未改变；只新增独立 Agent API，并同步
更新 `docs/A_manual.md`。

## Evidence / 证据

```powershell
.\.venv\Scripts\pytest.exe -q tests/test_agent_routing_planning.py tests/test_agent_api.py
.\.venv\Scripts\python.exe -m scripts.evaluate_p2_baseline
$env:DATABASE_TEST_URL = "postgresql+psycopg://banking:banking@localhost:5432/banking_test"
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe --no-incremental banking_core agent_tools agent shared scripts tests
```

结果：专项 9 passed；全量 55 passed；真实双服务 Green 调用返回 Core 中两个账户；Ruff
通过。路由小集合 15/15，单次进程内平均约 33 µs（机器与运行波动明显，不代表端到端
延迟）。Verifier fixture 分别拒绝 unknown tool、not allowed、model inferred 与 cycle。

Raw data / 原始数据：

- `evaluation/reports/p2_routing_baseline.csv`
- `evaluation/reports/p2_routing_baseline.json`

![Intent confusion matrix](../evaluation/figures/p2_intent_confusion_matrix.png)

![Verifier rejection reasons](../evaluation/figures/p2_verifier_rejections.png)

限制：15 条数据只用于 P2 契约回归，不含大规模口语、同名收款人和多轮分布；正式准确率、
macro-F1、token 与成本比较必须等待 P5 冻结数据和 P6/P8 重复实验。

## Decision / 决策

选择“确定性规则只处理窄 Green，其他 fail closed”作为未来 LLM/Jev 的安全基线。模板
Planner 不宣称覆盖完整中文表达，但提供了可验证、安全、可测的下界。P3 在此边界上新增
持久任务、审批中断和恢复，不允许另建绕过 Core 的授权状态。
