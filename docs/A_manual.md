# Frontend Development Guide / 前端开发指南

> Updated: 2026-10-23. English with Chinese keyword annotations comes first; the full Chinese edition follows. Both editions describe the same scope. Query examples for later dataset collection are placed at the end.

## Part I — English Edition（英文版）

### 1. Development priorities（开发重点）

This guide is for frontend developers building the Chinese competition application. Read it in this order: expected functions → page layout → JSON contracts → endpoint map → interaction and acceptance rules. The query appendix is for future dataset collection and is not the current implementation priority.

The API schemas and `/openapi.json` define the current wire contract（传输契约）. `/docs` provides interactive examples. This document also records agreed product plans; a planned UI does not imply an available API.

### 2. Expected functions and delivery status（预期功能与交付状态）

| Area | Expected application functions | Current delivery status |
|---|---|---|
| Dashboard（总览） | Accounts, balances, monthly spending, category budgets, subscription summary | Existing REST APIs; compose multiple responses |
| Accounts & transactions（账户与流水） | Account list, balance, paginated history, date/category/merchant/amount filters, category correction | Available |
| Transfer（转账） | Beneficiary selection, draft, confirmation/MFA, commit, receipt, status recovery | Available; final execution requires backend authorization |
| Spending & budgets（消费与预算） | Monthly category/merchant breakdown; create/list/update budgets; usage, remaining, estimate, threshold | Available |
| Subscription tracker（订阅追踪） | Tracked subscriptions, recurring-payment evidence, billing estimate, reminder record, cancellation | Available; reminder delivery and real merchant cancellation are future integrations |
| Cards（银行卡） | List/details, limit update, freeze/unfreeze, lost reporting | Available with fictional identifiers |
| Wealth（模拟理财） | Product list/filter/compare, five-answer assessment, suitability list, holdings, subscription/redemption, order status | Available; redemption depends on product capability |
| Approval & MFA（审批与验证） | Operation review, confirm/reject, challenge, verification, expiry and result | Available with simulated MFA |
| Chat & voice entrance（聊天与语音入口） | Persistent bottom entry; text input and press-to-speak interaction; route to function pages/result cards | Agreed UI requirement; speech services, conversation API and LLM/LangGraph orchestration are not implemented yet |
| Savings pots（储蓄罐） | Frontend page for savings goals, target amount, progress and contributions | Agreed planned feature; frontend may design it now; backend schema/API must follow before live use |

Savings pots are retained in the intended product scope following the product edits. They are different from category budgets: a budget limits planned spending, while a savings pot represents a savings goal. Whether contributions are virtual allocations or real account transfers remains an interface decision; do not assume either behavior.

Internal-only capabilities: unusual-spending detection, monthly comparison and audit storage currently have no customer-facing routes. Real bank/card/market execution, production login, real OTP delivery, loans, FX conversion and full payment credentials are outside the current backend delivery.

### 3. Page layout and navigation（页面布局与导航）

#### 3.1 Application shell（应用框架）

- Desktop: header with application name and selected account; left navigation; main content; persistent chat entry at the bottom.
- Mobile: compact header, scrollable content, primary bottom navigation (Home, Accounts, Transfer, Wealth, More), and a persistent chat/voice entry above the safe area.
- Put Budgets, Subscriptions, Cards and Savings Pots under More on narrow screens; use direct navigation entries on desktop.
- The chat entry expands into a drawer or sheet with message history, text input, microphone button and result cards. Use Chinese labels as the primary display language.
- Reserve loading, microphone-active, transcription-preview, sending, approval-required and error states. Voice controls need service integration; unavailable actions should show an honest unavailable state.
- Chat-triggered actions must use the same review/approval components as forms. A generated response never counts as a completed banking operation.

#### 3.2 Page components（页面组件）

| Page | Suggested layout | Key interaction / data source |
|---|---|---|
| Dashboard（总览） | Account balance cards → monthly spending chart → budget progress → subscriptions | Load account list then balances; analytics/budgets/subscriptions are separate requests |
| Accounts（账户） | Account selector → balance/status → transaction table/list → filters/pagination | Keep each amount paired with its currency; show empty and error states per section |
| Transfer（转账） | Source account → beneficiary search/list → amount/currency → review → confirmation/MFA → receipt | Multiple beneficiary matches require user selection; disable duplicate submit while pending |
| Spending/Budgets（消费/预算） | Month selector → category/merchant charts → budget cards → create/edit form | Use backend totals; budget changes do not move funds |
| Subscriptions（订阅） | Active/cancelled tabs → billing cards → inferred-payment section → reminder/cancel actions | Keep inferred evidence separate from persisted subscription state |
| Cards（银行卡） | Card list → details/status/limit → operation controls | Disable invalid state actions; lost reporting uses MFA |
| Wealth（理财） | Product filters/list → comparison → assessment/suitability → holdings → order review/status | Fetch product details to label holdings; only offer redemption when supported |
| Savings Pots（储蓄罐，规划中） | Goal list → progress → target/date form → contribution/history panel | Use clearly labelled preview data until backend integration; field design is provisional |
| Approval/MFA（审批/验证） | Shared modal/sheet: exact operation → risk/expiry → confirm/reject or code input → result | Show persisted backend values; clear expired/consumed grants |

Keep chat controls clear of navigation, submit buttons and the on-screen keyboard. Preserve form contents during recoverable request failures. Show a receipt only after a persisted completed result.

### 4. Shared JSON transport standard（统一 JSON 传输规范）

#### 4.1 Primitive types and encoding（基础类型与编码）

