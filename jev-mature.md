# FinSAO Jev Mature Expense Plan (v1)

**Status:** Draft for implementation
**Date:** 2026-11-01
**Scope:** everyday expense tracking in chat, Jev intent coverage, expense capture, and transaction-history correctness
**Relationship to existing plans:** extends `plan.md` (Jev cascade) and `plan-track.md` (expense reads/labels). Where this document changes a chat-expense or transaction-history rule, this document is authoritative for that slice. `plan.md` invariants still apply unless explicitly revised here.

---

## 1. Executive summary

The chatbot currently behaves as if it only understands a narrow set of banking commands. In practice:

- `I spent 5 dollars on coke` is routed as `TRACK_EXPENSES` (list expenses), not as a new expense.
- There is no `RECORD_EXPENSE` intent, no expense-create tool, and no Core endpoint for creating an expense.
- Jev’s intent Choice contains the existing read intents, but no expense-recording intent. Jev is also skipped whenever the deterministic router produces any non-`SAFE_FALLBACK` result.
- A completed transfer is written to `transactions` and `ledger_entries`, but the account transaction log hides it because the account transaction endpoint is implemented as an expense query that excludes `INTERNAL_TRANSFER`.

This plan fixes those problems in this order:

1. **Fix transaction history first.** A successful transfer must immediately appear in the account’s transaction history.
2. **Add a canonical tracked-expense model and write API.** Manual/cash expenses must be storable without inventing a bank movement.
3. **Add deterministic expense parsing.** Extract amount, currency, merchant, date, and category from ordinary sentences.
4. **Add expense intents to Jev and to the router.** Jev gets explicit options for recording, editing, deleting, listing, and summarizing expenses.
5. **Keep Jev out of slot extraction.** Jev selects intent only. The parser supplies slots. Jev never supplies tool arguments.
6. **Make pass 2 useful rather than a blanket veto.** Give it structured plan data, a calibrated threshold, and apply it only where a model-generated plan can move money.

The target interaction is:

```text
User: I spent 5 dollars on coke
Agent: Recorded: coke — 5.00 USD — DINING? // or UNKNOWN
       [Undo] [Change category]
```

The agent must not ask for confirmation merely because Jev is uncertain. It must record a tracking entry, preserve `UNKNOWN` when category confidence is low, and offer correction/undo.

---

## 2. Current findings

### 2.1 Router bug: “spent” means “list”, not “record”

`agent/routing.py` contains:

```python
if any(word in normalized for word in ("expense", "expenses", "spending", "spent", ...)):
    ...
    return self._result(
        Intent.TRACK_EXPENSES,
        route=Route.PLANNER,
        ...
    )
```

Therefore `I spent 5 dollars on coke` matches `spent` and becomes `TRACK_EXPENSES`. `BaselinePlanner` then emits a `get_expenses` query. The amount and merchant are ignored.

There is no `RECORD_EXPENSE` enum value and no branch for a completed spend.

### 2.2 Jev has no expense-write option

`HttpJevAdapter._choice_options()` builds options from the current `Intent` enum. The enum has only these expense intents:

- `TRACK_EXPENSES`
- `SUMMARIZE_EXPENSES`
- `CORRECT_EXPENSE_CATEGORY` (excluded from Jev options)

There is no option for:

- recording an expense;
- editing an expense;
- deleting an expense;
- recording income;
- recording a refund;
- splitting an expense.

Adding options alone is insufficient because `HybridRouter` returns the deterministic result whenever it is not `SAFE_FALLBACK`. Jev currently sees only text the rule router cannot classify at all.

### 2.3 Jev Choice criteria are weak

`_choice_options()` emits criteria as:

```python
criteria={name: name for name in options}
```

The model receives intent names with no description. Similar names such as `TRACK_EXPENSES`, `SUMMARIZE_EXPENSES`, and a future `RECORD_EXPENSE` need contrasting definitions, or the Choice will be unstable.

### 2.4 Pass 2 can reject normal plans

`review_plan()` currently sends:

```json
{"user_text": "...", "tools": ["get_accounts"]}
```

It asks whether “the plan’s intent and tool sequence” match, but the plan’s intent is absent. `goal` and `purpose` are intentionally stripped. The returned Noul is therefore judged against incomplete evidence. The `0.5` threshold is hard-coded in `AgentService`, is not calibrated, and is applied to every plan, including deterministic baseline plans.

This is separate from any Jev authentication failure. A local check against the current `.env` key returned HTTP 401 from both `/v1/models` and `/v1/systemone`; that path is `PLAN_REVIEW_UNAVAILABLE`, not `PLAN_REVIEW_REJECTED`.

### 2.5 Transaction history is hidden by the expense query

A completed transfer writes:

- one `transactions` row with category `INTERNAL_TRANSFER`;
- two `ledger_entries` rows: a credit on the source account and a debit on the destination account;
- an updated source and destination balance.

But `GET /accounts/{account_id}/transactions` calls `_expense_page()` and `ExpenseService`, whose base query filters:

```python
LedgerEntryModel.credit > 0
TransactionModel.category.notin_(EXCLUDED_EXPENSE_CATEGORIES)
```

`INTERNAL_TRANSFER` is excluded. The transfer exists but is intentionally hidden from the account transaction log. That is a read-path defect, not a failed write.

`AccountService.get_transactions()` already exists but is unused.

### 2.6 There is no expense write path

Current Core surface is read-only for expenses:

- `GET /transactions`
- `GET /accounts/{id}/transactions`
- `GET /analytics/expenses/summary`
- `PATCH /transactions/{id}/category`
- internal labeling endpoints

There is no create, update, or delete expense endpoint. The frontend cash ledger is device-local (`frontend/aegis-pwa/src/core/ledger.ts`) and does not reach Core or chat.

### 2.7 The taxonomy is too small for “everyday”

Current categories are:

```text
DINING, GROCERIES, TRANSPORT, HOUSEHOLD, ENTERTAINMENT, HEALTHCARE,
EDUCATION, TRAVEL, SHOPPING, UTILITIES, FEES, INTERNAL_TRANSFER,
OPENING_BALANCE, UNKNOWN
```

Missing common day-to-day buckets include personal care, pets, gifts, insurance, taxes, subscriptions, repairs, childcare, and other. `UNKNOWN` must remain valid, but the taxonomy should not force obvious expenses into it.

### 2.8 The frontend infers direction

`frontend/aegis-pwa/src/core/format.ts` infers transaction direction from category because the Core response does not expose debit/credit. Transfers are displayed as “move” by category. This works only while categories are reliable; a real transaction log should expose direction explicitly.

---

## 3. Definitions

### 3.1 Bank transaction

A financial event that posts to one or more bank accounts and has balanced ledger entries. A transfer is a bank transaction. It moves money and appears in account transaction history.

### 3.2 Tracked expense

A user-reported expense that represents money already spent. It does not move money when recorded. It may be:

- bank/card spending already visible in the bank feed;
- cash spending the bank cannot see;
- a manual correction or backfill.

Recording a tracked expense is a data write, not a payment. Paying a merchant is a separate, money-moving operation and must use approval/MFA.

### 3.3 Expense feed

The user-facing list of expenses, including tracked cash/manual expenses and bank expenses. Transfers, opening balances, and internal movements are excluded by default.

### 3.4 Activity feed

The user-facing chronological event feed across bank transactions and tracked expenses. This is what Home/Activity should use when the product wants “everything that happened”.

### 3.5 Jev

Jev selects an intent and returns confidence signals. It does not extract amounts, merchants, dates, accounts, categories, or tool arguments. Category labeling remains the asynchronous derived-label job already defined by `plan-track.md`.

---

## 4. Principles

1. **A completed transfer is visible immediately.** There is no such thing as a successful balance change with no history row.
2. **Expense capture is not payment.** “I spent 5 dollars on coke” records a fact; it does not debit an account.
3. **The deterministic parser owns slots.** Amount, currency, merchant, date, and account scope are parsed or clarified, never invented by Jev.
4. **Jev supplies intent only.** Jev never supplies tool arguments or expands capabilities.
5. **UNKNOWN is acceptable.** A recorded expense with an uncertain category is better than a failed capture. The labeling worker can improve it later.
6. **Low-risk tracking writes are reversible.** Record first, offer undo/edit. Do not turn category uncertainty into a clarification loop.
7. **Money-moving writes remain fail-closed.** Transfers, payments, card actions, and wealth orders keep approval/MFA and pass-2 veto behavior.
8. **Every reject is diagnosable.** Distinguish authentication failure, timeout, low confidence, out-of-scope, injection, and plan mismatch with distinct error codes and non-PII telemetry.
9. **Feature flags preserve baseline behavior.** Expense capture, Jev expense routing, and transaction-history changes are independently gated during rollout.
10. **No financial arithmetic in a model.** Totals and summaries remain Core/database computations.

---

## 5. Target intent model

Add these intents:

```text
RECORD_EXPENSE
UPDATE_EXPENSE
DELETE_EXPENSE
CORRECT_EXPENSE_CATEGORY   (existing; allow chat with confirmation)
RECORD_INCOME              (phase 2)
RECORD_REFUND              (phase 2)
SPLIT_EXPENSE              (phase 2)
PAY_MERCHANT               (phase 2/3; money-moving, separate from tracking)
```

Keep existing:

```text
TRACK_EXPENSES
SUMMARIZE_EXPENSES
ANALYZE_SPENDING
LIST_BUDGETS
GET_BUDGET_STATUS
CREATE_BUDGET
UPDATE_BUDGET
LIST_SUBSCRIPTIONS
DETECT_RECURRING
CANCEL_SUBSCRIPTION
TRANSFER
```

### 5.1 Intent catalog

| Intent | Example | Required slots | Mutates | Default route | Jev option |
|---|---|---|---|---|---|
| `RECORD_EXPENSE` | “I spent 5 dollars on coke” | amount, currency, merchant | tracking write | `PLANNER` | yes |
| `TRACK_EXPENSES` | “show my dining expenses this month” | none | no | `PLANNER` | yes |
| `SUMMARIZE_EXPENSES` | “how much did I spend on food this month” | none | no | `PLANNER` | yes |
| `UPDATE_EXPENSE` | “change the coke expense to 6 dollars” | expense reference, patch | tracking write | `PLANNER` | yes |
| `DELETE_EXPENSE` | “delete the taxi expense” | expense reference | tracking write | `PLANNER` | yes |
| `CORRECT_EXPENSE_CATEGORY` | “that was groceries, not dining” | expense reference, category | tracking write | `PLANNER` | yes (confirmation) |
| `RECORD_INCOME` | “I got paid 5000 yuan” | amount, currency, source | tracking write | `PLANNER` | yes (phase 2) |
| `RECORD_REFUND` | “Coke refunded me 5 dollars” | amount, currency, merchant | tracking write | `PLANNER` | yes (phase 2) |
| `SPLIT_EXPENSE` | “split this 100 yuan lunch with Alice” | expense reference, people | tracking write | `CLARIFY` | yes (phase 2) |
| `PAY_MERCHANT` | “pay Coke 5 dollars” | account, amount, merchant/recipient | money movement | approval path | yes (phase 3) |

