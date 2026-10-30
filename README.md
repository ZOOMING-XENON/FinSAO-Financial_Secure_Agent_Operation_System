# FinSAO：安全可控的 AI 银行助手演示系统

FinSAO 是一个面向教学、比赛和原型验证的 AI 银行助手。它把“理解自然语言”和“执行金融业务”严格拆成不同层：大语言模型负责识别用户意图、提出候选参数和候选任务计划；真正的账户、转账、预算、银行卡、理财和审批操作，只能由确定性的 Banking Core 完成。

这不是一个真实银行系统，也不会连接真实支付网络。仓库中的用户、账户、银行卡、资金和理财产品都是虚构数据。

## 1. 最先需要理解的三个部分

| 部分 | 主要职责 | 明确不能做什么 |
|---|---|---|
| 前端与 Node 代理 | 展示页面、收集确认、把请求转发到两个后端 | 浏览器不持有服务令牌；前端不判断银行意图，也不直接修改数据库 |
| Agent API | 调用 LLM、维护上下文、生成和验证 DAG、暂停/恢复任务 | 不能自行建立用户身份，不能绕过审批，不能直接写金融数据库 |
| Banking Core | 保存金融事实、执行业务规则、审批/MFA、记账和审计 | 不相信 LLM 的结论，不接受模型提供的身份或授权 |

一句话概括：**LLM 可以建议“做什么”，Agent 决定“是否允许这样计划”，Banking Core 决定“这笔业务是否真的可以发生”。**

## 2. 当前系统架构

```mermaid
flowchart TB
    U[用户] --> B[浏览器单页前端]
    B --> N[Node 同源代理 :5173]

    N -->|结构化业务页面 /api/core| C[Banking Core :8000]
    N -->|自然语言 /api/agent| A[Agent API :8100]

    A --> P[敏感信息与注入检查]
    P --> L[LLM 意图识别与候选 Slots]
    L --> S[SlotTracker 参数与来源追踪]
    S -->|缺失或模型推断| F[前端确认表单]
    F --> A
    S -->|参数已确认| D[候选 TaskPlan / DAG]
    D --> V[CapabilityBroker + PlanVerifier]
    V --> G[Typed ToolGateway]
    G --> C

    A --> LG[LangGraph 任务状态机]
    LG --> CP[(PostgreSQL Checkpoint)]
    A --> AT[(Agent Tasks / Events)]

    C --> SEC[所有权、风险、Approval、MFA、幂等]
    SEC --> SV[确定性业务 Service]
    SV --> DB[(PostgreSQL 金融数据与双重记账)]
    SV --> AU[(Audit Events)]

    J[Jev Router] -. 当前未启用 .-> A
```

系统有两条入口：

1. 账户、转账、预算等结构化页面直接通过 Node 代理调用 Banking Core。这些页面已经明确知道要调用哪个业务接口，不需要 LLM。
2. “AI 助手”中的自然语言先进入 Agent。Agent 完成理解、补充参数、计划验证后，才可能通过 Typed Tool 调用 Banking Core。

Node 代理分别为 Core 和 Agent 注入服务端令牌，并覆盖浏览器伪造的 `Authorization`。这样浏览器不需要持有后端服务密钥，也不需要开放跨域访问。

更详细的架构图和规划对照见 [architecture.md](architecture.md)。

## 3. 一条自然语言请求是怎样执行的

以“我下个月想预留一些预算给妈妈过生日，大概 1000 元”为例：