| Item | Wire format | Frontend rule |
|---|---|---|
| JSON / encoding | UTF-8; JSON body; `Content-Type: application/json` | No JSON comments, trailing commas or `undefined` |
| Names（字段名） | `snake_case` | Keep API keys unchanged; translate labels separately |
| IDs（标识符） | UUID strings | Treat as opaque; `id` means the resource ID; `account_id`/`product_id` refer to related resources |
| Money（金额） | Decimal strings, e.g. `"800.00"` | Send strings; preserve cents; use a decimal library for arithmetic |
| Currency（币种） | `CNY`, `USD`, `EUR` | Never add different currencies together without an explicit conversion API |
| Integer（整数） | JSON number, e.g. `50` | Pagination, year/month, assessment answers; not monetary values |
| Date（日期） | `YYYY-MM-DD` | Budget `month` stores an exact date; month-only agent input is normalized to day 1 |
| Timestamp（时间戳） | ISO 8601 with offset, e.g. `2026-10-23T04:30:00Z` | Send timezone-aware values; accept `Z` or `+00:00`; display in user locale |
| Boolean（布尔值） | `true` / `false` | Never send `"true"` or `"false"` |
| Null（空值） | `null` | Different from absent, `"null"`, `""`, `0` and `[]` |
| Enum（枚举） | Exact uppercase identifier | Localize labels, not wire values; allow unknown-value display fallback |

Daily transfer policy and relative budget dates use `Asia/Shanghai`. Use fixed two-decimal strings in request/display conventions; responses remain decimal strings and should be normalized for display without converting to binary floating point. Transfer/wealth amount schemas allow up to 18 digits in total and two fractional digits. Monetary mutations require positive amounts.

Required fields must be present. Omit unused optional query filters rather than sending `"null"` or an empty string. Send only documented mutation fields; the current PATCH routes update the explicit fields shown below and are not generic merge-patch endpoints.

#### 4.2 Headers, identity and browser integration（请求头、身份与浏览器集成）

| Header / setting | Contract |
|---|---|
| `Content-Type` | `application/json` for JSON bodies |
| `Accept` | `application/json` recommended |
| `X-Trace-Id` | Optional UUID; backend accepts a valid UUID or generates one and returns it in the response header |
| `Idempotency-Key`（幂等键） | Required for transfer draft creation, 1–120 characters; preserve it for the same intent |
| Wealth idempotency | `idempotency_key` is required in the draft request body, 1–120 characters |
| Identity（身份） | Development user is server-configured; client-supplied `user_id` or `X-User-Id` is not an authentication mechanism |

Default local API base URL is `http://127.0.0.1:8000`; configure it outside components. Use a same-origin frontend proxy during local integration, or agree on explicit CORS origins and exposed headers before cross-origin browser calls. The backend currently has no CORS middleware configured. Production session/authentication is a separate integration dependency.

#### 4.3 Success, collections and pagination（成功响应、列表与分页）

REST returns resource objects directly, collection arrays directly, and transaction pages as `{items, limit, offset}`. There is no universal REST `{data: ...}` wrapper. Empty collections are `[]`; a paginated empty result has `items: []`. The API returns no `total` or `has_more` field for transaction pages.

Transaction filters: `start` inclusive, `end` exclusive, `limit` 1–200 (default 50), `offset` ≥ 0 (default 0), `category`, `merchant`, `minimum_amount`, `maximum_amount`. Merchant matches the transaction description case-insensitively. A page shorter than `limit` marks the end; a full page may require one more fetch. Pagination is offset-based, not a snapshot of changing data.

Example: `GET /accounts/{account_id}/transactions?limit=20&offset=0&category=HOUSEHOLD`

```json
{
  "items": [
    {
      "id": "af50fc80-6954-4fcf-9500-814792751b86",
      "reference": "DEMO-001",
      "status": "COMPLETED",
      "amount": "142.60",
      "currency": "CNY",
      "description": "Fictional household purchase",
      "category": "HOUSEHOLD",
      "posted_at": "2026-10-23T04:30:00Z"
    }
  ],
  "limit": 20,
  "offset": 0
}
```

#### 4.4 Resource field dictionary（资源字段字典）

All listed response fields are present unless an endpoint says otherwise; `T | null` means the field can be null. `Money` below means a decimal string, and `UUID` means a UUID string.