`PAY_MERCHANT` must never be folded into `RECORD_EXPENSE`. A past-tense statement records; an imperative payment moves money.

### 5.2 Intent precedence

The deterministic router must apply this order before generic expense-query matching:

1. explicit money-moving imperative (`send`, `transfer`, `pay`, `buy`, `subscribe`);
2. explicit completed spend (`spent`, `paid`, `bought`, `cost`, `charged` + amount, or an amount + merchant phrase);
3. expense updates/deletes/corrections;
4. expense summaries;
5. expense listing;
6. generic spending analysis;
7. Jev/LLM fallback.

This prevents `spent` from falling into `TRACK_EXPENSES`.

---

## 6. Expense capture contract

### 6.1 Canonical data model

Extend `TransactionModel` rather than creating a second expense table. One table avoids double counting and keeps IDs stable.

Add:

```text
user_id                 FK users, nullable during backfill, required for manual rows
account_id              FK accounts, nullable for cash/manual expenses
kind                    EXPENSE | INCOME | REFUND | TRANSFER | OPENING_BALANCE | ADJUSTMENT
origin                  BANK | CARD | CASH | MANUAL | IMPORT
merchant                normalized display merchant, nullable
idempotency_key         nullable; unique per user where present
deleted_at              nullable soft delete for manual rows
```

Existing columns remain:

```text
reference, status, amount, currency, description, category,
category_source, category_version, category_labeled_at, posted_at
```

Backfill rules:

- `OPENING_BALANCE` category → `kind=OPENING_BALANCE`, `origin=BANK`.
- `INTERNAL_TRANSFER` category → `kind=TRANSFER`, `origin=BANK`.
- ledger credit on an owned account → `kind=EXPENSE`.
- ledger debit on an owned account without a matching credit on another owned account → `kind=INCOME`.
- set `user_id` and `account_id` from the joined ledger account.
- set `origin=BANK` for all pre-existing rows.
- `merchant` may be backfilled from a deterministic merchant extractor; otherwise null.

Manual tracked expense:

- `kind=EXPENSE`;
- `origin=CASH` or `MANUAL`;
- `user_id` set;
- `account_id` optional and informational only;
- no ledger entries;
- no balance change;
- `posted_at` is the user-reported occurrence time;
- `description` is the user-facing merchant/note;
- `category` may be `UNKNOWN`;
- `category_source` is `USER`, `RULE`, or `UNKNOWN` as appropriate.

Ledger invariant:

- bank-origin rows must have balanced ledger entries;
- manual/cash rows have no ledger entries;
- the ledger invariant verifier must skip manual rows, not fail them.

### 6.2 Core API

Add:

```text
POST   /expenses
GET    /expenses/{expense_id}
PATCH  /expenses/{expense_id}
DELETE /expenses/{expense_id}
```

`POST /expenses` request:

```json
{
  "amount": "5.00",
  "currency": "USD",
  "merchant": "coke",
  "category": null,
  "occurred_at": "2026-11-01T12:30:00+08:00",
  "account_id": null,
  "origin": "CASH",
  "note": null
}
```

Rules:

- `Idempotency-Key` header is required; unique per `(user_id, idempotency_key)`.
- `amount > 0`, at most two decimal places.
- `currency` from the supported enum; no implicit FX.
- `merchant` is normalized with NFKC, whitespace collapse, case-fold for matching, bounded to 80 characters for storage.
- `category` must be in the shared taxonomy; null/`UNKNOWN` is allowed.
- `occurred_at` defaults to now in `BUSINESS_TIMEZONE`; future times beyond a small clock skew are rejected or clarified.
- `account_id` is validated as owned if supplied, but no balance changes.
- response includes `id`, `amount`, `currency`, `merchant`, `category`, `category_source`, `occurred_at`, `origin`, `status`, `created_at`.
- delete is a soft delete; audit event records the action.
- update is limited to amount, currency, merchant, category, occurred_at, note, and account metadata. It never changes `kind` or origin.

Keep existing read endpoints:

- `GET /transactions` remains the expense feed for compatibility, but its query moves to the new `kind`/`user_id` model.
- `GET /analytics/expenses/summary` uses the same model.
- `GET /accounts/{id}/transactions` becomes bank history, not an expense query.
- Add `GET /activity` for a user-scoped chronological feed across bank and manual rows.

### 6.3 Agent tools

Add typed tools:

```text
record_expense(amount, currency, merchant, category?, occurred_at?, account_id?, origin?, note?)
update_expense(expense_id, patch)
delete_expense(expense_id)
get_expense(expense_id)
```

Add Core actions:

```text
expenses.create
expenses.update
expenses.delete
expenses.query
expenses.summary
expenses.correct_category
```

`record_expense`, `update_expense`, and `delete_expense` are `mutates_data=True` even though no bank balance moves. They must still be capability-scoped and audited.

`CapabilityBroker` mappings:

```python
Intent.RECORD_EXPENSE: {"expenses.create"}
Intent.UPDATE_EXPENSE: {"expenses.query", "expenses.update"}
Intent.DELETE_EXPENSE: {"expenses.query", "expenses.delete"}
Intent.CORRECT_EXPENSE_CATEGORY: {"expenses.query", "expenses.correct_category"}
```

### 6.4 Planner behavior

`BaselinePlanner` should build a single-step plan:

- `record_expense` from parsed slots;
- `update_expense` with a trusted expense ID and patch;
- `delete_expense` with a trusted expense ID.

`HybridPlanner` must not ask the LLM to extract amount, currency, merchant, or date for `RECORD_EXPENSE`. If the deterministic parser produced complete slots, use the baseline plan. If slots are incomplete, clarify. The LLM may only be used for an expense reference resolution or a deterministic-plan repair that does not invent financial literals.

### 6.5 Confirmation and undo

- `RECORD_EXPENSE` is auto-recorded when amount, currency, and merchant are explicit.
- Category may be `UNKNOWN`; do not block capture.
- Return an undo token or the created expense ID and allow “undo”, “change to DINING”, or “delete”.
- If amount or merchant is missing, clarify.
- If multiple accounts/currencies are plausible, clarify; do not guess.
- No approval/MFA for tracking-only writes.
- A future `PAY_MERCHANT` uses the existing approval/MFA path and is never auto-executed.

---

## 7. Deterministic expense parser

### 7.1 Required behavior

Implement a deterministic zh/en parser before Jev. It must extract or explicitly mark ambiguous:

- amount;
- currency;
- merchant;
- occurrence date/time;
- optional category;
- optional account scope from trusted structured input only;
- optional payment origin.

### 7.2 Amount and currency

Support:

```text
I spent 5 dollars on coke
I spent $5 on coke
I paid 5 USD for coke
coke 5 dollars
lunch was 25 yuan
taxi 30 元
coffee cost me 18.50
```

Rules:

- amount must be positive and have at most two decimal places;
- do not parse identifiers, dates, or account numbers as amounts;
- map `$`, `USD`, `dollar`, `dollars` → `USD`;
- map `¥`, `CNY`, `RMB`, `yuan`, `元` → `CNY`;
- map `€`, `EUR`, `euro` → `EUR`;
- if no currency is stated, use the user’s default currency only if unambiguous; otherwise clarify;
- no FX conversion in v1.

### 7.3 Merchant

Extract after markers:

```text
on, for, at, from, to
买, 买了, 在, 花了 ... 买
```

Strip trailing punctuation and time phrases. Normalize with NFKC and whitespace collapse. Bound to 80 characters. Do not parse an account number, card number, user ID, or URL as a merchant.

For `I spent 5 dollars on coke`, merchant is `coke`.

### 7.4 Date

Support:

- today, yesterday, last night, this morning;
- explicit ISO date;
- `on 5 Oct`, `10月5日`;
- “just now”;
- “last Friday” only if the anchor date is unambiguous.

Use `BUSINESS_TIMEZONE` and store timezone-aware UTC. If a phrase has two reasonable interpretations, clarify.

### 7.5 Category

Use a deterministic, versioned alias table in `shared/expense_taxonomy.py`.

Examples:

```text
coffee, lunch, dinner, restaurant, takeout -> DINING
supermarket, grocery, milk, eggs -> GROCERIES
taxi, metro, bus, fuel, parking -> TRANSPORT
rent, utilities, electricity, water, internet -> HOUSEHOLD/UTILITIES
pharmacy, clinic, hospital -> HEALTHCARE
netflix, spotify, subscription -> ENTERTAINMENT/SUBSCRIPTIONS
```

If no alias matches with sufficient confidence, store `UNKNOWN`. Do not call Jev synchronously for category in v1. The async labeling worker can fill it later.

### 7.6 Multi-expense input

v1 supports one expense per utterance. “coffee 5 and taxi 20” returns a clarification or a preview with two candidate rows. Multi-row capture is phase 2.

---

## 8. Jev changes

### 8.1 Add expense intents to the Choice

Add `RECORD_EXPENSE`, `UPDATE_EXPENSE`, `DELETE_EXPENSE`, and phase-2 intents to `Intent` and to `_choice_options()`.

Do not include `CORRECT_EXPENSE_CATEGORY` until the UI-only restriction is intentionally lifted. When lifted, mark it as requiring an existing expense reference.

### 8.2 Give every option a description

Replace `{name: name}` with meaningful criteria. Example:

```python
criteria = {
    "RECORD_EXPENSE": "The user reports money already spent and gives an amount or merchant; create a tracked expense.",
    "TRACK_EXPENSES": "The user asks to view, list, filter, or sort existing expenses.",
    "SUMMARIZE_EXPENSES": "The user asks for totals, averages, or grouped spending, not individual rows.",
    "UPDATE_EXPENSE": "The user asks to change an existing expense's amount, merchant, date, or note.",
    "DELETE_EXPENSE": "The user asks to remove an existing expense.",
    "CORRECT_EXPENSE_CATEGORY": "The user corrects the category of an existing expense.",
    "TRANSFER": "The user asks to move money to another account or person.",
    ...
}
```

Every option should have a one-sentence boundary statement. The text must make clear that:

- `RECORD_EXPENSE` is past-tense reporting;
- `TRACK_EXPENSES` is reading;
- `SUMMARIZE_EXPENSES` is aggregation;
- `PAY_MERCHANT`/`TRANSFER` is future money movement.

