# FinSAO 前端与后端联调

`demo-final/` 是同学提供的零依赖单页前端。本次接入保留了原有视觉和 Banking Core 业务流程，并连接当前仓库的两个后端进程：

```text
浏览器 http://127.0.0.1:5173
  ├─ /api/core/*  → Banking Core http://127.0.0.1:8000
  └─ /api/agent/* → Agent API    http://127.0.0.1:8100
```

前端服务负责同源代理，因此不需要放宽后端 CORS。Jev 未接入、未调用，也不影响现有功能；当前 `.env` 使用 `AGENT_ROUTING_MODE=llm_only`，安全输入先经 LLM 生成结构化意图和候选参数，执行仍由 `PlanVerifier + ToolGateway` 控制。`RuleRouter` 保留在代码中，便于之后对照延迟和效果，但当前不承担正常业务路由。

## 前置条件

- Python 3.11+，仓库依赖已经安装到 `.venv`。
- PostgreSQL 已启动并已执行迁移、种子脚本。
- Node.js 18+；前端没有 npm 依赖，不需要 `npm install`。
- 根目录 `.env` 至少设置：

```dotenv
APP_ENV=development
DATABASE_URL=postgresql+psycopg://banking:banking@localhost:5432/banking
DEVELOPMENT_USER_ID=<演示用户 UUID>
AGENT_DEVELOPMENT_USER_ID=<与 DEVELOPMENT_USER_ID 相同的 UUID>
MOCK_MFA_CODE=123456
BANKING_BASE_URL=http://127.0.0.1:8000
BANKING_SERVICE_TOKEN=development-only
AGENT_API_TOKEN=development-agent-only
MODEL_PROVIDER=deepseek
AGENT_ROUTING_MODE=llm_only
```

生成确定性的 Lin 演示用户 UUID：

```powershell
uv run python -c "from scripts.seed_demo_data import stable_id; print(stable_id('user:lin'))"
```

身份只由 Core/Agent 服务端环境变量注入。浏览器请求不能提交或覆盖 `user_id`、风险等级、MFA、approval 或授权引用。Node 代理会覆盖浏览器提供的 `Authorization`，分别注入 Core 和 Agent 的开发服务令牌；示例值只能用于本机开发，部署前必须替换。

## 启动顺序

在仓库根目录分别打开三个终端。

### 1. Banking Core

```powershell
uv run alembic upgrade head
uv run python -m scripts.seed_demo_data
uv run uvicorn banking_core.app.main:app --host 127.0.0.1 --port 8000
```

检查：`http://127.0.0.1:8000/health`。

### 2. Agent API

```powershell
uv run uvicorn agent.app:app --host 127.0.0.1 --port 8100
```

检查：`http://127.0.0.1:8100/openapi.json`。

### 3. 前端

```powershell
cd frontend/demo-final
node server.mjs
```

打开 `http://127.0.0.1:5173`。页面顶部应显示“Core 已连接”和“Agent 已连接”。

可覆盖默认地址：

```powershell
$env:CORE_BACKEND_URL = "http://127.0.0.1:8000"
$env:AGENT_BACKEND_URL = "http://127.0.0.1:8100"
$env:PORT = "5173"
node server.mjs
```

兼容旧变量 `BACKEND_URL`，但新配置建议使用含义更明确的 `CORE_BACKEND_URL`。

## 接入行为