| Resource | Response fields and types | UI meaning / limitation |
|---|---|---|
| Account（账户） | `id: UUID`, `account_number: string`, `name: string`, `currency: Currency`, `status: AccountStatus` | No balance field; fetch balance separately |
| Balance（余额） | `account_id: UUID`, `balance: Money`, `currency: Currency` | Display balance with currency |
| Transaction（流水） | `id: UUID`, `reference: string`, `status: TransactionStatus`, `amount: Money`, `currency: Currency`, `description: string`, `category: string | null`, `posted_at: Timestamp | null` | No debit/credit direction or running balance field; do not infer income/expense from positive amount |
| Beneficiary（收款人） | `id: UUID`, `name: string`, `nickname: string | null`, `destination_account_id: UUID` | Transfer uses destination account ID, not beneficiary ID |
| Resolution（匹配结果） | `status: RESOLVED / AMBIGUOUS / NOT_FOUND`, `matches: Beneficiary[]` | Require choice when ambiguous |
| Transfer draft/status（转账草稿/状态） | `id: UUID`, `source_account_id: UUID`, `destination_account_id: UUID`, `amount: Money`, `currency: Currency`, `status: TransferStatus`, `expires_at: Timestamp`, `transaction_id: UUID | null` | `id` is the draft/operation ID |
| Transfer receipt（转账回执） | `transaction_id: UUID`, `reference: string`, `status: TransactionStatus`, `amount: Money`, `currency: Currency` | Different shape from draft; keep operation ID in UI state |
| Spending summary（支出汇总） | `total: Money`, `by_category: Record<string, Money>`, `by_merchant: Record<string, Money>` | No currency field; use current CNY demo scope; multi-currency analysis requires a backend contract extension |
| Budget（预算） | `id: UUID`, `category: string`, `month: Date`, `limit_amount: Money`, `currency: Currency` | Month is first calendar day |
| Budget status（预算使用情况） | `limit: Money`, `used: Money`, `remaining: Money`, `estimate: Money`, `threshold_exceeded: boolean` | Join with budget for ID/currency; remaining is clamped to zero; default threshold is 80%; REST does not expose threshold configuration |
| Subscription（订阅） | `id: UUID`, `merchant_name: string`, `amount: Money`, `currency: Currency`, `next_billing_date: Date`, `active: boolean`, `status: string`, `cancelled_at: Timestamp | null` | Active state and successful cancellation are persisted |
| Recurring evidence（周期扣费线索） | `merchant: string`, `confidence: string`, `evidence_transaction_ids: UUID[]`, `estimated_next_billing_date: Date` | Current confidence is `HIGH`; inference is not a saved subscription |
| Reminder（提醒记录） | `id: UUID`, `subscription_id: UUID`, `remind_on: Date`, `delivered: boolean` | Record creation does not mean notification delivery |
| Card（银行卡） | `id: UUID`, `account_id: UUID`, `label: string`, `last_four: string`, `status: CardStatus`, `spending_limit: Money` | Keep last_four as text; currency comes from associated account |
| Product（理财产品） | `id: UUID`, `code: string`, `name: string`, `product_type: string`, `risk_tier: RiskTier`, `minimum_amount: Money`, `currency: Currency`, `supports_redemption: boolean` | Product type examples: MONEY_MARKET_FUND, BOND_FUND, GOVERNMENT_BOND, FIXED_INCOME |
| Assessment（风险测评） | `id: UUID`, `score: integer`, `risk_tier: RiskTier` | Questionnaire labels still need product copy; API accepts five 1–5 answers |
| Holding（持仓） | `id: UUID`, `product_id: UUID`, `amount: Money`, `currency: Currency` | Join product list for name; no live profit/return field |
| Wealth order（理财订单） | `id: UUID`, `account_id: UUID`, `product_id: UUID`, `amount: Money`, `currency: Currency`, `status: string`, `order_type: WealthOrderType`, `transaction_id: UUID | null` | Current states are PENDING_AUTHORIZATION and COMPLETED |
| Approval（审批） | `id: UUID`, `operation_id: UUID`, `operation_type: string`, `target_account_id: UUID | null`, `recipient_id: UUID | null`, `amount: Money | null`, `currency: Currency | null`, `risk_tier: RiskTier`, `status: ApprovalStatus`, `expires_at: Timestamp` | Join related resource for display names; IDs/amount/currency may be null for non-money actions |
| Authorization（授权） | `authorization_ref: UUID`, `expires_at: Timestamp` | Treat as short-lived credential |
| MFA challenge（验证挑战） | `challenge_id: UUID`, `expires_at: Timestamp` | OTP is never returned by the API |

Current analysis limitations: merchant aggregation uses description text; monthly totals have no per-currency grouping; wealth category handling is not a separate consumption/investment reporting contract. Budget forecast uses the current service estimate (including a simplified 30-day projection), not an investment or cash-flow forecast. Do not derive features requiring absent fields.

#### 4.5 Mutation request templates（写操作请求模板）

These JSON objects are actual request bodies. Replace the valid illustrative UUIDs with IDs returned by the backend; explanatory field descriptions stay outside JSON.

**Transfer draft（转账草稿）** — `POST /transfers/drafts`, plus header `Idempotency-Key: transfer-intent-001`.

```json
{
  "source_account_id": "8a9cdd44-3416-595f-865d-75e2f44a8654",
  "destination_account_id": "2cb91352-7c76-4814-bd0c-7b895686940f",
  "amount": "800.00",
  "currency": "CNY"
}
```

**Budget creation / update（预算创建/修改）** — `POST /budgets` uses the first object; `PATCH /budgets/{budget_id}` uses the second.

```json
{
  "category": "HOUSEHOLD",
  "month": "2026-10-01",
  "limit_amount": "1500.00",
  "currency": "CNY"
}
```
```json
{
  "limit_amount": "2000.00"
}
```

**Category correction / reminder（分类修正/续费提醒）** — `PATCH /transactions/{transaction_id}/category` and `POST /subscriptions/{subscription_id}/reminders` respectively.

```json
{
  "category": "TRANSPORT"
}
```
```json
{
  "remind_on": "2026-10-28"
}
```

**Product comparison / assessment（产品比较/风险测评）** — `POST /wealth/products/compare` and `POST /wealth/risk-assessment` respectively.

```json
{
  "product_ids": [
    "0eb06179-6c76-46db-ac91-2431cbf5da83",
    "e8a4c544-ceae-4eba-bce7-35b504b652b3"
  ]
}
```
```json
{
  "answers": [
    1,
    2,
    3,
    4,
    5
  ]
}
```

**Wealth draft（理财草稿）** — same body for `POST /wealth/orders` (subscription/申购) and `POST /wealth/redemptions` (redemption/赎回). The key must not be reused for a different order type or payload.

```json
{
  "account_id": "8a9cdd44-3416-595f-865d-75e2f44a8654",
  "product_id": "0eb06179-6c76-46db-ac91-2431cbf5da83",
  "amount": "1000.00",
  "idempotency_key": "wealth-intent-001"
}
```

**Approval creation（创建审批）** — `POST /security/approvals`. Use `transfer.commit`, `subscription.cancel`, `card.limit`, `card.freeze`, `card.unfreeze`, `card.report_lost`, `wealth.subscribe` or `wealth.redeem`. The resource determines valid action types. For cards/subscriptions, operation_id is the resource ID; for transfers/wealth, it is the draft/order ID. Exact `amount` is required when approving `card.limit`.

```json
{
  "operation_id": "11263eac-2ca5-46da-837d-03697213309d",
  "operation_type": "transfer.commit"
}
```
```json
{
  "operation_id": "c8c998e7-20b3-4c50-bd9c-59c0c397283e",
  "operation_type": "card.limit",
  "amount": "6000.00"
}
```

**Decision / verification（审批决定/验证码验证）** — `POST /security/approvals/{approval_id}/decision` and `POST /security/mfa/{challenge_id}/verify` respectively. `accepted: false` rejects an approval; code is a string so leading zeros survive. Challenge creation itself needs no JSON body.

```json
{
  "accepted": true
}
```
```json
{
  "code": "012345"
}
```

An accepted Yellow decision or successful Red verification returns:

