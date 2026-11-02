[中文](README.md) | [English](README.en.md)

<div align="center">
  <img src="image.png" alt="Aegis Logo" width="160" />
  <h1>Aegis</h1>
  <p>让银行智能体的每一步都可核验、可审批、可恢复</p>
</div>

Aegis 是面向比赛、教学和原型验证的模拟银行智能体系统。用户既可以使用结构化页面，也可以用自然语言提出多项需求。模型负责理解和建议；独立的 Banking Core 负责账户事实、资源归属、风险审批和资金提交。仓库仅使用虚构用户与模拟资金，不连接真实支付网络。

> 当前定位是可验证原型，不是生产银行系统。TLS、真实身份认证、真实 MFA、密钥托管和生产级监控需要由部署环境补充。

## 系统能做什么

- 查询账户、余额、流水、消费分析、预算、订阅、卡片、理财和储蓄目标。
- 将一次自然语言请求拆成最多五个有依赖关系的任务项，并在多轮对话中分别澄清、确认和恢复。
- 对“先查活期余额，再把 10% 转给妈妈”先取得可信余额，再由模型提出百分比与余额引用，服务端用 `Decimal` 计算金额，最后要求用户确认。
- 将已保存收款人的临时候选交给模型排序；服务端验证候选 key 后才映射到真实账户 ID。
- 通过 Core 的 Green / Yellow / Red 策略完成读取、明确确认或模拟 MFA，并以一次性授权提交写操作。
- 保存 Task Bundle、持久任务、事件、Core 审计和 LangGraph checkpoint，便于恢复与对账。

当前边界：自然语言创建或存入储蓄罐的任务项会标记为 `DEFERRED_UNSUPPORTED`，同一任务束中的其他任务仍可继续；结构化储蓄罐页面和 Core 接口不受影响。语音与票据能力依配置和外部服务而定。

## 架构概览

```mermaid
flowchart LR
    U[用户] --> PWA[Aegis PWA<br/>React / Vite / Capacitor]
    PWA -->|/api/agent/*| PX[Node 代理<br/>注入 Agent 服务令牌]
    PWA -->|/api/core/*| PX
    PX --> AG[Agent Service<br/>任务拆解与编排]
    PX --> CORE[Banking Core<br/>金融事实与策略]
    AG -->|注册工具 + 服务令牌| CORE
    AG -.可选.-> LLM[主 LLM]
    AG -.可选.-> JEV[Jev 分类 / 复核]
    AG --> APG[(Agent 状态库)]
    AG --> CPG[(LangGraph checkpoint)]
    CORE --> FPG[(金融数据库 / 账本)]
```

浏览器不持有 Core 或 Agent 服务令牌。Node 代理覆盖来自浏览器的 `Authorization`；Agent 只通过注册工具调用 Core，不直接写金融 ORM。三个 PostgreSQL 职责可以位于同一实例，但逻辑职责不同。详见[总体架构](documents/Architecture.md)和[术语表](GLOSSARY.md)。

## 本地启动

### 1. 准备环境

要求 Python 3.12、Node.js 22.12+ 和 PostgreSQL 16。Docker Desktop 仅用于便捷启动数据库。

```bash
cp .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
docker compose up -d db
```

如果 Python 服务运行在宿主机，而 PostgreSQL 运行在 Docker 中，请在 `.env` 使用：

```dotenv
DATABASE_URL=postgresql+psycopg://banking:banking@127.0.0.1:5432/banking
AGENT_DATABASE_URL=postgresql+psycopg://banking:banking@127.0.0.1:5432/banking
AGENT_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@127.0.0.1:5432/banking
```

空字符串不是 UUID。若不启用独立标注身份，应删除 `LABELING_SERVICE_USER_ID` 或保持代码支持的空值配置；不要把无效文本填入 UUID 字段。

### 2. 迁移和演示数据

```bash
python -m alembic upgrade head
python -m scripts.seed_demo_data
python -m alembic current
```

代码与数据库迁移必须同步。出现 `relation ... does not exist` 或 `column ... does not exist` 时，先确认命令与服务读取的是同一个 `DATABASE_URL` / `AGENT_DATABASE_URL`，再执行迁移；不要手工只补单列或单表。

### 3. 启动三个进程

```bash
# 终端 1
source .venv/bin/activate
python -m uvicorn banking_core.app.main:app --host 127.0.0.1 --port 8000

# 终端 2
source .venv/bin/activate
python -m uvicorn agent.app:app --host 127.0.0.1 --port 8100

# 终端 3
cd frontend/aegis-pwa
npm ci
npm run build
npm run serve
```