1. 前端发送当前消息、会话 UUID 和有限的对话历史。
2. Agent 在调用模型前检查密码、验证码、CVV、完整卡号和明显的提示注入。
3. 默认配置为 `AGENT_ROUTING_MODE=llm_only`；普通业务文本不先进入 `RuleRouter`，LLM 直接返回严格 JSON：`intent + confidence + proposed_slots + slot_evidence`。
4. `SlotTracker` 不再使用业务关键词决定 LLM 路径的语义；它只验证模型引用的证据是否确实出现在当前用户原文中，并标记用户明确输入、工具验证、系统常量或模型推断等来源。
5. “妈妈生日”和“下个月”可以作为模型推断值预填；没有可验证原文证据的金融参数不能直接执行，必须由用户确认。
6. 用户确认后，前端发送结构化 `confirmation`；这些字段被标记为用户明确确认。随后 LLM 在最小 Tool Schema 集合内提出候选 DAG，`CapabilityBroker` 和 `PlanVerifier` 确定性检查工具、参数来源、依赖关系和权限；模型规划不可用时只能回退到基于已确认数据的确定性计划。
7. `ToolGateway` 用 Pydantic Schema 校验参数，通过 HTTP 调用 Banking Core。
8. Banking Core 独立检查身份、资源所有权、风险、审批、MFA、幂等和业务状态，然后在数据库事务中执行。
9. Agent 的最终回答只能根据真实 `ToolResult` 生成，不能仅凭 LLM 文本声称“创建成功”或“转账成功”。

如果参数不足，任务停在 `NEEDS_CLARIFICATION`；如果需要审批，LangGraph 停在 `WAITING_APPROVAL`；用户确认后使用同一任务和 PostgreSQL checkpoint 恢复执行。

## 4. LLM 在系统中具体做什么

LLM 目前有两个可替换用途：

- 路由与参数候选：把自然语言转换为 `intent + confidence + proposed_slots`。
- 候选计划：在允许的 Tool Schema 范围内提出 TaskPlan/DAG。

LLM 不负责：

- 验证用户身份；
- 判断账户余额或数据库事实；
- 生成有效审批、MFA 或授权引用；
- 绕过 Tool 白名单；
- 直接访问 Banking Core 或 PostgreSQL；
- 决定一笔金融操作最终成功。

支持 DeepSeek、Qwen 和本地 OpenAI-compatible 模型。Provider 不可用、超时、输出结构非法或置信度不足时，`llm_only` 模式会安全停止并请求澄清，不会悄悄使用业务关键词规则执行操作。`RuleRouter` 仍保留用于测试和以后进行 `hybrid` 对照；Jev 保持可插拔，但当前没有接入或调用。

## 5. 已实现功能

### 5.1 账户与流水

- 查看本人账户、余额和分页流水；
- 按日期、分类、商户、金额筛选；
- 修改消费分类；
- 所有金额使用 `Decimal` 与 PostgreSQL `NUMERIC(18,2)`，不使用二进制浮点数。

### 5.2 转账与收款人

- 首次转账在结构化页面填写收款人姓名和完整收款账号；
- 种子数据提供爸爸、妈妈等 10 个虚构收款账户，用于展示首次录入流程；
- Core 验证模拟账户后保存本人收款人映射；
- 后续转账可按姓名或昵称自动匹配，聊天表单无需用户复制 UUID；
- 创建转账草稿、风险审批、MFA、提交和状态对账；
- 幂等键防止重复创建，数据库行锁防止并发超支；
- 每次真实余额变化都生成平衡的借贷分录。

### 5.3 消费、预算和订阅

- 月度消费汇总、分类统计和周期消费线索；
- 创建、更新、查询预算；
- 自定义预算类别和月份选择；
- 查询订阅并经过授权取消。

### 5.4 银行卡

- 查询银行卡；
- 调整限额；
- 冻结、解冻和挂失；
- 高风险挂失要求 MFA，并验证状态迁移。

### 5.5 理财

- 查看、比较虚构理财产品；
- 风险测评和适当性检查；
- 查询持仓；
- 申购和支持范围内的赎回；
- 申购/赎回属于 Red 操作，必须通过模拟 MFA。

### 5.6 储蓄罐

- 创建储蓄目标、查询列表、记录虚拟贡献；
- `saved_amount` 和贡献历史会持久化；
- 当前是“虚拟分配”模式，不改变账户余额，也不生成真实转账。

### 5.7 Agent 任务

- 多轮澄清和结构化确认表单；
- LangGraph DAG 执行、暂停、恢复、取消和人工接管；
- PostgreSQL checkpoint；
- 独立的公开任务状态和事件记录；
- SSE 任务事件流；
- 只提供建议、不自动执行金融写入的主动提醒框架。