### 8.3 Jev routing policy

Keep `plan.md`’s rule-first behavior:

- deterministic router handles clear cases;
- Jev runs only when the deterministic route is `SAFE_FALLBACK`;
- Jev may select `RECORD_EXPENSE` only when the deterministic parser has already extracted amount and merchant;
- Jev output never supplies slots;
- if Jev is unavailable, the deterministic parser/planner path still records a clear expense;
- Jev may not downgrade a clear write into a read or vice versa.

### 8.4 Jev expense classification request

Add a scoped expense observation for ambiguous cases:

```json
{
  "intent": "Choice",
  "is_expense": "Noul",
  "injection": "Noul",
  "in_scope": "Noul"
}
```

Options include `RECORD_EXPENSE`, `TRACK_EXPENSES`, `SUMMARIZE_EXPENSES`, `UPDATE_EXPENSE`, `DELETE_EXPENSE`, and the existing non-expense intents.

Forward/reverse orderings remain required. If order is inconsistent, fall back to the deterministic parser; do not block recording a clear tracking expense.

Do not ask Jev for:

- amount;
- currency;
- merchant text;
- date;
- account ID;
- transaction ID;
- category as a tool argument.

### 8.5 Pass 1 thresholds

Introduce separate, configurable thresholds:

```text
JEV_INTENT_MIN_CONFIDENCE=0.80
JEV_EXPENSE_INTENT_MIN_CONFIDENCE=0.75
JEV_MAX_INJECTION=0.03
JEV_MIN_IN_SCOPE=0.97
JEV_REQUIRE_ORDER_CONSISTENT=true
```

For `RECORD_EXPENSE`, low Jev confidence must not block a deterministic, complete expense. It should only affect whether Jev’s suggested intent is used.

### 8.6 Pass 2 repair

`review_plan()` state must become structured:

```json
{
  "user_text": "<redacted>",
  "intent": "RECORD_EXPENSE",
  "steps": [
    {
      "tool": "record_expense",
      "argument_sources": {
        "amount": "USER_EXPLICIT",
        "currency": "USER_EXPLICIT",
        "merchant": "USER_EXPLICIT",
        "category": "SYSTEM_CONSTANT"
      }
    }
  ]
}
```

Rules:

- no raw amounts, account IDs, transaction IDs, or merchant text beyond the redacted user text;
- no `goal` or `purpose`;
- ask one Noul with explicit true/false criteria;
- make the threshold configurable (`JEV_PLAN_REVIEW_MIN`, proposed `0.7`);
- run pass 2 only on model-generated plans and money-moving mutations;
- for tracking-only `RECORD_EXPENSE`, pass 2 is advisory or skipped; a low score cannot silently discard a user’s explicit expense;
- if pass 2 is unavailable, money-moving plans fail closed; tracking writes proceed with validation and undo.

### 8.7 Authentication and availability

The current local key is rejected with HTTP 401. Treat this as a configuration failure, not a model decision.

- On startup, if `JEV_ENABLED=true`, validate the key against `GET /v1/models`.
- In production, fail fast with a clear non-secret error code.
- In development, disable Jev and log `JEV_AUTH_INVALID`; do not return `PLAN_REVIEW_REJECTED`.
- Add a circuit breaker after repeated 401/429/5xx/timeout failures.
- Surface distinct error codes:
  - `JEV_AUTH_INVALID`
  - `JEV_TIMEOUT`
  - `JEV_UNAVAILABLE`
  - `JEV_LOW_CONFIDENCE`
  - `JEV_OUT_OF_SCOPE`
  - `JEV_INJECTION`
  - `PLAN_REVIEW_REJECTED`
  - `PLAN_REVIEW_UNAVAILABLE`

### 8.8 Jev is not the expense extractor

Jev’s role remains:

1. intent selection when deterministic routing is inconclusive;
2. veto-only plan review for high-risk plans;
3. asynchronous category labeling.

It is not a slot extractor. “Read 5 dollars and coke” is the deterministic parser’s job.

---

## 9. Transaction history fix

### 9.1 Root cause

`GET /accounts/{account_id}/transactions` uses `ExpenseService`, which:

- joins only ledger entries with `credit > 0`;
- excludes `INTERNAL_TRANSFER` and `OPENING_BALANCE`.

A transfer out is a credit on the source account with category `INTERNAL_TRANSFER`, so it is excluded. The transaction exists; the read path hides it.

### 9.2 Required route behavior

`GET /accounts/{account_id}/transactions` must return all ledger-backed activity for that account, including:

- expenses;
- income;
- transfers in and out;
- opening balances;
- adjustments.

It must not use the expense exclusion rules. It should use a dedicated account-history query, for example a new `TransactionHistoryService` or the existing `AccountService.get_transactions()` with sorting added.

### 9.3 Response fields

Extend `TransactionResponse` with:

```text
account_id: UUID | null
direction: DEBIT | CREDIT | MOVE
origin: BANK | CARD | CASH | MANUAL | IMPORT
merchant: str | null
kind: EXPENSE | INCOME | REFUND | TRANSFER | OPENING_BALANCE | ADJUSTMENT
```

For account history:

- source-side transfer entry → `direction=DEBIT`, `kind=TRANSFER`;
- destination-side transfer entry → `direction=CREDIT`, `kind=TRANSFER`;
- expense → `direction=DEBIT`;
- income → `direction=CREDIT`.