```json
{
  "authorization_ref": "62df06e2-9bb7-4502-9d35-bda2c1a15ce1",
  "expires_at": "2026-10-23T04:40:00Z"
}
```

A successful rejection returns HTTP 200 with JSON `null`; it does not return an Authorization object. Fetch the approval again if the UI needs its final status.

**Authorized execution（授权执行）** — transfer commit, subscription cancellation, card freeze/unfreeze/lost reporting and wealth commit use:

```json
{
  "authorization_ref": "62df06e2-9bb7-4502-9d35-bda2c1a15ce1"
}
```

Card limit update additionally includes the exact approved amount:

```json
{
  "spending_limit": "6000.00",
  "authorization_ref": "62df06e2-9bb7-4502-9d35-bda2c1a15ce1"
}
```

#### 4.6 Errors and frontend behavior（错误与前端行为）

```json
{
  "code": "INSUFFICIENT_FUNDS",
  "message": "insufficient funds"
}
```

| HTTP status / code | Frontend behavior |
|---|---|
| 401 / HTTP_ERROR | Identity unavailable; do not offer user-ID header workarounds |
| 403 / FORBIDDEN | Show access denied |
| 403 / AUTHORIZATION_REQUIRED | Review operation/approval state; may also represent expired or invalid authorization/MFA |
| 404 / NOT_FOUND | Show missing resource; refresh affected list |
| 409 / CONFLICT | Refresh state or explain idempotency/state conflict |
| 409 / INSUFFICIENT_FUNDS | Show funds error; preserve form values |
| 422 / VALIDATION_ERROR | Validate documented fields; current response gives a generic message, not per-field errors |
| 500 / INTERNAL_ERROR | Show retry/recovery guidance and capture trace ID |

Branch on error codes and HTTP status; localize the displayed message. A 200 response means HTTP success, not always business completion: a draft can still be PENDING_AUTHORIZATION. For exceptions outside a route handler, a trace header may be unavailable; logging should tolerate that.

The Python ToolGateway has a separate `{status, data, error_code, message}` result. Its statuses are SUCCESS, WAITING_APPROVAL, MFA_REQUIRED, DENIED, VALIDATION_ERROR and EXECUTION_ERROR. UNKNOWN_OUTCOME is the HTTP client's classification after a mutation timeout, not a persisted REST operation status. REST currently may report MFA problems with AUTHORIZATION_REQUIRED; do not assume a dedicated MFA_REQUIRED REST response.

#### 4.7 Status values（状态值）

| Type | Values |
|---|---|
| AccountStatus | ACTIVE, FROZEN, CLOSED |
| TransactionStatus | PENDING, COMPLETED, FAILED, REVERSED |
| TransferStatus | DRAFT, PENDING_AUTHORIZATION, AUTHORIZED, PROCESSING, COMPLETED, FAILED, CANCELLED, EXPIRED |
| CardStatus | ACTIVE, FROZEN, LOST, CANCELLED, EXPIRED |
| RiskTier | GREEN, YELLOW, RED |
| ApprovalStatus | PENDING, CONFIRMED, REJECTED, EXPIRED, CONSUMED |
| WealthOrderType | SUBSCRIPTION, REDEMPTION |

Enum membership does not imply a public operation exists for every state. There is no public transfer cancellation endpoint, for example.

### 5. Endpoint map（接口清单）

| Area | Method and path |
|---|---|
| Accounts | GET /accounts; GET /accounts/{account_id}/balance; GET /accounts/{account_id}/transactions |
| Beneficiaries | GET /beneficiaries; GET /beneficiaries/resolve?query=... |
| Transfers | POST /transfers/drafts; GET /transfers/drafts/{draft_id}; POST /transfers/{draft_id}/commit; GET /transfers/{transfer_id} |
| Analysis | GET /analytics/monthly-summary?year=2026&month=10; GET /analytics/spending?year=2026&month=10; PATCH /transactions/{transaction_id}/category |
| Budgets | GET /budgets; POST /budgets; PATCH /budgets/{budget_id}; GET /budgets/{budget_id}/status |
| Subscriptions | GET /subscriptions; GET /subscriptions/detect-recurring; POST /subscriptions/{subscription_id}/reminders; POST /subscriptions/{subscription_id}/cancel |
| Cards | GET /cards; GET /cards/{card_id}; PATCH /cards/{card_id}/limit; POST /cards/{card_id}/freeze; POST /cards/{card_id}/unfreeze; POST /cards/{card_id}/report-lost |
| Wealth discovery | GET /wealth/products; POST /wealth/products/compare; GET /wealth/recommendations; POST /wealth/risk-assessment; GET /wealth/holdings |
| Wealth orders | POST /wealth/orders; POST /wealth/redemptions; GET /wealth/orders/{order_id}; POST /wealth/orders/{order_id}/commit |
| Security | POST /security/approvals; GET /security/approvals/{approval_id}; POST /security/approvals/{approval_id}/decision; POST /security/approvals/{approval_id}/mfa; POST /security/mfa/{challenge_id}/verify |
| Health | GET /health; GET /health/db |

Product list filters are optional `product_type` and `risk_tier`. Recommendations can be empty before assessment. There are no current `/chat`, `/voice` or `/savings-pots` routes.

The separately deployed Agent API exposes `POST /agent/requests` on its own base URL
(development default `http://127.0.0.1:8100`). Its v1 body contains `session_id`,
`message`, optional conversation messages and locale. It rejects client-supplied
identity, risk, approval, MFA and authorization fields. P2 is single-turn: Green tools
can execute, while writes stop at a draft/approval boundary; durable resume and SSE are
not yet implemented.

Durable P3 endpoints are `POST /agent/tasks`, `GET /agent/tasks/{task_id}`,
`POST /agent/tasks/{task_id}/resume`, `/cancel`, `/takeover`,
`GET /agent/tasks/{task_id}/events`, and
`GET /agent/tasks/{task_id}/events/stream`. SSE uses the monotonically increasing
event sequence as `id`; reconnect with `Last-Event-ID`. The resume body contains only
the out-of-band `authorization_reference`; never copy it into chat history, model
messages or persistent browser storage. Proactive reminder subscriptions use
`PUT /agent/proactive/subscriptions/{event_kind}` and can always be disabled; emitted
items are suggestions and never automatic payments.