## 6. 安全是怎样保证的

本项目采用“模型不可信、客户端不可信、金融事实只能来自 Core”的原则。

### 6.1 身份与服务边界

- Core 和 Agent 使用不同 Bearer 服务令牌；
- Node 代理在服务端注入令牌，浏览器不能覆盖；
- 开发身份来自服务端环境变量，不接受请求或模型提供的 `user_id`；
- Docker 只把 PostgreSQL 和 Core 绑定到 `127.0.0.1`。

开发令牌和固定演示用户不是生产认证。真实部署必须换成 OIDC/JWT、短期服务凭据或 mTLS，并使用密钥托管。

### 6.2 敏感信息不应进入 LLM

浏览器和 Agent 请求契约都会阻止明显的密码、OTP/MFA 验证码、CVV/CVC 和完整银行卡号。首次收款账号通过结构化转账页只发送给 Banking Core，不放入聊天 Prompt；前端 JSON 日志只保留账号尾号。

当前检查是确定性正则，不是完整 DLP。普通聊天内容、用途、金额、日期和用户主动输入的其他未识别信息仍可能发送给配置的外部模型，因此不能在聊天框输入真实秘密。

### 6.3 LLM 输出不能直接执行

- LLM 输出必须通过严格 Pydantic JSON Schema；
- 身份、风险等级、审批状态、MFA、授权引用等字段禁止由模型提供；
- 模型推断的金融参数标记为 `MODEL_INFERRED`，写操作前必须由用户确认；
- `CapabilityBroker` 按意图只下发最小工具集合；
- `PlanVerifier` 拒绝未知工具、循环依赖、越权工具和不可信参数；
- `ToolGateway` 在执行前再次验证 Tool 输入与输出。

### 6.4 风险、审批与 MFA

| 等级 | 示例 | 要求 |
|---|---|---|
| Green | 查询账户、余额、历史收款人 | 认证后可读，不需要审批 |
| Yellow | 当日累计转出不超过 CNY 1,000、取消订阅 | 明确确认 |
| Red | 累计转出超过 CNY 1,000、挂失、理财申购/赎回 | 模拟 MFA |

日界线使用 `Asia/Shanghai`。未过期草稿和已完成转账都计入当日累计额度。授权 grant 绑定用户、操作、资源、收付款账户、金额、币种和规范化请求哈希，具有有效期且只能使用一次；提交事务中还会重新检查业务条件。

模拟 MFA 只保存带随机盐的 PBKDF2 哈希，限制尝试次数、防止重放，并可触发临时安全锁。它用于演示安全流程，不等同于真实短信或认证器 MFA。

### 6.5 数据正确性与可恢复性

- 金融写操作只在 Banking Core 数据库事务内发生；
- 双重记账要求总借方等于总贷方；
- 已入账 ledger entry 由 PostgreSQL 触发器禁止更新和删除；
- 幂等键避免网络重试造成重复业务；
- 行锁处理并发转账；
- `X-Trace-Id`、audit events、Agent events 和 checkpoint 支持追踪与恢复；
- 网络超时后优先查询状态，不使用新幂等键盲目重试。

## 7. 数据和持久化边界

同一个 PostgreSQL 实例中保存三类数据，但职责不同：

- Banking Core 表：用户、账户、收款人、交易、ledger、预算、订阅、卡片、理财、审批、MFA、审计、储蓄罐；
- Agent 公开状态表：session、task、event、主动提醒订阅；
- LangGraph checkpoint 表：图执行到哪个节点、暂停数据和恢复状态。

LLM 不连接数据库。`agent_tools` 也不导入 Banking Core ORM，只能通过有类型的 HTTP 接口访问 Core。

## 8. 本地运行

### 8.1 前置条件

- Python 3.11 或更高；
- PostgreSQL 16（推荐使用仓库的 Docker Compose）；
- Node.js 18 或更高；前端没有 npm 依赖，不需要 `npm install`；
- 可选的 DeepSeek、Qwen 或本地模型。

### 8.2 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

也可以使用项目元数据安装开发依赖：