Keep `amount` positive; direction carries the sign.

### 9.4 Endpoint split

Use distinct semantics:

```text
GET /accounts/{account_id}/transactions   bank history for one account
GET /activity                            all user activity, including manual expenses
GET /transactions                        expense feed (bank + manual; excludes transfers)
GET /analytics/expenses/summary          expense aggregates
```

Do not overload one route with both “bank history” and “expense report”.

### 9.5 Frontend

- `Home.loadRecent()` should use `/activity` for the “History” section so cash/manual expenses and transfers appear.
- Account detail views should use `/accounts/{id}/transactions`.
- `direction(tx)` should prefer `tx.direction` and fall back to category only for older responses.
- `TxRow` should display `DEBIT` as negative, `CREDIT` as positive, and `TRANSFER` as “moved”.
- Add labels for new categories and origins.

### 9.6 Regression test

Add a PostgreSQL integration test:

1. create a transfer draft;
2. commit it;
3. assert source balance decreased and destination increased;
4. `GET /accounts/{source}/transactions` includes exactly one `TRANSFER` row with `direction=DEBIT`;
5. `GET /accounts/{destination}/transactions` includes exactly one `TRANSFER` row with `direction=CREDIT`;
6. `GET /transactions` does not include the transfer;
7. `GET /analytics/expenses/summary` is unchanged by the transfer;
8. `GET /activity` includes the transfer exactly once for the initiating user.

---

## 10. Category taxonomy and merchant aliases

### 10.1 Proposed taxonomy

```text
DINING
GROCERIES
TRANSPORT
HOUSEHOLD
UTILITIES
ENTERTAINMENT
SUBSCRIPTIONS
HEALTHCARE
EDUCATION
CHILDCARE
TRAVEL
SHOPPING
PERSONAL_CARE
PETS
GIFTS
INSURANCE
TAXES
FEES
REPAIRS
OTHER
INTERNAL_TRANSFER
OPENING_BALANCE
UNKNOWN
```

Additions require:

- shared taxonomy update;
- UI labels in both locales;
- Jev labeling criteria update;
- evaluation dataset update;
- no unversioned category strings.

### 10.2 Alias policy

Keep a versioned alias file:

```text
coke, cola, soda -> GROCERIES (default; user may correct to DINING)
coffee, latte -> DINING
taxi, didi, uber -> TRANSPORT
rent -> HOUSEHOLD
electricity, water, internet, phone -> UTILITIES
netflix, spotify, icloud -> SUBSCRIPTIONS
```

Alias labels are deterministic `RULE` labels, not Jev labels. A user correction always becomes `USER` and wins.

---

## 11. Files to change

### Agent

- `agent/routing.py`: add intents, required slots, precedence, explicit spend patterns.
- `agent/context.py`: add `RECORD_EXPENSE` slot extraction and expense-reference extraction.
- `agent/planning.py`: add expense plans and tools.
- `agent/expenses.py`: include new intents in feature gating.
- `agent/capabilities.py`: add expense write actions.
- `agent/jev_http.py`: add intent options and criteria; structured pass-2 state.
- `agent/hybrid.py`: Jev expense intent handling; baseline planning for deterministic expense slots.
- `agent/service.py`: pass-2 scope and configurable threshold; undo metadata.
- `agent/review.py`: redact pass-2 text; never include raw amounts/IDs.
- `agent/config.py`: Jev thresholds, expense flags, auth validation.
- `agent/app.py`: wire expense tools and Jev startup checks.
- `agent/localization.py`: expense labels, messages, fallback text.

### Agent tools

- `agent_tools/tools.py` or new `agent_tools/expense_tools.py`: record/update/delete/get expense tools.
- `agent_tools/registry.py`: register new tools.

### Banking Core

- `banking_core/app/persistence/models.py`: transaction kind/origin/user/merchant/idempotency/deleted_at.
- `banking_core/app/services/expenses.py`: query by user/kind, include manual rows.
- `banking_core/app/services/analytics.py`: use the unified expense model.
- `banking_core/app/services/accounts.py`: account history with direction.
- new `banking_core/app/services/transaction_history.py` if needed.
- `banking_core/app/api/banking.py`: create/update/delete expense, activity, fixed account history.
- `banking_core/app/api/analytics.py`: stop using ledger-only expense joins.
- `banking_core/app/schemas/banking.py`: response fields and expense request models.
- `banking_core/app/domain/enums.py`: `TransactionKind`, `TransactionOrigin`, `Direction`.

### Shared

- `shared/expense_taxonomy.py`: categories, aliases, normalization, version.

### Migrations

- add transaction kind/origin/user/merchant/idempotency/deleted_at;
- backfill existing transactions;
- add indexes for `(user_id, kind, posted_at)`, `(user_id, idempotency_key)`, `(account_id, posted_at)`;
- no destructive column removal.

### Frontend

- `frontend/aegis-pwa/src/core/types.ts`: direction, origin, kind.
- `frontend/aegis-pwa/src/core/format.ts`: prefer API direction.
- `frontend/aegis-pwa/src/screens/Home.tsx`: use `/activity`.
- `frontend/aegis-pwa/src/screens/Activity.tsx`: use `/activity`.
- `frontend/aegis-pwa/src/screens/Track.tsx`: show manual expenses.
- `frontend/aegis-pwa/src/core/i18n.ts`: new categories, origin, undo, captured messages.

---

## 12. Phased implementation

### Phase 0 — Guardrails and diagnosis