### 6. Interaction rules and acceptance（交互规则与验收）

Prepare → create approval → show exact operation → confirm (Yellow) or verify MFA (Red) → commit → reconcile persisted status → receipt. Sensitive card/subscription operations reuse their resource ID rather than creating a separate draft. Backend authorization references belong in trusted application/session handling; keep them out of prompts, logs and persistent browser storage.

Green is used for reads; Yellow covers daily CNY outgoing transfers up to 1,000 including pending reservations, subscription cancellation and card limit/freeze/unfreeze; Red covers higher daily transfer totals, card loss and wealth subscription/redemption. Let the approval response determine the tier. A changed amount/action requires a new matching approval.

Generate one stable idempotency key for one transfer/wealth intent. Preserve the operation ID and original key across timeouts. Query transfer/order status before retrying. If draft creation times out before its ID is received, repeat the same draft request with the same key to recover the operation. Keep an unexpired grant temporarily while outcome is unresolved; discard it after confirmed completion/expiry. An invalid request must never produce an optimistic success receipt.

Frontend acceptance: load Dashboard resources independently; paginate/filter transactions; persist category/budget edits; require explicit beneficiary selection on ambiguity; complete an 800-CNY Yellow transfer on a fresh business-day dataset and a 1,500-CNY Red transfer; verify subscription cancellation after refresh; prevent lost-card unfreeze; assess risk before suitable wealth ordering; reconcile transfer/wealth timeouts. Chat and savings-pot pages may be reviewed as planned UI, but end-to-end acceptance requires their future backend contracts.

---

## 第二部分：中文版

### 1. 文档定位与开发顺序

本文面向中文比赛的前端开发人员。当前优先级是：**预期功能 → 页面布局 → JSON 传输规范 → 接口映射 → 交互与验收**。用户查询示例放在全文最后，供后续数据集采集使用。

现有接口以 Pydantic Schema 和 `/openapi.json` 为准，服务启动后可通过 `/docs` 联调。文档同时记录已确定的产品规划，标注“规划中”的功能需要后续后端接口配合。

### 2. 预期功能与实现状态

| 模块 | 页面需要覆盖的功能 | 当前状态 |
|---|---|---|
| 总览 Dashboard | 账户余额卡片、月度消费、分类预算、订阅摘要 | 已有接口，需要前端组合多个响应 |
| 账户与流水 | 账户列表、余额、分页、日期/分类/商户/金额筛选、分类修正 | 已实现 |
| 转账 | 收款人选择、草稿、确认/MFA、提交、回执、状态恢复 | 已实现，资金操作需授权 |
| 消费与预算 | 月度分类/商户统计、预算创建/列表/修改、使用量/余额/预测/预警 | 已实现 |
| 订阅追踪 | 已记录订阅、周期扣费线索、预计续费日、提醒记录、取消订阅 | 已实现模拟业务；真实商户取消和消息投递待接入 |
| 银行卡 | 列表、详情、限额、冻结、解冻、挂失 | 已实现，使用虚构卡标识 |
| 模拟理财 | 产品筛选/比较、五题风险测评、适当性推荐、持仓、申购/赎回、订单状态 | 已实现，赎回取决于产品支持情况 |
| 审批与验证 | 操作复核、确认/拒绝、验证码挑战、验证、到期与结果 | 已实现模拟 MFA |
| 聊天与语音入口 | 底部常驻入口、文本输入、按键说话、跳转功能页、结果卡片 | 保留为产品要求；语音服务、对话接口、LLM/LangGraph 编排尚未实现 |
| 储蓄罐 Savings Pots | 目标列表、目标金额、进度、存入与历史面板 | 按你的修改纳入预期功能；前端可先设计，后端后续补充契约 |

储蓄罐与分类预算是两个概念：预算管理计划支出，储蓄罐管理储蓄目标。储蓄罐“存入”究竟是虚拟分配还是实际账户转账，需要后续确定；当前不能把预览页面展示成已经完成真实资金操作。

内部已有但尚无公开接口：异常消费检测、月度对比、审计存储。当前后端交付不含正式登录系统、真实验证码投递、真实银行/卡组织/市场交易、贷款、换汇或完整支付凭证。

### 3. 页面布局与组件建议

桌面端采用“顶部栏 + 左侧功能导航 + 主内容区 + 底部常驻聊天入口”。移动端采用“紧凑顶部栏 + 可滚动内容 + 底部主导航 + 安全区域上方的聊天/语音入口”。底部主导航建议为：首页、账户、转账、理财、更多；预算、订阅、银行卡、储蓄罐可放入“更多”。

聊天入口展开为抽屉或底部面板，包含历史消息、文本输入框、麦克风按钮和结果卡片，主要标签采用中文。预留加载、录音中、转写预览、发送中、待审批和错误状态。语音未接入时应显示不可用状态。通过聊天发起的转账仍需进入统一的复核/审批组件。

| 页面 | 内容布局 | 关键交互 |
|---|---|---|
| 首页总览 | 账户余额卡片 → 月度消费图表 → 预算进度 → 订阅摘要 | 各区域独立加载、空态和错误态 |
| 账户与流水 | 账户选择 → 余额/状态 → 流水表格或列表 → 筛选与分页 | 每笔金额标明币种，不推断接口未返回的收支方向 |
| 转账 | 付款账户 → 收款人 → 金额币种 → 复核 → 确认/验证 → 回执 | 同名匹配必须选择；处理中防重复提交 |
| 消费与预算 | 月份选择 → 分类/商户图表 → 预算卡片 → 创建/修改表单 | 使用后端统计；修改预算不等于转移资金 |
| 订阅追踪 | 有效/已取消页签 → 续费卡片 → 推测线索 → 提醒与取消 | 已记录订阅与推测结果分别展示 |
| 银行卡 | 卡片列表 → 状态/限额详情 → 操作按钮 | 根据状态禁用非法操作；挂失需 MFA |
| 理财 | 筛选列表 → 比较 → 风险测评/推荐 → 持仓 → 订单复核/状态 | 用产品列表补齐持仓名称，仅支持时展示赎回 |
| 储蓄罐（规划中） | 目标列表 → 进度 → 金额/日期表单 → 存入/历史 | 预览数据需明确标注，字段暂不视为正式接口 |
| 审批/验证 | 共用弹窗：操作详情 → 风险/到期 → 确认或验证码 → 结果 | 使用后端持久化详情，处理过期/已消费授权 |