```powershell
python -m pip install -e ".[dev]"
```

如果 Core 在宿主机运行，把 `.env` 中的数据库主机从 `db` 改为 `localhost`：

```dotenv
DATABASE_URL=postgresql+psycopg://banking:banking@localhost:5432/banking
AGENT_DATABASE_URL=postgresql+psycopg://banking:banking@localhost:5432/banking
AGENT_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking
```

### 8.3 准备数据库和演示数据

```powershell
docker compose up -d db
uv run alembic upgrade head
uv run python -m scripts.seed_demo_data
```

种子脚本可重复执行，并生成固定的虚构 UUID。查看 Lin 演示用户 ID：

```powershell
uv run python -c "from scripts.seed_demo_data import stable_id; print(stable_id('user:lin'))"
```

将该值同时配置为 `DEVELOPMENT_USER_ID` 和 `AGENT_DEVELOPMENT_USER_ID`。

### 8.4 配置模型

当前推荐的实验配置：

```dotenv
MODEL_PROVIDER=deepseek
AGENT_ROUTING_MODE=llm_only
DEEPSEEK_API_KEY=<你的 API Key>
```

也可选择 `qwen`、`local`。`MODEL_PROVIDER=offline` 时没有在线模型，`llm_only` 请求会安全返回澄清，不能完成自然语言意图识别。

### 8.5 启动三个进程

终端一：

```powershell
uv run uvicorn banking_core.app.main:app --host 127.0.0.1 --port 8000
```

终端二：

```powershell
uv run uvicorn agent.app:app --host 127.0.0.1 --port 8100
```

终端三：

```powershell
cd frontend/demo-final
node server.mjs
```

打开 `http://127.0.0.1:5173`。页面顶部应显示“Core 已连接”和“Agent 已连接”。Core Swagger 在 `http://127.0.0.1:8000/docs`，Agent OpenAPI 在 `http://127.0.0.1:8100/openapi.json`。

前端的详细联调与故障排查见 [frontend/README.md](frontend/README.md)。

## 9. 主要 API

| 领域 | 代表接口 |
|---|---|
| 健康检查 | `GET /health`、`GET /health/db` |
| 账户 | `GET /accounts`、余额和流水 |
| 收款人 | `GET/POST /beneficiaries`、`GET /beneficiaries/resolve` |
| 转账 | 创建草稿、查询状态、提交 |
| 审批/MFA | `/security/approvals`、decision、challenge、verify |
| 消费与预算 | spending、monthly summary、budgets |
| 订阅 | list、detect recurring、cancel |
| 卡片 | list、status、limit、freeze、unfreeze、report lost |
| 理财 | products、compare、assessment、holdings、subscribe、redeem |
| 储蓄罐 | `/savings-pots` 和 contributions |
| Agent | `/agent/requests`、`/agent/tasks`、resume/cancel/takeover/events |

API 错误统一为 `{ "code": "...", "message": "..." }`。金额在 JSON 中使用十进制字符串。

## 10. 仓库结构和逐文件说明

下面列出人工维护的源码、配置、测试和说明文件。`__init__.py` 主要用于声明 Python package，本身通常没有业务逻辑；生成的图片和 JSONL 数据在最后按组说明。

### 10.1 根目录

| 文件 | 作用 |
|---|---|
| `README.md` | 当前总览、架构、安全、运行方式和仓库导航 |
| `architecture.md` | 当前实际架构图与早期规划架构的对照 |
| `AGENT.md` | 仓库内 Agent 开发约定 |
| `dev_plan.md` | 分阶段开发计划和验收记录 |
| `building_banking_core_and_tool_use.md` | Banking Core 与 Tool Use 的早期设计说明 |
| `.env.example` | 可复制的环境变量模板，不应存放真实密钥 |
| `.gitignore` | Git 忽略规则 |
| `pyproject.toml` | Python 包、依赖、pytest、Ruff 和 mypy 配置 |
| `requirements.txt` | 便于传统 pip 安装的 Python 依赖；Node.js 仅作为系统依赖说明 |
| `uv.lock` | uv 生成的精确版本锁文件 |
| `alembic.ini` | Alembic 数据库迁移配置 |
| `docker-compose.yml` | 启动 PostgreSQL 与可选 Core 容器，端口仅绑定本机 |
| `Dockerfile` | 构建 Banking Core Python 容器 |