打开 <http://127.0.0.1:5174>。`docker compose up` 当前只编排 PostgreSQL 和 Banking Core；Agent 与 PWA 仍需单独启动。前端 Node 进程不会自动读取仓库根目录 `.env`，自定义令牌时请在启动它前设置 `BANKING_SERVICE_TOKEN` 与 `AGENT_API_TOKEN`。

Windows PowerShell 使用 `py -3.12 -m venv .venv`、`.\\.venv\\Scripts\\Activate.ps1` 和 `Copy-Item .env.example .env`，其余 Python 命令相同。

### 4. 健康检查

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8100/openapi.json
curl http://127.0.0.1:5174/api/agent/openapi.json
```

## 一次请求如何执行

1. PWA 将当前消息、会话 ID 和可选的卡片确认发送到 `/agent/bundles/turns`。
2. `TaskDecomposer` 对简单高置信请求使用可选 Jev 快速路径；复杂请求由主 LLM 输出最多五个结构化任务和原文依据。
3. `ConversationOrchestrator` 持久化任务束，按依赖逐项执行。缺字段时只澄清当前任务项；用户确认必须绑定到同一个 item。
4. `AgentService` 验证参数来源、意图允许的工具和 DAG。模型推断的金融写入字段不能绕过确认。
5. Agent 通过 `ToolGateway` 调用 Core。Core 重新检查身份、所有权、状态、精确负载和风险等级。
6. Yellow 操作取得明确确认；Red 操作还完成模拟 MFA。Core 签发并消费短期、一次性、负载绑定的授权。
7. 只有 Core 提交事务并返回完成状态后，界面才显示成功；超时或未知结果进入查询与对账路径。

## 风险等级

| 等级 | Core 行为 | 典型操作 |
| --- | --- | --- |
| Green | 身份与所有权检查后读取 | 余额、流水、账单、投资收益查询 |
| Yellow | 明确确认 | 当日已保留和已提交转出累计不超过 CNY 1,000；卡片冻结/解冻/限额；订阅取消；不超过 CNY 1,000 的储蓄存入 |
| Red | 明确审批 + 模拟 MFA | 超过上述阈值的转账或储蓄存入、挂失、理财申购/赎回 |

转账累计按 `Asia/Shanghai` 业务日计算，并包含待授权草稿。审批、参数确认和最终提交是三个不同状态，见[术语表](GLOSSARY.md)。

## 配置模型服务

默认 `MODEL_PROVIDER=offline`，可配置 DeepSeek、Qwen 或 OpenAI 兼容的本地服务。Jev 和隐私代理均为可选能力：

```dotenv
MODEL_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
JEV_ENABLED=true
JEV_API_KEY=...
PRIVACY_BROKER_ENABLED=true
```

Jev 可参与简单意图分类、消费分类和可选的计划复核；不可用或低置信时系统转向主 LLM 或澄清，不把 Jev 当作金融授权者。隐私代理只做尽力脱敏，密码、验证码、CVV 和完整卡号仍由确定性输入防线直接拒绝。

## 验证

```bash
python -m pytest
python -m ruff check .
python -m mypy

cd frontend/aegis-pwa
npm run typecheck
npm test
npm run build
```

2026-11-02 的最近一次完整 Python 回归结果为 `142 passed, 12 skipped`；跳过项是未配置独立 `DATABASE_TEST_URL` 的 PostgreSQL 集成测试。前端 16 项测试、类型检查和生产构建在同轮开发中通过。测试结果是当时快照，不代表生产认证。`DATABASE_TEST_URL` 必须指向可重置的独立测试库。

## 文档导航

| 文档 | 关注点 |
| --- | --- |
| [文档索引](documents/README.md) | 推荐阅读顺序与文档职责 |
| [总体架构](documents/Architecture.md) | 服务、数据流、持久化与部署边界 |
| [核心算法](documents/Algorithm.md) | 任务拆解、槽位来源、计算、计划和恢复 |
| [安全设计](documents/Security.md) | 信任边界、审批授权、隐私、审计与限制 |
| [术语表](GLOSSARY.md) | 中英文概念和状态区分 |

## 仓库结构

```text
agent/                  自然语言、任务束与执行编排
agent_tools/            Agent 到 Core 的类型化工具网关
agent_persistence/      Agent 会话、任务束、任务和事件
banking_core/           金融领域、API、策略、事务和账本
frontend/aegis-pwa/     React PWA、Node 代理与 Capacitor 外壳
migrations/             Core 与 Agent 数据库迁移
tests/                  Python 单元与集成测试
documents/              当前架构、算法和安全文档
```