聊天按钮不能遮挡导航、提交按钮或软键盘。可恢复错误发生后保留用户填写内容。只有后端确认完成后才能展示成功回执。

### 4. 统一 JSON 传输规范

#### 4.1 基础约定

| 数据项 | 传输格式 | 前端要求 |
|---|---|---|
| 编码与命名 | UTF-8 JSON，字段统一 `snake_case` | API 字段名不翻译；中文仅用于显示标签 |
| UUID | 字符串 | `id` 是当前资源 ID，`account_id` 等是关联资源 ID；不能用 ID 推断归属 |
| 金额 | 十进制字符串，例如 `"800.00"` | 发送字符串，展示两位小数；权威金额运算使用十进制库 |
| 币种 | CNY / USD / EUR | 不同币种不能直接相加；当前没有换汇 API |
| 整数 | JSON number | 用于分页、年份、月份、测评答案；金额不使用该类型 |
| 日期 | `YYYY-MM-DD` | 预算 month 必须是当月第一天，例如 `2026-10-01` |
| 时间戳 | 带时区的 ISO 8601 | 可接收 `Z` 或 `+00:00`，发送时保留时区，本地化展示 |
| 布尔 | true / false | 不发送字符串 `"true"` / `"false"` |
| 空值 | null | 与字段缺失、空字符串、零、空数组不同 |
| 枚举 | 英文大写值 | 显示时映射中文；收到未知值时提供兜底标签 |

业务日界线和预算月份采用 Asia/Shanghai。金额请求/展示约定为两位小数字符串；响应按字符串接收并格式化，不先转为 JavaScript 浮点数。转账和理财请求金额最多 18 位总数字、两位小数，资金写操作金额必须为正。

必填字段必须发送。可选筛选条件未填写时直接省略，不发送 `"null"`。JSON 不允许注释、尾逗号或 undefined。PATCH 只修改接口明确列出的字段，不代表支持任意字段合并。

#### 4.2 请求头、身份和联调地址

- 本地 API 默认地址：`http://127.0.0.1:8000`，由环境配置提供，组件中不要散落硬编码地址。
- JSON 请求体使用 `Content-Type: application/json`，建议发送 `Accept: application/json`。
- 可发送 UUID 格式的 `X-Trace-Id`；后端接收有效值或生成新值，并通过响应头返回。
- 转账草稿必须发送 `Idempotency-Key` 请求头，长度 1–120；同一意图保留相同键。
- 理财草稿的幂等键放在请求体 `idempotency_key`，长度 1–120。
- 当前开发身份由服务端配置，客户端的 `user_id` 或 `X-User-Id` 不构成身份认证。
- 本地浏览器可使用同源代理；跨域直连前需约定 CORS 来源及暴露的响应头。当前后端没有配置 CORS 中间件。

#### 4.3 成功响应、分页与字段语义

REST 单资源直接返回对象，列表直接返回数组，分页流水返回 `{items, limit, offset}`。没有统一 `{data: ...}` 外壳。空列表返回 `[]`，空流水页返回 `items: []`。流水页没有 total、has_more 字段。

流水筛选支持：start（包含起点）、end（不包含终点）、limit（1–200，默认 50）、offset（≥0，默认 0）、category、merchant、minimum_amount、maximum_amount。merchant 对流水 description 做不区分大小写的包含匹配。返回条数小于 limit 表示结束，满页可能还需再取一页。offset 分页不提供数据快照。

字段完整类型见英文版 4.4；接口键名中英文版一致。以下是页面最容易误用的字段：

| 资源 | 需要明确的约定 |
|---|---|
| Account / Balance | 账户列表没有 balance，需逐账户请求余额 |
| Transaction | amount 为正值，但未提供借/贷方向或账户余额，不能据此标记收入/支出；category、posted_at 可为 null |
| Beneficiary | 转账 destination_account_id 使用关联账户 UUID，不使用 beneficiary.id |
| Transfer | 草稿的 id 是 operation_id；回执使用 transaction_id，两个 ID 需分别保存 |
| SpendingSummary | total、by_category、by_merchant 均为金额字符串；响应没有 currency，当前按人民币演示数据使用，多币种需后端扩展 |
| Budget / BudgetStatus | month 为月首日期；status 没有 id/currency，需关联预算对象；remaining 最低为零；默认预警比例 80%，REST 暂不支持修改该比例 |
| Subscription / Evidence | 已记录订阅带 id/active/status；推测结果带 confidence、证据交易 ID、预计扣款日，不自动成为已记录订阅 |
| Reminder | delivered=false 不代表系统会自动发送通知，目前仅创建提醒记录 |
| Card | last_four 保留字符串；币种需要关联账户获取 |
| Holding | 用 product_id 关联产品名称；没有实时盈亏或收益字段 |
| Product | supports_redemption 决定是否可赎回；minimum_amount 是最低申购金额 |
| WealthOrder | order_type 区分 SUBSCRIPTION（申购）与 REDEMPTION（赎回）；当前状态为 PENDING_AUTHORIZATION / COMPLETED |
| Approval | 非金额操作的账户/收款人/金额/币种字段可能为 null；显示名称需关联资源，不能用前端输入替换审批绑定信息 |
| Authorization / MFA | 授权响应含 authorization_ref/expires_at；挑战响应含 challenge_id/expires_at，验证码不会由接口返回 |