`workspace/` 中的任务文档是开发过程记录，不属于运行时依赖；例如 `workspace/task1027.md` 记录了当前功能迭代和决策。

### 10.2 `agent/`：自然语言理解与安全编排

| 文件 | 作用 |
|---|---|
| `app.py` | Agent FastAPI 入口；装配 Provider、Router、Planner、Gateway、LangGraph、任务仓库和认证依赖 |
| `config.py` | Agent 环境变量配置，包括模型、路由模式、Core 地址、令牌和数据库 |
| `contracts.py` | Agent 请求、响应、TaskPlan、ToolCall、澄清表单等严格数据契约 |
| `privacy.py` | 在外部模型调用前阻止明显的密码、验证码、CVV 和完整卡号 |
| `routing.py` | Intent/Route 枚举及保留的确定性 `RuleRouter`；还承担提示注入快筛 |
| `hybrid.py` | `llm_only`/`hybrid` 路由、结构化 LLM 意图输出和 LLM 候选 Planner |
| `providers.py` | DeepSeek、Qwen、本地 OpenAI-compatible Provider 与错误/重试封装 |
| `factory.py` | 根据配置创建对应模型 Provider，避免上层依赖厂商细节 |
| `context.py` | `SlotTracker`；在 LLM 主路径验证候选值的原文证据与事实来源，并为对照实验保留确定性提取器 |
| `capabilities.py` | `CapabilityBroker`；按 Intent 和执行阶段提供最小 Tool action 集合 |
| `planning.py` | 确定性 Baseline Planner 和 PlanVerifier，验证 DAG、参数来源和工具权限 |
| `service.py` | 单次 Agent 主流程；组织路由、slot、候选查询、表单、计划、执行和响应 |
| `responses.py` | 只根据经过验证的 ToolResult 生成面向用户的结果文本 |
| `graph.py` | LangGraph 在线状态机，处理 ingest、路由、执行、interrupt 和 resume |
| `checkpoints.py` | Windows 兼容的 PostgreSQL checkpoint 异步适配器 |
| `durable.py` | 持久任务状态、事件、恢复、取消、人工接管和对账编排 |
| `proactive.py` | 用户主动订阅的建议引擎；只能产生建议，不能自动执行金融操作 |
| `jev.py` | 可选 Jev 路由边界、超时、熔断和可信字段限制；当前默认不启用 |
| `__init__.py` | Agent package 标识 |

### 10.3 `agent_persistence/`：Agent 公开任务持久化

| 文件 | 作用 |
|---|---|
| `models.py` | Agent session、task、event 和主动提醒订阅的 SQLAlchemy 模型 |
| `repository.py` | 创建/更新任务、追加事件、并发版本控制、主动提醒频率控制 |
| `__init__.py` | 对外导出持久化组件 |

这些表与 LangGraph checkpoint 不同：前者是稳定的公开任务视图，后者是图运行时的内部恢复状态。

### 10.4 `agent_tools/`：Agent 到 Core 的有类型边界

| 文件 | 作用 |
|---|---|
| `contracts.py` | Tool 抽象类、ExecutionContext、ToolResult 和标准状态 |
| `registry.py` | Tool 注册、查找和按 action 列出允许工具 |
| `gateway.py` | 验证 Tool 输入/输出、标准化错误和执行审计 |
| `client.py` | 带服务认证、trace、超时和幂等语义的异步 HTTP 客户端 |
| `tools.py` | 账户、流水、历史收款人和转账相关 Tool |
| `analytics_tools.py` | 消费分析、预算和订阅 Tool |
| `cards_wealth_tools.py` | 卡片与理财 Tool |
| `savings_tools.py` | 储蓄罐 Tool |
| `__init__.py` | Tool package 标识 |

此目录禁止直接访问 ORM 或数据库，确保 Agent 不能绕过 Core 业务规则。

