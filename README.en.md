[中文](README.md) | English

<div align="center">
  <img src="image.png" alt="Aegis Logo" width="160" />
  <h1>Aegis</h1>
  <p>A banking agent whose actions are verifiable, approvable, and recoverable</p>
</div>

Aegis is a simulated banking-agent system for competitions, teaching, and prototyping. Users can use structured screens or express several requests in natural language. Models interpret and propose; an independent Banking Core owns account facts, resource ownership, risk approval, and financial commits. The repository uses fictional users and simulated funds and does not connect to payment networks.

> This is a verifiable prototype, not a production banking system. A real deployment must add TLS, production identity, real MFA, secret management, and production monitoring.

## What it does

- Queries accounts, balances, transactions, spending analytics, budgets, subscriptions, cards, wealth products, and savings goals.
- Decomposes one message into at most five dependency-linked tasks and clarifies, confirms, or resumes each task across turns.
- For “check my checking balance, then send 10% to Mom,” obtains a trusted balance, lets the model propose a percentage and balance reference, calculates with server-side `Decimal`, and requires confirmation.
- Gives the model temporary keys for saved-recipient ranking; the server validates the selected key before mapping it to an actual account ID.
- Applies Core-owned Green / Yellow / Red policy for reads, explicit confirmation, or simulated MFA, then commits writes through a single-use grant.
- Persists Task Bundles, Durable Tasks, events, Core audit records, and LangGraph checkpoints for recovery and reconciliation.

Current boundary: natural-language savings-pot creation and contribution items become `DEFERRED_UNSUPPORTED`, while other items in the same bundle continue. The structured savings UI and Core APIs remain available. Voice and receipt features depend on configuration and external services.

## Architecture at a glance

```mermaid
flowchart LR
    U[User] --> PWA[Aegis PWA<br/>React / Vite / Capacitor]
    PWA -->|/api/agent/*| PX[Node proxy<br/>injects Agent token]
    PWA -->|/api/core/*| PX
    PX --> AG[Agent Service<br/>decomposition and orchestration]
    PX --> CORE[Banking Core<br/>financial facts and policy]
    AG -->|registered tools + service token| CORE
    AG -.optional.-> LLM[Primary LLM]
    AG -.optional.-> JEV[Jev classification / review]
    AG --> APG[(Agent state DB)]
    AG --> CPG[(LangGraph checkpoints)]
    CORE --> FPG[(Financial DB / ledger)]
```

The browser never holds Core or Agent service tokens. The Node proxy overwrites browser-supplied `Authorization`; the Agent calls Core only through registered tools and does not write financial ORM records. The three PostgreSQL responsibilities may share one instance, but they remain logically separate. See [Architecture](documents/Architecture.en.md) and the [Glossary](GLOSSARY.en.md).

## Local setup

### 1. Prepare the environment

Use Python 3.12, Node.js 22.12+, and PostgreSQL 16. Docker Desktop is optional and used here only to start PostgreSQL conveniently.

```bash
cp .env.example .env
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
docker compose up -d db
```

When Python services run on the host and PostgreSQL runs in Docker, use host addresses in `.env`:

```dotenv
DATABASE_URL=postgresql+psycopg://banking:banking@127.0.0.1:5432/banking
AGENT_DATABASE_URL=postgresql+psycopg://banking:banking@127.0.0.1:5432/banking
AGENT_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@127.0.0.1:5432/banking
```

An empty string is not a UUID. If no separate labeling identity is used, remove `LABELING_SERVICE_USER_ID` or rely on the code's supported empty-value behavior; do not place arbitrary text in UUID settings.

### 2. Migrate and seed

```bash
python -m alembic upgrade head
python -m scripts.seed_demo_data
python -m alembic current
```

Code and schema must move together. If a log says a relation or column does not exist, first confirm that migration commands and services use the same `DATABASE_URL` / `AGENT_DATABASE_URL`, then run the migration. Do not patch a single table or column manually.

### 3. Start all three processes

```bash
# terminal 1
source .venv/bin/activate
python -m uvicorn banking_core.app.main:app --host 127.0.0.1 --port 8000

# terminal 2
source .venv/bin/activate
python -m uvicorn agent.app:app --host 127.0.0.1 --port 8100

# terminal 3
cd frontend/aegis-pwa
npm ci
npm run build
npm run serve
```