1. Add Jev startup auth check and distinct error codes.
2. Add non-secret telemetry for pass-1/pass-2 scores and failure reasons.
3. Make `JEV_PLAN_REVIEW_MIN` configurable; default 0.7 for money-moving plans.
4. Add feature flags:
   - `EXPENSE_CAPTURE_ENABLED=false`
   - `EXPENSE_CAPTURE_CHAT_ENABLED=false`
   - `JEV_EXPENSE_ROUTING_ENABLED=false`
5. Document that Jev is not required for deterministic capture.

**Exit:** an invalid key disables Jev with `JEV_AUTH_INVALID`; no `PLAN_REVIEW_REJECTED` for auth failures.

### Phase 1 — Transaction history fix (ship first)

1. Add account-history query independent of `ExpenseService`.
2. Add `direction`, `origin`, `kind`, `merchant` response fields.
3. Wire `GET /accounts/{id}/transactions` to account history.
4. Add `GET /activity` for the unified feed.
5. Update frontend Home/Activity.
6. Add the transfer visibility regression test.

**Exit:** completed transfers appear immediately in both account history and activity; expense summaries still exclude them.

### Phase 2 — Expense write model and Core API

1. Add migration and backfill.
2. Add `POST/PATCH/DELETE /expenses`.
3. Add idempotency and soft delete.
4. Update expense queries and analytics to the unified model.
5. Add audit events for create/update/delete.
6. Add tests for manual cash expenses with no ledger entries.

**Exit:** a manual USD cash expense can be created, listed, updated, deleted, and included in summaries without changing any account balance.

### Phase 3 — Deterministic parser and intents

1. Add `RECORD_EXPENSE`, `UPDATE_EXPENSE`, `DELETE_EXPENSE`.
2. Add parser for amount/currency/merchant/date.
3. Add expense category aliases.
4. Add intent precedence.
5. Add baseline plans and tools.
6. Add “undo” and “change category” flows.
7. Add feature gate for chat capture.

**Exit:** `I spent 5 dollars on coke` creates a tracked expense with amount `5.00`, currency `USD`, merchant `coke`, category `DINING` or `UNKNOWN`, without asking for clarification.

### Phase 4 — Jev expense routing

1. Add expense intents to the Jev Choice.
2. Add descriptive criteria.
3. Add forward/reverse consistency checks.
4. Add Jev expense thresholds.
5. Keep Jev only for ambiguous cases.
6. Add tests that Jev-selected `RECORD_EXPENSE` cannot supply slots.
7. Add tests that Jev low confidence does not block deterministic capture.

**Exit:** ambiguous “coke 5” can be classified as `RECORD_EXPENSE` by Jev, but the parser still owns the values.

### Phase 5 — Pass-2 maturity

1. Send structured plan state.
2. Add true/false Noul criteria.
3. Apply pass 2 only to model-generated money-moving plans.
4. Make threshold configurable.
5. Add tests for normal expense plans not being vetoed.
6. Add tests for transfer plans still being vetoed when inconsistent.

**Exit:** normal expense capture never fails with `PLAN_REVIEW_REJECTED`; a mismatched transfer plan still fails closed.

### Phase 6 — Phase-2 intents

1. `RECORD_INCOME`.
2. `RECORD_REFUND` and refund policy.
3. `SPLIT_EXPENSE`.
4. `PAY_MERCHANT` with approval/MFA.

**Exit:** money-moving merchant payments are distinct from tracking writes and always require approval.

### Phase 7 — Evaluation and rollout

1. Build the zh/en expense-intent and slot dataset.
2. Add golden traces for all flagship sentences.
3. Run with flags off and on.
4. Calibrate Jev thresholds on the dev split only.
5. Roll out Jev expense routing; keep capture deterministic.
6. Publish precision/coverage and false-reject metrics.

---

## 13. Test matrix

### Router and parser

- “I spent 5 dollars on coke” → `RECORD_EXPENSE`, amount 5.00, USD, merchant coke.
- “I spent 5 on coke” → currency clarification or default, not `TRACK_EXPENSES`.
- “lunch was 25 yuan” → CNY, merchant lunch, DINING.
- “taxi 30” → TRANSPORT.
- “show my expenses” → `TRACK_EXPENSES`.
- “how much did I spend on food” → `SUMMARIZE_EXPENSES`.
- “send 100 to mom” → `TRANSFER`, not `RECORD_EXPENSE`.
- “pay Coke 5 dollars” → payment/approval path, not tracking.
- “change the coke expense to 6” → `UPDATE_EXPENSE`.
- “delete the taxi expense” → `DELETE_EXPENSE`.
- Chinese equivalents for each.

### Jev

- intent Choice includes `RECORD_EXPENSE`;
- criteria differentiate record/list/summarize;
- forward/reverse inconsistency does not produce a write;
- Jev low confidence does not discard a deterministic complete expense;
- Jev cannot populate amount/currency/merchant/date;
- 401 produces `JEV_AUTH_INVALID`, not `PLAN_REVIEW_REJECTED`;
- pass-2 state contains intent/tool names and source kinds only;
- normal expense plan is not vetoed;
- mismatched transfer plan is vetoed.

### Core

- manual expense creates no ledger entry and no balance change;
- bank expense remains ledger-balanced;
- idempotent create returns the same row;
- duplicate create with different payload returns conflict;
- soft delete hides from default lists;
- update preserves `USER` category precedence;
- mixed currency is grouped, never summed silently;
- transfer appears in account history and activity;
- transfer excluded from expense list and summary;
- opening balance appears in account history, excluded from expenses;
- cross-user access rejected;
- account history direction is correct.