### 10.5 `banking_core/app/`：金融事实与规则

#### 应用入口和配置

| 文件 | 作用 |
|---|---|
| `main.py` | Banking Core FastAPI 入口、路由注册、错误处理和 trace middleware |
| `config.py` | Core 数据库、演示身份、MFA 和服务令牌配置 |
| `__init__.py` | 应用 package 标识 |

#### `api/` HTTP 层

| 文件 | 作用 |
|---|---|
| `banking.py` | 账户、余额、流水、收款人和转账接口 |
| `analytics.py` | 消费分析、预算、分类和订阅接口 |
| `cards_wealth.py` | 卡片、风险测评、产品、持仓和理财订单接口 |
| `savings.py` | 储蓄罐及贡献历史接口 |
| `security.py` | Approval、确认、MFA challenge 和 verify 接口 |
| `health.py` | 进程和数据库健康检查 |
| `dependencies.py` | 数据库 Session、服务认证、开发用户和授权验证依赖 |
| `errors.py` | 把领域异常和校验异常转换成统一 API 错误 |
| `__init__.py` | API package 标识 |

#### `domain/` 纯领域类型

| 文件 | 作用 |
|---|---|
| `entities.py` | 不依赖数据库的账户、转账、授权等领域实体与不变量 |
| `enums.py` | Currency、状态、风险等级等枚举 |
| `money.py` | 金额 Decimal 类型、量化和精度约束 |
| `__init__.py` | Domain package 标识 |

#### `schemas/` API 数据契约

| 文件 | 作用 |
|---|---|
| `banking.py` | 账户、收款人、转账请求与响应 Schema |
| `analytics.py` | 消费、预算、订阅 Schema |
| `cards_wealth.py` | 卡片和理财 Schema |
| `savings.py` | 储蓄罐 Schema |
| `security.py` | Approval、MFA 和授权结果 Schema |
| `health.py` | 健康检查 Schema |
| `__init__.py` | Schema package 标识 |

#### `services/` 确定性业务逻辑

| 文件 | 作用 |
|---|---|
| `accounts.py` | 账户所有权、余额、流水查询和过滤 |
| `beneficiaries.py` | 保存、列出和匹配当前用户的收款人 |
| `transfers.py` | 转账草稿状态机、幂等、所有权、锁和提交 |
| `ledger.py` | 平衡借贷分录与余额更新 |
| `analytics.py` | 消费聚合、预算和订阅逻辑 |
| `cards_wealth.py` | 卡片状态、风险测评、适当性、理财订单和持仓 |
| `savings.py` | 储蓄目标和虚拟贡献逻辑 |
| `errors.py` | Core 领域异常类型及 HTTP 语义 |
| `__init__.py` | Service package 标识 |

#### `security/` 授权与风险

| 文件 | 作用 |
|---|---|
| `policy.py` | Green/Yellow/Red 规则和累计转账阈值 |
| `approvals.py` | 创建审批、确认、MFA、grant 绑定、有效期和重放防护 |
| `transfer_authorization.py` | 转账提交时验证授权引用 |
| `models.py` | 安全层内部类型 |
| `__init__.py` | Security package 标识 |

#### `persistence/` 数据访问

| 文件 | 作用 |
|---|---|
| `database.py` | SQLAlchemy Engine、Session factory 和 FastAPI Session 生命周期 |
| `models.py` | 全部 Banking Core ORM 表模型与数据库约束 |
| `repositories.py` | 通用持久化查询与仓库实现 |
| `__init__.py` | Persistence package 标识 |

`banking_core/__init__.py` 标识顶层 Core package。

### 10.6 `migrations/`：数据库演进