- 账户、余额、流水、转账、预算、订阅、卡片、理财及审批/MFA 页面调用真实 Banking Core。
- AI 助手调用 `POST /api/agent/tasks`，请求包含稳定的浏览器会话 UUID，但不包含用户身份或授权字段。
- 助手会发送最近的对话历史；只有带 `[CLARIFICATION]` 标记的未完成澄清链会参与 Slot 合并，已完成任务不会污染新请求。
- 当前 Agent 完成请求时，前端展示后端 `TaskPlan`、工具步骤和 Banking Core 结果。
- 当前 Agent 返回 `NEEDS_CLARIFICATION` 时，前端展示结构化确认表单。账户与联系人由 Core 的只读工具提供选项，模型推断值标为“待确认”。
- 点击“确认并继续”会发送严格的结构化 `confirmation`，不会把表单再次交给 LLM 解释；因此确认值不会反复被标记为模型推断并循环弹窗。
- 首次向新收款人转账时，在“转账”页填写姓名和完整收款账号；Core 验证并保存后，后续聊天转账可以按姓名或昵称自动匹配。完整账号不会通过聊天 Prompt 发送给 LLM。
- 转账页的“查看 10 个虚构演示收款账号”可展开测试账号清单；若数据库早于该功能创建，请重新运行 `uv run python -m scripts.seed_demo_data`。
- 密码、验证码、CVV 和完整卡号在浏览器与 Agent 请求契约两层阻止，不会进入外部 LLM；MFA 仍只提交给 Core 的独立验证接口。
- `WAITING_APPROVAL` 或 `FAILED` 不会自动重放，防止重复草稿或重复写入；用户转到对应业务页面完成显式确认/MFA。
- Agent 不可用时，业务页面仍可使用 Core，但助手不会在浏览器本地执行银行操作。
- Core 不可用时会进入内置演示模式。演示模式不写数据库，不能当作后端联调成功的证据。

右上角“JSON 日志”显示最多 40 次请求/响应，并隐藏授权引用、六位 MFA 验证码及收款账号主体（只保留尾号）。

## 当前支持范围

| 页面/能力 | 后端来源 | 状态 |
|---|---|---|
| 账户、余额、流水及分类修正 | Banking Core | 已接入 |
| 转账草稿、Yellow/Red 审批、提交及状态查询 | Banking Core | 已接入 |
| 预算、消费分析、订阅与周期扣费线索 | Banking Core | 已接入 |
| 卡片冻结/解冻/挂失/限额 | Banking Core | 已接入 |
| 风险测评、产品比较、申购/赎回 | Banking Core | 已接入 |
| Agent 持久任务、计划及结果 | Agent API + LangGraph | 已接入 |
| Jev 路由 | 无 | 按要求暂不接入，保持可插拔 |
| 储蓄罐 | Banking Core + Typed Tools | 虚拟分配模式；持久化目标和历史，但不移动账户资金 |
| 语音 | 无 | 尚未接入 |

## 验证

前端代理和脚本语法测试：

```powershell
node --test frontend/demo-final/server.test.mjs
node --check frontend/demo-final/server.mjs
```

后端相关验证：

```powershell
uv run pytest tests/test_agent_api.py tests/test_agent_routing_planning.py -q
uv run ruff check agent banking_core tests
```

`server.test.mjs` 会启动隔离的 Core/Agent 假服务，验证：页面可读取、查询字符串/请求体原样转发、Core 与 Agent 不串线、代理覆盖并注入对应服务令牌、Agent OpenAPI 探测路径正确，以及未知前端路由返回 404。

## 常见问题

- **页面显示 Core 演示模式**：确认 8000 端口和 `/health`，并检查 `DEVELOPMENT_USER_ID`。
- **页面显示 Agent 未连接**：确认 8100 端口和 `AGENT_DEVELOPMENT_USER_ID`；它应与 Core 演示用户一致。
- **Agent 能连通但工具调用失败**：检查 `BANKING_BASE_URL` 和 Core/Agent 的 `BANKING_SERVICE_TOKEN` 配置是否一致。
- **Red 操作无法验证**：检查 `MOCK_MFA_CODE`，演示默认使用六位数字 `123456`。
- **Durable task 接口失败**：确认 `AGENT_DATABASE_URL` 指向已迁移的 PostgreSQL；若设置了 `AGENT_CHECKPOINT_DATABASE_URL`，还要确认 LangGraph checkpoint 数据库可连接。
- **所有输入都只返回安全追问**：`llm_only` 必须将 `MODEL_PROVIDER` 设置为 `deepseek`、`qwen` 或 `local` 并配置凭据；Provider 不可用时不会退回业务规则执行。
- **端口已占用**：用 `PORT`、`CORE_BACKEND_URL`、`AGENT_BACKEND_URL` 覆盖默认值。

不要对含有真实银行信息的数据库运行演示重置命令。当前项目只应使用虚构比赛数据。
