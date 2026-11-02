[中文](README.md) | English

# Frontend

This folder holds two frontends. Both reach the repository's two backend processes through the same kind of local proxy:

| Folder | What it is | Port |
|---|---|---|
| [`aegis-pwa/`](aegis-pwa/README.en.md) | **The main app, Aegis**: a React + TypeScript PWA that also ships as iOS / Android apps through Capacitor. Use this one for the competition demo | `5174` |
| [`demos/`](demos/) | The earlier zero-dependency single-page prototype (`index.html` + `server.mjs`), plus design files and the architecture diagram, kept for reference | `5173` |

```text
Browser / iOS app
  └─ frontend server (server.mjs: same-origin proxy, adds the service tokens server-side)
       ├─ /api/core/*  → Banking Core  http://127.0.0.1:8000
       └─ /api/agent/* → Agent API     http://127.0.0.1:8100
```

Because the frontend server proxies same-origin, the backends don't need relaxed CORS. Features, screenshots and iOS packaging are in [`aegis-pwa/README.en.md`](aegis-pwa/README.en.md).

## Requirements

| Software | Version | Used for |
|---|---|---|
| Python | **3.12** | Banking Core, Agent, migrations |
| Node.js | **22.12+** | Aegis (Vite 8, Capacitor 8) |
| Docker Desktop | recent stable | PostgreSQL |
| Xcode | optional | running Aegis on an iPhone or the Simulator |

## One-time setup (macOS / Linux)

From the repository root (for Windows, see the root [`README.en.md`](../README.en.md)):

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
docker compose up -d db
python -m alembic upgrade head
python -m scripts.seed_demo_data
```

When Core and the Agent run on your machine (not in Docker), change the database host `db` in `.env` to `127.0.0.1`. The name `db` only works inside Docker:

```bash
sed -i '' 's/@db:5432/@127.0.0.1:5432/g' .env   # macOS; on Linux drop the ''
```

The `.env` settings that matter for the frontend:

```dotenv
DEVELOPMENT_USER_ID=900fefe8-ceba-516d-8d05-5cfff313fa65        # demo user Lin
AGENT_DEVELOPMENT_USER_ID=900fefe8-ceba-516d-8d05-5cfff313fa65  # same as above
MOCK_MFA_CODE=123456
BANKING_BASE_URL=http://127.0.0.1:8000
BANKING_SERVICE_TOKEN=development-only
AGENT_API_TOKEN=development-agent-only
MODEL_PROVIDER=offline        # or deepseek / qwen / local, with its API key
AGENT_ROUTING_MODE=hybrid     # with llm_only the agent can't answer if the model is down; see below
```

That UUID is the fixed seed value for `user:lin`. Check it with `python -c "from scripts.seed_demo_data import stable_id; print(stable_id('user:lin'))"`.

## Start order

Open three terminals. In the first two, run `source .venv/bin/activate` from the repository root first.

**1. Banking Core**

```bash
python -m uvicorn banking_core.app.main:app --host 127.0.0.1 --port 8000
```

**2. Agent API**

```bash
python -m uvicorn agent.app:app --host 127.0.0.1 --port 8100
```

**3. Aegis**

```bash
cd frontend/aegis-pwa
npm ci
npm run build && npm run serve
```

Open <http://127.0.0.1:5174>. **No** purple "Demo mode" banner at the top means Core and the Agent are both connected.

In the iPhone Simulator: keep step 3 running, run `VITE_API_BASE=http://localhost:5174 npm run cap:ios` in another terminal, choose your Team in Xcode and press ▶. For a real iPhone and screen recording, see [`aegis-pwa/README.en.md`](aegis-pwa/README.en.md).

**The earlier prototype (optional)**

```bash
cd frontend/demos
node server.mjs
```

Open <http://127.0.0.1:5173>. Override the addresses with `CORE_BACKEND_URL`, `AGENT_BACKEND_URL` and `PORT`.

### Check the connection

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8100/openapi.json
curl http://127.0.0.1:5174/api/agent/openapi.json
```

## Behaviour and security boundaries

- **Identity is injected only on the server.** The user comes from Core / Agent environment variables. Browser requests can't send or override `user_id`, risk tier, MFA, approvals or authorization references.
- **Tokens never reach the browser.** The Node proxy overwrites any `Authorization` header from the browser and injects the Core and Agent service tokens. The example values are for local development only and must be replaced before any deployment.
- **Sensitive input never reaches the model.** Passwords, verification codes, CVVs and full card numbers are blocked both in the browser and by the Agent request contract, so they never go to an external LLM. MFA codes go only to Core's own verification endpoint.
- **Core decides the risk tier.** Transfers are Yellow while today's total, including the current one, is ¥1,000 or less, and Red above that. Backing out at the shield cancels the unfinished draft.
- **No automatic replay.** Tasks in `WAITING_APPROVAL` or `FAILED` are never retried automatically, so drafts or writes are never duplicated.
- **If the Agent is down**, the screens still work against Core, but the assistant doesn't run banking actions locally.
- **If Core is down**, the frontend switches to built-in demo mode (fictional data, code `123456`). Demo mode writes nothing to the database, so it doesn't prove the integration works.
- **Request log.** Aegis's **Profile → API log** shows requests and responses with trace IDs, with authorization references and codes hidden.

## Checks

```bash
# Aegis
cd frontend/aegis-pwa && npm run typecheck && npm test

# the prototype's proxy
node --test frontend/demos/server.test.mjs

# backend (repository root)
python -m pytest
```

## Troubleshooting

- **The page stays in demo mode:** check that the services on ports 8000 and 8100 are running, and check `DEVELOPMENT_USER_ID`. After `npm run build`, restart `npm run serve`.
- **`failed to resolve host 'db'`:** the database host in `.env` is still `db`; change it to `127.0.0.1` as above.
- **`UnicodeEncodeError: 'ascii' codec can't encode`:** an API key in `.env` contains `•` or other non-ASCII characters, usually because a masked key was copied from a web page or chat. Copy the full key again from the provider's console.
- **Every message gets a follow-up question or an error:** with `AGENT_ROUTING_MODE=llm_only`, nothing falls back to the rule router when the model is unavailable. Check `MODEL_PROVIDER` and the API key, or switch to `hybrid`.
- **A small transfer asks for a code:** once today's transfers, including this one, pass ¥1,000, it's Red. That's expected.
- **A Red action won't verify:** check `MOCK_MFA_CODE` in `.env`.
- **Durable task endpoints fail:** check that `AGENT_DATABASE_URL` points at the migrated PostgreSQL, and, if set, that `AGENT_CHECKPOINT_DATABASE_URL` is reachable.
- **Strange install or import errors:** check that `python --version` is 3.12. Newer versions such as 3.15 may not be compatible.
- **A port is already in use:** override it with `PORT`, `CORE_BACKEND_URL` or `AGENT_BACKEND_URL`.

Never run the demo reset commands against a database with real banking data. This project should only use fictional competition data.