| 文件 | 作用 |
|---|---|
| `env.py` | Alembic 运行环境和 SQLAlchemy metadata 连接 |
| `script.py.mako` | 新迁移文件模板 |
| `20261022_0001_initial_schema.py` | 用户、账户、收款人、交易、ledger 和转账草稿基础表 |
| `20261022_0002_security.py` | 审批、MFA、授权和审计表 |
| `20261022_0003_analytics.py` | 预算、订阅和分析相关结构 |
| `20261022_0004_cards_wealth.py` | 卡片、理财产品、测评、订单和持仓 |
| `20261022_0005_ledger_immutability.py` | 禁止修改/删除已入账 ledger 的数据库保护 |
| `20261022_0006_repeatable_approvals.py` | 多次审批与授权生命周期修正 |
| `20261022_0007_wealth_redemption.py` | 理财赎回数据结构 |
| `20261026_0008_agent_tasks.py` | Agent session、task、event 和主动提醒表 |
| `20261027_0009_savings_pots.py` | 储蓄罐与贡献历史表 |

### 10.7 `frontend/`：演示界面

| 文件 | 作用 |
|---|---|
| `README.md` | 前端联调、启动、环境变量和故障排查 |
| `demo-final/index.html` | 当前零依赖单页应用，包含全部页面、确认表单和离线模拟 Core |
| `demo-final/server.mjs` | 静态文件服务器及 Core/Agent 同源反向代理 |
| `demo-final/server.test.mjs` | Node 代理、令牌注入和页面脚本解析测试 |
| `demo-final/README.md` | 原始 demo-final 说明 |
| `demo-final/design/architecture.svg` | 前端设计阶段架构图 |
| `demo-final/design/figma-frames.svg` | Figma 画板参考 |
| `demo-final/design/tokens.json` | 设计 token |
| `demo-final/design/FIGMA.md` | Figma 资产说明 |
| `demo1.html`、`demo2.html` | 早期界面原型，非当前入口 |
| `architecture.svg`、`figma-frames.svg` | 前端早期设计资产 |

### 10.8 `banking_dataset/` 与 `evaluation/`

| 文件/目录 | 作用 |
|---|---|
| `banking_dataset/schema.py` | 银行 Agent 样本和标签 Schema |
| `banking_dataset/generate.py` | 生成固定的合成中文数据集 |
| `banking_dataset/validate.py` | 检查数量、字段、分割和数据泄漏 |
| `banking_dataset/score.py` | Intent、路由、安全等评测指标 |
| `banking_dataset/__init__.py` | Dataset package 标识 |
| `evaluation/dataset/*.jsonl` | train/dev/test 冻结合成样本 |
| `evaluation/dataset/*.json` | JSON Schema 和分割哈希 manifest |
| `evaluation/figures/*.png` | 各阶段测试、延迟、混淆矩阵、UI 等证据图 |
| `evaluation/manifests/*.json` | 本地模型和价格快照 |
| `evaluation/reports/` | 基准测试原始结果与人工审核记录；部分文件可能被 Git 忽略 |
| `outputs/p5-review/` | 人工种子审核表及渲染检查产物 |

### 10.9 `scripts/`：数据、演示和证据生成

| 文件 | 作用 |
|---|---|
| `seed_demo_data.py` | 幂等生成虚构用户、账户、交易、收款人、卡片、预算和理财数据 |
| `demo_tool_calls.py` | 直接演示 Typed Tool 调用 |
| `demo_end_to_end.py` | 演示完整 Core 业务和安全流程 |
| `provider_smoke.py` | 模型 Provider 连通性与结构化输出冒烟测试 |
| `evaluate_p2_baseline.py` | P2 路由和 Planner 基线评估 |
| `benchmark_p6.py` | rule/DeepSeek/Qwen/local 冻结测试基准 |
| `generate_p0_evidence.py` | 生成初始 API、测试和工具覆盖证据 |
| `generate_p3_evidence.py` | 生成 LangGraph 任务和事件证据 |
| `generate_p5_evidence.py` | 生成数据集审核与分布证据 |
| `generate_p6_evidence.py` | 汇总模型准确率、延迟、成本和错误图 |
| `summarize_p4_evidence.py` | 汇总前端桌面/移动端证据 |
| `__init__.py` | Scripts package 标识 |

### 10.10 `shared/`

| 文件 | 作用 |
|---|---|
| `tracing.py` | 在 Core、Agent 和 Tool 调用间绑定/传播 trace ID |
| `__init__.py` | Shared package 标识 |

