[中文](README.md) | [English](README.en.md)

# 前端

这个目录包含两个前端，都通过同一个本地代理连接仓库里的两个后端进程：

| 目录 | 内容 | 端口 |
|---|---|---|
| [`aegis-pwa/`](aegis-pwa/README.md) | **主应用 Aegis**：React + TypeScript PWA，可通过 Capacitor 打包为 iOS / Android 应用。比赛演示使用这一个 | `5174` |
| [`demos/`](demos/) | 早期的零依赖单页原型（`index.html` + `server.mjs`），以及设计稿和架构图，保留作参考 | `5173` |

```text
浏览器 / iOS 应用
  └─ 前端服务（server.mjs，同源代理，在服务端注入服务令牌）
       ├─ /api/core/*  → Banking Core  http://127.0.0.1:8000
       └─ /api/agent/* → Agent API     http://127.0.0.1:8100
```

前端服务负责同源代理，因此不需要放宽后端 CORS。功能、界面截图和 iOS 打包方法见 [`aegis-pwa/README.md`](aegis-pwa/README.md)。

## 前置条件

| 软件 | 版本 | 用途 |
|---|---|---|
| Python | **3.12** | Banking Core、Agent、迁移 |
| Node.js | **22.12+** | Aegis（Vite 8、Capacitor 8） |
| Docker Desktop | 近期稳定版 | 运行 PostgreSQL |
| Xcode | 可选 | 在 iPhone / 模拟器上运行 Aegis |

## 一次性准备（macOS / Linux）

在仓库根目录执行（Windows 见根目录 [`README.md`](../README.md)）：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
docker compose up -d db
python -m alembic upgrade head
python -m scripts.seed_demo_data
```

在宿主机上运行 Core 和 Agent 时，要把 `.env` 中数据库地址的主机名 `db` 改成 `127.0.0.1`（`db` 只在 Docker 内部有效）：

```bash
sed -i '' 's/@db:5432/@127.0.0.1:5432/g' .env   # macOS；Linux 去掉 ''
```

`.env` 中与前端联调相关的关键项：

```dotenv
DEVELOPMENT_USER_ID=900fefe8-ceba-516d-8d05-5cfff313fa65        # 演示用户 Lin
AGENT_DEVELOPMENT_USER_ID=900fefe8-ceba-516d-8d05-5cfff313fa65  # 与上面相同
MOCK_MFA_CODE=123456
BANKING_BASE_URL=http://127.0.0.1:8000
BANKING_SERVICE_TOKEN=development-only
AGENT_API_TOKEN=development-agent-only
MODEL_PROVIDER=offline        # 或 deepseek / qwen / local，并填写对应 API Key
AGENT_ROUTING_MODE=hybrid     # llm_only 时模型不可用就无法回答，见下方常见问题
```

上面的 UUID 是种子脚本中 `user:lin` 的固定值，可用 `python -c "from scripts.seed_demo_data import stable_id; print(stable_id('user:lin'))"` 核对。

## 启动顺序

打开三个终端，前两个先在仓库根目录执行 `source .venv/bin/activate`。

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

打开 <http://127.0.0.1:5174>。页面顶部**没有**紫色「演示模式」提示条，就说明 Core 和 Agent 都已连接。

在 iPhone 模拟器中运行：保持第 3 步运行，另开终端执行 `VITE_API_BASE=http://localhost:5174 npm run cap:ios`，在 Xcode 中选择 Team 后点 ▶。真机和录屏方法见 [`aegis-pwa/README.md`](aegis-pwa/README.md)。

**早期原型（可选）**

```bash
cd frontend/demos
node server.mjs
```

打开 <http://127.0.0.1:5173>。地址可用 `CORE_BACKEND_URL`、`AGENT_BACKEND_URL`、`PORT` 覆盖。

### 检查是否连通

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8100/openapi.json
curl http://127.0.0.1:5174/api/agent/openapi.json
```

## 联调行为与安全边界

- **身份只由服务端注入。** 用户身份来自 Core / Agent 的环境变量。浏览器请求不能提交或覆盖 `user_id`、风险等级、MFA、审批或授权引用。
- **令牌不进入浏览器。** Node 代理会覆盖浏览器提供的 `Authorization`，分别注入 Core 和 Agent 的服务令牌。示例值只能用于本机开发，部署前必须替换。
- **敏感信息不发给模型。** 密码、验证码、CVV 和完整卡号在浏览器和 Agent 请求契约两层被拦截，不会进入外部 LLM；MFA 只提交给 Core 的独立验证接口。
- **风险等级以 Core 为准。** 当天累计转账（含本笔）不超过 ¥1,000 为黄色，超过为红色；在护盾页取消会撤销未完成的草稿。
- **不自动重放。** `WAITING_APPROVAL` 或 `FAILED` 的任务不会自动重试，避免重复草稿或重复写入。
- **Agent 不可用时**，业务页面仍可使用 Core，但助手不会在本地执行银行操作。
- **Core 不可用时**，前端进入内置演示模式（虚构数据，验证码 `123456`）。演示模式不写数据库，不能当作联调成功的证据。
- **请求日志。** Aegis 的「个人资料 → API 日志」显示带 Trace ID 的请求和响应，并隐藏授权引用和验证码。

## 验证

```bash
# Aegis
cd frontend/aegis-pwa && npm run typecheck && npm test

# 早期原型的代理
node --test frontend/demos/server.test.mjs

# 后端（仓库根目录）
python -m pytest
```

## 常见问题

- **页面一直显示演示模式**：确认 8000 和 8100 端口的服务都在运行，并检查 `DEVELOPMENT_USER_ID`。改完代码重新 `npm run build` 后，要重启 `npm run serve`。
- **`failed to resolve host 'db'`**：`.env` 中的数据库主机还是 `db`，按上文改成 `127.0.0.1`。
- **`UnicodeEncodeError: 'ascii' codec can't encode`**：`.env` 里的 API Key 含有 `•` 等非 ASCII 字符，通常是从网页或聊天里复制了被遮挡的 Key。请从服务商控制台重新复制完整 Key。
- **所有输入都只返回追问或报错**：`AGENT_ROUTING_MODE=llm_only` 时，模型不可用就不会退回规则路由。检查 `MODEL_PROVIDER` 和 API Key，或改用 `hybrid`。
- **小额转账也要验证码**：当天累计转账（含本笔）超过 ¥1,000 就是红色，这是预期行为。
- **Red 操作无法验证**：检查 `.env` 中的 `MOCK_MFA_CODE`。
- **Durable task 接口失败**：确认 `AGENT_DATABASE_URL` 指向已迁移的 PostgreSQL；如果设置了 `AGENT_CHECKPOINT_DATABASE_URL`，也要确认它可连接。
- **安装依赖或导入时出现奇怪错误**：检查 `python --version` 是否为 3.12；过新的 Python（如 3.15）可能不兼容。
- **端口已占用**：用 `PORT`、`CORE_BACKEND_URL`、`AGENT_BACKEND_URL` 覆盖默认值。

不要对含有真实银行信息的数据库运行演示重置命令。本项目只应使用虚构的比赛数据。