现有分析还有这些边界：商户维度实际使用 description 文本；月度金额没有按币种分组；投资与消费尚无独立统计契约。预算预测包含简化的 30 天估算，不应解释成完整现金流预测。

#### 4.4 常用请求与响应示例

以下 JSON 可作为前端请求模板，UUID 为合法示例值，联调时替换为接口返回值。英文版 4.5 提供全部写操作模板。

转账草稿：`POST /transfers/drafts`，同时发送 `Idempotency-Key: transfer-intent-001`。

```json
{
  "source_account_id": "8a9cdd44-3416-595f-865d-75e2f44a8654",
  "destination_account_id": "2cb91352-7c76-4814-bd0c-7b895686940f",
  "amount": "800.00",
  "currency": "CNY"
}
```

预算创建：`POST /budgets`。修改预算时，`PATCH /budgets/{budget_id}` 只发送 limit_amount。

```json
{
  "category": "HOUSEHOLD",
  "month": "2026-10-01",
  "limit_amount": "1500.00",
  "currency": "CNY"
}
```

月度支出响应：

```json
{
  "total": "142.60",
  "by_category": {
    "HOUSEHOLD": "142.60"
  },
  "by_merchant": {
    "Fictional household purchase": "142.60"
  }
}
```

预算状态响应（需与预算列表关联）：

```json
{
  "limit": "1500.00",
  "used": "142.60",
  "remaining": "1357.40",
  "estimate": "142.60",
  "threshold_exceeded": false
}
```

理财申购草稿 `POST /wealth/orders` 和赎回草稿 `POST /wealth/redemptions` 使用相同字段；不同订单意图使用不同幂等键。

```json
{
  "account_id": "8a9cdd44-3416-595f-865d-75e2f44a8654",
  "product_id": "0eb06179-6c76-46db-ac91-2431cbf5da83",
  "amount": "1000.00",
  "idempotency_key": "wealth-intent-001"
}
```

审批创建：`POST /security/approvals`。

```json
{
  "operation_id": "11263eac-2ca5-46da-837d-03697213309d",
  "operation_type": "transfer.commit"
}
```

operation_type 支持 transfer.commit、subscription.cancel、card.limit、card.freeze、card.unfreeze、card.report_lost、wealth.subscribe、wealth.redeem。卡/订阅使用资源 ID，转账/理财使用草稿或订单 ID。card.limit 必须额外传入与提交值完全一致的 amount。

确认审批发送 `{"accepted":true}`，拒绝发送 `{"accepted":false}`。拒绝成功返回 HTTP 200 和 JSON `null`，需要最终状态时再次查询审批。创建 MFA 挑战无需请求体，验证码验证发送 `{"code":"012345"}`，用字符串保留前导零。

确认或验证成功返回：

```json
{
  "authorization_ref": "62df06e2-9bb7-4502-9d35-bda2c1a15ce1",
  "expires_at": "2026-10-23T04:40:00Z"
}
```

转账提交、订阅取消、卡冻结/解冻/挂失、理财提交均发送以下授权体；卡限额修改还需增加 spending_limit。

```json
{
  "authorization_ref": "62df06e2-9bb7-4502-9d35-bda2c1a15ce1"
}
```

分类修正体为 `{"category":"TRANSPORT"}`，续费提醒体为 `{"remind_on":"2026-10-28"}`，测评体为 `{"answers":[1,2,3,4,5]}`。产品比较传 product_ids 数组，必须包含 2–10 个不同产品 ID。

#### 4.5 错误与状态处理

标准错误体：

```json
{
  "code": "INSUFFICIENT_FUNDS",
  "message": "insufficient funds"
}
```

401 表示身份不可用；403 表示无权访问或授权/MFA 问题；404 表示资源不存在；409 表示状态/幂等冲突或余额不足；422 表示请求校验失败；500 表示服务错误。依据 HTTP 状态及 code 显示中文提示，不依据 message 文本编写业务分支。当前 422 仅提供通用信息，没有逐字段错误对象。

HTTP 200 不等于资金操作完成，草稿仍可能待授权。通常通过 X-Trace-Id 关联日志，极少数请求处理链外异常可能没有该响应头，前端需要容忍缺失。

ToolGateway 另用 `{status, data, error_code, message}`，状态为 SUCCESS、WAITING_APPROVAL、MFA_REQUIRED、DENIED、VALIDATION_ERROR、EXECUTION_ERROR，不能套用到普通 REST 响应。UNKNOWN_OUTCOME 是客户端在资金请求超时后的结果分类，并不是后端持久化状态。REST 的 MFA 错误当前可能仍用 AUTHORIZATION_REQUIRED。

传输枚举保持英文：

| 类型 | 值与中文含义 |
|---|---|
| AccountStatus | ACTIVE 有效、FROZEN 冻结、CLOSED 关闭 |
| TransactionStatus | PENDING 待处理、COMPLETED 完成、FAILED 失败、REVERSED 冲正 |
| TransferStatus | DRAFT 草稿、PENDING_AUTHORIZATION 待授权、AUTHORIZED 已授权、PROCESSING 处理中、COMPLETED 完成、FAILED 失败、CANCELLED 取消、EXPIRED 过期 |
| CardStatus | ACTIVE 有效、FROZEN 冻结、LOST 挂失、CANCELLED 注销、EXPIRED 过期 |
| RiskTier | GREEN 绿色、YELLOW 黄色、RED 红色 |
| ApprovalStatus | PENDING 待审批、CONFIRMED 已确认、REJECTED 已拒绝、EXPIRED 过期、CONSUMED 已消费 |
| WealthOrderType | SUBSCRIPTION 申购、REDEMPTION 赎回 |

枚举存在某个值不代表有对应公开操作，例如当前没有转账取消接口。

### 5. 接口地图与联调关系

完整 Method/Path 清单见英文版第 5 节，中英文共用同一接口。按前端模块联调时：