Open <http://127.0.0.1:5174>. The current Compose file starts PostgreSQL and Banking Core only; start Agent and PWA separately. The frontend Node process does not automatically load the repository-root `.env`. Export `BANKING_SERVICE_TOKEN` and `AGENT_API_TOKEN` before starting it when tokens are customized.

On Windows PowerShell, use `py -3.12 -m venv .venv`, `.\\.venv\\Scripts\\Activate.ps1`, and `Copy-Item .env.example .env`; the remaining Python commands are unchanged.

### 4. Check health

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8100/openapi.json
curl http://127.0.0.1:5174/api/agent/openapi.json
```

## How one request executes

1. The PWA sends the message, session ID, and optional card confirmation to `/agent/bundles/turns`.
2. `TaskDecomposer` may use the optional Jev fast path for a simple, high-confidence request. The primary LLM handles complex input and returns up to five structured tasks with exact evidence.
3. `ConversationOrchestrator` persists the bundle and processes items by dependency. Clarification targets only the active item; confirmation must bind to that same item.
4. `AgentService` checks argument provenance, intent capabilities, and the DAG. Model-inferred fields cannot bypass confirmation for financial writes.
5. Agent calls Core through `ToolGateway`. Core rechecks identity, ownership, state, exact payload, and policy.
6. Yellow operations require explicit confirmation; Red operations also perform simulated MFA. Core issues and consumes a short-lived, single-use, payload-bound grant.
7. The UI reports success only after Core commits and returns a completed state. Timeouts or unknown outcomes enter status-query and reconciliation paths.

## Risk tiers

| Tier | Core behavior | Typical operations |
| --- | --- | --- |
| Green | Read after identity and ownership checks | Balance, transactions, bills, and investment-return queries |
| Yellow | Explicit confirmation | Daily reserved-plus-committed outgoing total up to CNY 1,000; card freeze/unfreeze/limit; subscription cancellation; savings contribution up to CNY 1,000 |
| Red | Approval plus simulated MFA | Transfers or savings contributions above that threshold, card loss report, wealth subscription/redemption |

Transfer totals use the `Asia/Shanghai` business day and include pending-authorization drafts. Parameter Confirmation, Risk Approval, and commit are distinct; see the [Glossary](GLOSSARY.en.md).

## Model-service configuration

The default is `MODEL_PROVIDER=offline`. DeepSeek, Qwen, or an OpenAI-compatible local service can be configured. Jev and the Privacy Broker are optional:

```dotenv
MODEL_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
JEV_ENABLED=true
JEV_API_KEY=...
PRIVACY_BROKER_ENABLED=true
```

Jev can classify simple intents, label expenses, and optionally review plans. If it is unavailable or below threshold, the system uses the primary LLM or asks for clarification; Jev never authorizes financial actions. The Privacy Broker is best-effort redaction. A deterministic input guard still rejects passwords, verification codes, CVV, and full card numbers.

## Verification

```bash
python -m pytest
python -m ruff check .
python -m mypy

cd frontend/aegis-pwa
npm run typecheck
npm test
npm run build
```

The latest full Python regression on 2026-11-02 reported `142 passed, 12 skipped`; the skipped cases were PostgreSQL integration tests without a separate `DATABASE_TEST_URL`. The 16 frontend tests, type check, and production build passed in the same development cycle. This is a dated test snapshot, not production certification. `DATABASE_TEST_URL` must point to a disposable test database.

## Documentation

| Document | Focus |
| --- | --- |
| [Documentation index](documents/README.en.md) | Reading order and document ownership |
| [Architecture](documents/Architecture.en.md) | Services, data flow, persistence, and deployment boundaries |
| [Algorithms](documents/Algorithm.en.md) | Decomposition, provenance, calculations, plans, and recovery |
| [Security](documents/Security.en.md) | Trust boundaries, approval, privacy, audit, and limits |
| [Glossary](GLOSSARY.en.md) | Shared concepts and state distinctions |

## Repository map

```text
agent/                  Language, Task Bundles, and execution orchestration
agent_tools/            Typed Agent-to-Core gateway
agent_persistence/      Sessions, bundles, tasks, and events
banking_core/           Financial domain, API, policy, transactions, and ledger
frontend/aegis-pwa/     React PWA, Node proxy, and Capacitor shell
migrations/             Core and Agent schema migrations
tests/                  Python unit and integration tests
documents/              Current architecture, algorithm, and security docs
```