### Frontend

- transfer shows as a movement in Activity;
- manual expense shows in Activity and expense feed;
- account detail shows transfer debit/credit;
- category correction updates the row;
- undo removes a just-created manual expense;
- no direction inference from category when `direction` is present.

### Evaluation

- intent accuracy per language;
- exact amount/currency/merchant match;
- false-record rate;
- missed-record rate;
- duplicate-record rate;
- clarification rate;
- Jev pass-2 false reject rate;
- latency and external call count.

---

## 14. Acceptance criteria

1. `I spent 5 dollars on coke` records an expense. It does not list expenses.
2. The recorded row has amount, currency, merchant, timestamp, and a category (`UNKNOWN` allowed).
3. The user can undo, edit, or recategorize without a second model call.
4. Jev is not required for this flow; deterministic capture works with Jev disabled.
5. Jev’s intent options include recording, reading, summarizing, updating, and deleting expenses.
6. Jev never supplies amount, currency, merchant, date, account, or category as a tool argument.
7. A completed transfer appears immediately in the account transaction history and activity feed.
8. Transfers remain excluded from expense lists and summaries.
9. Pass 2 does not reject a normal tracking expense.
10. A mismatched money-moving plan still fails closed.
11. Invalid Jev credentials produce a configuration error, not a plan rejection.
12. All new behavior is behind independently switchable flags.
13. Tests cover zh/en phrases, transfer visibility, manual expense creation, and Jev failure modes.

---

## 15. Open decisions

| Decision | Recommendation | Why |
|---|---|---|
| Does “I spent” debit an account? | No. It records a tracked expense only. | The money was already spent; recording must not double-charge. |
| Default currency when omitted | Clarify unless the user has a single unambiguous default. | Prevents silent CNY/USD errors. |
| Default account when omitted | No account needed for tracking; use optional metadata. | Cash expenses have no bank account. |
| Category when uncertain | Store `UNKNOWN`; label asynchronously. | Capture must not fail on taxonomy uncertainty. |
| Pass-2 threshold | Configurable, default 0.7, only for money-moving plans. | 0.5 is a coin flip; blanket veto is wrong. |
| Jev intent threshold for expenses | 0.75, lower than money-moving routing. | Missing a common capture is costlier than a wrong read intent. |
| Multi-expense utterance | Clarify or preview in v1; batch in phase 2. | Avoid silently splitting amounts. |
| Duplicate bank/cash records | No automatic dedupe in v1; expose link/delete. | Matching bank rows to reported cash rows needs a separate design. |
| Soft delete vs hard delete | Soft delete with audit. | Recoverability and analytics integrity. |
| Category taxonomy expansion | Approve the proposed list before phase 2 migration. | Taxonomy is shared across Core, Agent, Jev, UI, and evaluation. |

---

## 16. Risks and mitigations

| Risk | Mitigation |
|---|---|
| `spent` continues to route to `TRACK_EXPENSES` | Add precedence tests before any Jev work. |
| Jev key remains invalid | Startup check; disable Jev; deterministic capture still works. |
| Pass 2 rejects all expenses | Skip or downgrade pass 2 for tracking writes; structured state; calibrated threshold. |
| Manual expenses double-count bank expenses | v1 records only user-reported rows; add linking/dedupe before importing bank rows. |
| Transaction backfill assigns the wrong user | Backfill from ledger/account ownership; fail the migration on ambiguous rows. |
| Account history still excludes transfers | Dedicated history query; regression test with a committed transfer. |
| Jev criteria become too large | Use concise descriptions; evaluate order consistency; keep only intents in active use. |
| LLM invents merchant/amount | Deterministic parser owns slots; LLM cannot supply financial literals. |
| Cash expenses disappear from analytics | Unified expense query by `user_id`/`kind`; test manual rows. |
| Currency confusion | No FX in v1; explicit currency or clarification. |

---

## 17. Out of scope for this plan

- real-time bank/card webhook ingestion;
- automatic expense matching/deduplication across bank and cash;
- FX conversion;
- receipt OCR backend implementation;
- multi-user shared expenses and settlement;
- investment/tax advice;
- changing the existing transfer approval/MFA policy;
- enabling `JEV_DIRECT`.

---

## 18. Final target flow

```text
User: I spent 5 dollars on coke
  -> RuleRouter: explicit completed-spend pattern
  -> Deterministic parser:
       amount=5.00
       currency=USD
       merchant=coke
       occurred_at=now
       category=GROCERIES or UNKNOWN
  -> BaselinePlanner: record_expense
  -> CapabilityBroker: expenses.create
  -> PlanVerifier: schema + provenance
  -> Core: POST /expenses (idempotent, no balance change)
  -> Agent: "Recorded coke 5.00 USD. [Undo] [Change category]"
```

```text
User: send 100 to mom
  -> RuleRouter: TRANSFER
  -> Jev pass 2: optional, structured, veto-only
  -> approval/MFA
  -> Core: transfer draft + commit
  -> transactions + ledger entries
  -> GET /accounts/{source}/transactions shows DEBIT TRANSFER
  -> GET /accounts/{destination}/transactions shows CREDIT TRANSFER
  -> expense list/summary still excludes INTERNAL_TRANSFER
```