| 页面 | 先读取 | 写操作与恢复 |
|---|---|---|
| 总览/账户 | /accounts → 各账户 /balance；流水 /transactions | 分类 PATCH /transactions/{transaction_id}/category |
| 转账 | /beneficiaries 或 /beneficiaries/resolve | /transfers/drafts → 审批 → /transfers/{draft_id}/commit → /transfers/{transfer_id} |
| 消费/预算 | /analytics/monthly-summary 或 /analytics/spending；/budgets；预算 /status | POST /budgets；PATCH /budgets/{budget_id} |
| 订阅 | /subscriptions；/subscriptions/detect-recurring | 提醒 /reminders；审批后 /cancel |
| 卡 | /cards；/cards/{card_id} | /limit、/freeze、/unfreeze、/report-lost |
| 理财 | /wealth/products、/compare、/recommendations、/holdings | /wealth/risk-assessment；/wealth/orders 或 /redemptions；订单 /commit 与状态读取 |
| 审批 | /security/approvals/{approval_id} | POST /security/approvals；/decision 或 /mfa 后 /security/mfa/{challenge_id}/verify |
| 服务状态 | /health；/health/db | 仅用于健康检查 |

产品列表支持 product_type/risk_tier；月度统计传 year/month。当前没有 /chat、/voice、/savings-pots 路由，不能直接根据页面名构造请求。

独立部署的 Agent API 在单独基地址（开发默认 `http://127.0.0.1:8100`）提供
`POST /agent/requests`。v1 请求包含 `session_id`、`message`、可选会话消息和 locale，
拒绝客户端提供身份、风险、审批、MFA 或授权字段。P2 仅支持单轮：Green 工具可以执行，
写操作停在草稿/待审批边界；持久恢复和 SSE 尚未实现。

P3 持久任务接口包括 `POST /agent/tasks`、`GET /agent/tasks/{task_id}`、
`POST /agent/tasks/{task_id}/resume`、`/cancel`、`/takeover`、
`GET /agent/tasks/{task_id}/events` 与 `/events/stream`。SSE 的 `id` 是单调递增事件
序号，重连发送 `Last-Event-ID`。resume body 只携带带外取得的
`authorization_reference`，不得进入聊天记录、模型消息或浏览器持久存储。主动提醒通过
`PUT /agent/proactive/subscriptions/{event_kind}` 显式订阅并可关闭；提醒只给建议，绝不
自动付款。

### 6. 敏感交互与验收

统一流程：准备意图 → 创建审批 → 展示精确操作 → 黄色确认或红色 MFA → 使用授权提交 → 查询状态 → 展示回执。银行卡/订阅操作直接使用资源 ID，不创建独立草稿。authorization_ref 放在可信应用/会话处理流程，不进入提示词、日志或浏览器持久存储。

绿色用于读取；黄色包括当日累计人民币转出不超过 1,000 元（包含待授权占用）、订阅取消、卡限额/冻结/解冻；红色包括更高累计转账、卡挂失、理财申购/赎回。风险等级从审批响应获取；修改金额或动作需要匹配新操作的审批。

一个转账/理财意图保留一个幂等键。超时后先查状态，不重新生成键盲目重试。若创建草稿超时且没有拿到 ID，重复相同请求和原幂等键恢复。结果未知期间暂存未过期授权，确认完成或过期后清除。

验收重点：总览分区加载；流水分页/筛选；分类/预算修改持久化；同名收款人选择；新业务日演示数据下 800 元黄色转账与 1,500 元红色转账；订阅取消刷新后仍有效；挂失卡不能解冻；测评后适当性下单；资金请求超时可恢复。聊天和储蓄罐可先验收页面设计，完整功能验收需等待对应后端契约。

---

## Appendix / 附录：Supported User Queries（支持的用户查询，后续数据集采集）

This section is intentionally last. These examples describe available banking capabilities; natural-language parsing and voice execution still require the planned agent/speech integration. Planned savings-pot examples must carry a planned-feature label in future datasets.

本节放在全文最后，现阶段不作为前端开发主线。示例对应银行能力，文本/语音的自动理解和调用仍需后续 Agent 与语音接入。储蓄罐数据样例必须标注“规划功能”，不能混入已支持功能标签。

| Domain / 领域 | English example（英文样例） | 中文样例 |
|---|---|---|
| Accounts | Show my accounts and checking balance. | 查看我的账户和活期余额。 |
| Transactions | Show household transactions in October between CNY 100 and 500. | 查看十月份家庭支出类、100 到 500 元的流水。 |
| Category correction | Change this transaction category to TRANSPORT. | 将这笔交易改成交通分类。 |
| Spending | Break this month's spending down by category and merchant. | 按分类和商户统计本月支出。 |
| Beneficiary | Find Alex; ask me to choose if there are multiple matches. | 查找小王，有多个匹配时让我选择。 |
| Transfer | Prepare a CNY 800 transfer and show its approval details. | 准备一笔 800 元转账，并展示确认信息。 |
| Transfer status | Check whether the transfer completed after the timeout. | 刚才请求超时了，查询转账是否完成。 |
| Budget | Create a CNY 1,500 monthly household budget and show remaining allowance. | 设置每月 1,500 元家庭预算并查看剩余额度。 |
| Subscription | Show subscriptions and recurring-payment evidence. | 查看订阅列表及周期扣费线索。 |
| Reminder/cancellation | Create a renewal reminder, then prepare cancellation for confirmation. | 创建续费提醒，并准备取消订阅供我确认。 |
| Cards | Freeze this card; report another card lost after MFA. | 冻结这张卡，并在验证后将另一张卡挂失。 |
| Wealth | Compare two mock products and show suitable products after assessment. | 比较两个模拟理财产品，测评后展示适合的产品。 |
| Wealth order | Prepare a subscription or a supported redemption, then show order status. | 准备申购或支持赎回的订单，再查看订单状态。 |
| Approval | Show the exact amount and recipient before I confirm. | 确认前展示准确金额和收款人。 |
| Savings pot — planned | Create a savings goal and track its progress. | 创建储蓄目标并跟踪进度（规划中）。 |
