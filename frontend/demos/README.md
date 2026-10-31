# FinSAO 前端（中文，AI 赛道）

完整的 Core + Agent 联调、环境变量、启动和测试说明请阅读 [`../README.md`](../README.md)。本目录保留页面实现和零依赖代理服务。

单文件前端 `index.html` + 零依赖本地服务 `server.mjs`。页面使用与后端一致的 JSON 规范（snake_case、十进制字符串金额、`X-Trace-Id`、`Idempotency-Key`）。

## 1. 启动后端（队友的仓库）
```powershell
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
docker compose up -d db
python -m alembic upgrade head
python -m scripts.seed_demo_data
uvicorn banking_core.app.main:app --reload
```
`.env` 必须包含（否则所有接口返回 401 / 无法完成红色验证）：
```
APP_ENV=development
DEVELOPMENT_USER_ID=<运行 python -c "from scripts.seed_demo_data import stable_id; print(stable_id('user:lin'))" 得到的 UUID>
MOCK_MFA_CODE=123456   # 6 位数字，红色操作验证码
```

## 2. 启动前端
```
node server.mjs            # 默认 http://127.0.0.1:5173
CORE_BACKEND_URL=http://host:8000 AGENT_BACKEND_URL=http://host:8100 PORT=5173 node server.mjs
```
页面顶部会分别显示 Core 与 Agent 连接状态；Core 不可达时进入演示模式，Agent 不可达时不影响 Core 业务页面，但聊天不会在浏览器本地执行银行操作。右上角“JSON 日志”可查看已脱敏的请求/响应。

## 3. 演示脚本（评委路径）
1. 助手页：`查询余额，并给 Friend 转 800 元` → 黄色确认 → 回执（展示工具调用轨迹）。
2. 再发 `给 Friend 转 1500 元` → 当日累计超过 ¥1,000 → 红色验证码。
3. 银行卡：冻结 / 解冻（黄），挂失（红）；订阅取消（黄）；理财测评后申购（红）。
注意：转账场景假设当日全新数据库；重置演示数据用 `docker compose down -v`（仅限一次性演示库）。

## 已知限制
- 聊天统一创建 `/agent/tasks`，规则快路径和可选 LLM fallback 都位于后端；语音仍未接入。
- Jev 按要求保持未启用；它是可插拔路由，不是前后端连接的依赖。
- 储蓄罐已接入持久化 API，采用虚拟分配语义，不扣减或冻结账户余额。
- 种子数据只含 2026-01～03 的流水，总览默认统计 2026-03。

## 赛题对照（AI 赛道）
| 要求 | 本前端的实现 | 状态 |
|---|---|---|
| 权限分级（绿/黄/红） | 审批以后端返回的 `risk_tier` 为准；黄=确认，红=6 位验证码；挂失/理财申购赎回为红 | 已实现 |
| 幻觉防护 | 助手只展示 API 返回的数据，每一步工具调用与结果可展开查看 | 已实现 |
| 注入防御 | 助手输入拦截“绕过验证/忽略指令”等；真正的权限判定在后端，授权凭据不进入工具参数、日志已脱敏 | 前端守卫 + 后端强制 |
| 操作审计 | “决策链路/审计”面板（客户端会话）；后端 audit_events 持久化（无查询接口） | 部分 |
| 异常熔断 | 助手连续 3 次工具失败/3 次可疑指令即锁定；MFA 错误过多触发后端安全锁定 | 已实现 |
| 任务规划 DAG / 中断 / 人工接管 | 执行前展示任务 DAG，可随时中断；资金操作必须人工审批 | 已实现（回滚受后端限制：无取消转账接口） |
| 场景 1 转账 / 3 理财 / 4 卡片 / 5 订阅 / 2 账单 | 已覆盖 | 已实现 |
| 定时转账、AA 收款、卡片申请、按手机号转账、跨场景联动 | 后端无对应接口 | 未实现 |
| 沙箱 | 前端不执行生成代码 | 不适用 |