### 10.11 `tests/`

| 文件 | 主要覆盖 |
|---|---|
| `test_domain.py` | 领域实体、金额和基础不变量 |
| `test_health.py` | 健康检查 |
| `test_phase2_unit.py` | 转账状态机和服务认证基础行为 |
| `test_phase3_security.py` | 风险阈值、审批、MFA 和授权安全 |
| `test_phase4_tools.py` | Tool Registry、Gateway、HTTP 客户端和类型验证 |
| `test_phase5_analytics.py` | 消费、预算、分类和订阅 |
| `test_phase6_cards_wealth.py` | 卡片与理财功能 |
| `test_agent_contracts_providers.py` | Agent 契约与模型 Provider |
| `test_agent_routing_planning.py` | Intent、Slot、能力最小化和 PlanVerifier |
| `test_agent_graph.py` | LangGraph 中断、恢复和状态变化 |
| `test_agent_api.py` | Agent HTTP API、任务和认证 |
| `test_jev_boundary.py` | 可选 Jev 的超时、熔断和权限边界 |
| `test_banking_dataset.py` | 数据集生成、校验和评分 |
| `test_task1027_runtime.py` | 多轮表单、敏感信息、服务令牌、储蓄罐、收款人和当前集成功能 |
| `test_postgres_integration.py` | 真实 PostgreSQL 下的迁移、并发、ledger、审批和幂等集成测试 |

### 10.12 `docs/`：阶段性技术文档

| 文件 | 作用 |
|---|---|
| `README.md` | 文档目录和推荐阅读顺序 |
| `00_baseline_and_documentation_index.md` | 基线状态、交付物索引和阶段入口 |
| `01_agent_contracts_and_model_providers.md` | Agent 契约、可信边界和模型 Provider |
| `02_planner_and_safe_routing.md` | 路由、Planner、CapabilityBroker 与 PlanVerifier |
| `03_langgraph_durable_execution.md` | LangGraph、checkpoint、任务恢复和事件 |
| `04_frontend_integration_and_demo.md` | 前后端连接和演示流程 |
| `05_banking_agent_dataset.md` | 合成数据集设计、生成与人工审核 |
| `06_llm_baseline_benchmark.md` | 模型基准、指标、延迟、成本和结果解读 |
| `07_jev_router_integration.md` | Jev 可插拔边界设计和未启用状态 |
| `banking_backend_modules.md` | Banking Core 模块说明 |
| `langgraph_integration.md` | LangGraph 与 Typed Tool 的集成说明 |
| `A_manual.md` | 项目操作和演示手册 |

## 11. 测试和质量检查

```powershell
uv run pytest -q
uv run ruff check .
uv run mypy
node --test frontend/demo-final/server.test.mjs
node --check frontend/demo-final/server.mjs
```

当前普通测试结果为 `77 passed, 10 skipped`。跳过的 10 项需要单独配置一次性 PostgreSQL 测试库：

```powershell
$env:DATABASE_TEST_URL = "postgresql+psycopg://banking:banking@localhost:5432/banking_test"
uv run pytest -m postgres
```

这些测试会把目标数据库降级到 Alembic `base`，只能使用可销毁的测试库，绝不能指向有价值的数据。

## 12. 当前限制与正确解读

- 这是比赛/教学原型，不是生产银行系统；
- 开发身份、服务令牌和 MFA 均为本机演示机制；
- 没有真实银行清算、银行卡网络、投资机构或真实客户数据；
- 首次收款账号必须存在于 Mock Banking Core 中，系统不支持真实跨行账户；
- 敏感信息正则不是完整 DLP；
- LLM 的准确性依赖 Provider 和 Prompt，因此所有金融写入仍需要确定性校验；
- Jev 尚未启用；
- 储蓄罐是虚拟目标，不移动真实账户资金；
- PostgreSQL 的锁、触发器和并发语义不能用 SQLite 等价替代。

因此，本项目最重要的成果不是“让 LLM 直接操作银行”，而是展示了一种更安全的组合方式：**让模型负责语言理解，让可验证的软件边界负责权限、资金和最终事实。**
