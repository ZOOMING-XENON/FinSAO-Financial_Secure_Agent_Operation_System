[中文](SECURITY_SELF_ASSESSMENT.md) | English

# Aegis Security Self-Assessment

> **Scope statement.** Aegis is a competition prototype operating on fictional users, accounts, and funds. It is not connected to a real payment network and is not a production banking system. This document distinguishes implemented controls, simulation-only controls, and known production gaps. It is a security self-assessment, not a penetration test, certification, or compliance attestation.

## 1. Executive assessment

Aegis places the security boundary in the **Banking Core**, not in the language model. The model may propose intent, parameters, and plans; it cannot supply identity, risk tier, approval state, MFA codes, authorization references, balances, or successful outcomes. Every financial write is revalidated and committed by Core inside a database transaction.

**Overall posture:** strong deterministic control plane for a competition prototype; **not production-ready** until identity, transport security, rate limiting, centralized audit, fraud monitoring, and operational controls are added.

| Area | Assessment | Summary |
|---|---|---|
| Permission tiers | Implemented | Green / Yellow / Red enforced by Core policy; unknown actions fail closed |
| Approval binding | Implemented | Payload-hash bound, expiring, single-use grants; commit-time recheck |
| Anti-hallucination | Implemented with limits | Typed tools, provenance, plan verification, Core-only truth; model intent can still be wrong |
| Prompt injection | Layered mitigation | Rules, model signals, evidence checks, capability narrowing; not a formal guarantee |
| Audit | Partial | Trace IDs and audit events exist; no centralized, tamper-evident, retention-managed store |
| Safety lock | Partial | MFA failure lock only; no global suspicious-behaviour or velocity engine |
| Sandbox | Not applicable | The Agent executes no model-generated code; no code sandbox exists |
| Financial integrity | Implemented with limits | Decimal, idempotency, row locks, double-entry ledger; balance reconciliation is absent |
| Production readiness | Not achieved | Development identity, static tokens, HTTP-only service links, no rate limiting |

## 2. Trust model and enforcement boundary

| Layer | Trust level | Authority |
|---|---|---|
| User, browser, uploaded files, chat text | Untrusted | May request; cannot authorize |
| Model output (LLM / Jev) | Untrusted candidate | May propose intent, slots, and plans; cannot execute |
| Agent service | Constrained orchestrator | Decomposes, validates, and calls registered tools only |
| ToolGateway | Type-checked boundary | Validates tool input/output; injects trusted execution context |
| Banking Core | Authoritative | Identity, ownership, policy, approval, MFA, authorization, ledger |
| PostgreSQL | System of record | Enforces constraints, uniqueness, row locks, append-only ledger |

The browser never receives the Core or Agent service token. The Node proxy removes the browser `Authorization` header and injects the server-side token. The Agent calls Core only through typed HTTP tools and never writes the financial ORM directly.

## 3. Permission-tier implementation

### 3.1 Deterministic policy authority

- `PolicyEngine.evaluate` is the sole source of the risk tier. The model and the UI cannot set it.
- The UI displays the tier returned by Core and uses the same Shield component for every sensitive action.
- Unknown actions, and any action without an explicit policy, are **DENIED**.
- A risk approval is not a payment. The lifecycle is: **parameter confirmation → risk approval → one-time authorization → Core commit**.
- Approval is bound to the actor, operation, action, payload hash, and expiry. The authorization grant is consumed once.
- At commit time, Core rechecks ownership, operation state, approval status, grant payload hash, expiry, and the current risk tier.

### 3.2 Tier matrix

| Operation | Tier | Enforcement | Status |
|---|---|---|---|
| Accounts, balances, transactions, expenses, budgets, subscriptions, cards, wealth products and holdings, beneficiaries | Green | Authenticated read plus ownership checks in Core | Implemented |
| Transfer, cumulative daily outgoing ≤ CNY 1,000 | Yellow | Explicit user confirmation, then one-time grant | Implemented |
| Transfer, cumulative daily outgoing > CNY 1,000 | Red | Simulated six-digit MFA, then one-time grant | Implemented |
| Card freeze, unfreeze, spending-limit change | Yellow | Explicit confirmation, then one-time grant | Implemented |
| Card loss report | Red | Simulated MFA, then one-time grant | Implemented |
| Subscription cancellation | Yellow | Explicit confirmation, then one-time grant | Implemented |
| Savings-pot contribution ≤ CNY 1,000 | Yellow | Explicit confirmation, then one-time grant | Implemented |
| Savings-pot contribution > CNY 1,000 | Red | Simulated MFA, then one-time grant | Implemented |
| Wealth subscription and redemption | Red | Simulated MFA, then one-time grant | Implemented |
| Virtual-card application | Yellow in policy | No end-to-end endpoint or UI flow | Not implemented |
| Password change | Red in policy | No end-to-end endpoint or UI flow | Not implemented |
| Any other action | — | Fail closed | Implemented (`DENIED`) |

**Threshold semantics.** The daily transfer limit uses the `Asia/Shanghai` business day. It includes live `PENDING_AUTHORIZATION` and `AUTHORIZED` drafts plus `PROCESSING` and `COMPLETED` transfers. Expired, cancelled, and failed drafts do not reserve the limit. A cumulative amount of exactly CNY 1,000 is Yellow; anything above it is Red. The cumulative check is repeated when the transfer is committed, so a Yellow approval cannot be used after the daily total crosses the Red threshold.

### 3.3 Approval and MFA controls

| Control | Implementation |
|---|---|
| Approval lifetime | At most 10 minutes, or the draft expiry if earlier |
| Grant | Single-use, payload-hash bound, operation bound, actor bound |
| MFA challenge | Six digits, five-minute validity, three attempts, then 15-minute actor lock |
| MFA storage | Salted PBKDF2-HMAC-SHA256 hash; the code is never stored in clear text |
| Replay resistance | Consumed grant and confirmed approval cannot be reused |
| Tamper resistance | Changing amount, account, recipient, or operation invalidates the old grant |
| Model isolation | MFA codes and authorization references never enter the model context |

### 3.4 Scenario coverage

| Challenge scenario | Coverage | Security-relevant gap |
|---|---|---|
| Smart transfers | Partial | Name/nickname transfers, AA split calculation, and recipient ranking are implemented. Phone-number, note-based, scheduled, and multi-payee collection transfers are absent. |
| Bill analysis | Partial | Category analysis, monthly summary, and expense summary are implemented. Annual reporting is absent; unusual-spending logic is not exposed as a first-class control. |
| Wealth operations | Implemented | Risk assessment, recommendation, comparison, subscription, redemption, and suitability checks are implemented. |
| Card management | Partial | Limit change, freeze/unfreeze, and loss reporting are implemented. Card application is policy-only; no application workflow exists. |
| Subscriptions and direct debit | Implemented | Recurring detection, renewal reminders, and confirmed cancellation are implemented. |
| Cross-scenario orchestration | Partial | Up to five dependent task items and verified-balance percentage transfers are supported. Birthday detection, merchant ordering, and chat-driven savings execution are not implemented. |

## 4. Security mechanisms

### 4.1 Hallucination and fabricated results

**Controls.** Model output is constrained by Pydantic contracts and allowed-field sets. Task decomposition requires an exact quote from the current message. `CapabilityBroker` limits the tools available for each intent. `PlanVerifier` rejects unknown tools, cycles, over-deep DAGs, missing provenance, inferred financial arguments, and schema violations. `ToolGateway` validates both input and output. `SafeResponseGenerator` builds prose only from verified tool results and never describes a pending draft as completed. Core remains the only source of financial truth.

**Residual risk.** The system can misunderstand a request and ask the wrong question, but it cannot convert that misunderstanding into an unauthorized or fabricated financial success. The model's semantic accuracy is probabilistic; Core's authority is deterministic.

### 4.2 Prompt injection

**Controls.** Input contracts reject passwords, OTP/MFA codes, CVV values, and full card numbers. The rule router detects explicit instruction-override markers and fails closed. The task decomposer combines Jev injection probability with explicit bypass markers. The frontend performs an independent injection check. Model-proposed trusted fields are rejected. The Agent can call only the tools allowed for the current intent. Even a successful injection cannot issue a Core authorization.

**Residual risk.** Regex and classifier signals do not cover every paraphrase, encoding, or multi-turn injection. The security claim is therefore **containment**, not detection completeness: an injected model can still waste a turn or produce a bad plan, but it cannot bypass Core approval.

### 4.3 Decision and execution logging

**Controls.** Every request carries `X-Trace-Id`. Core writes audit events for approvals, transfers, savings contributions, card operations, wealth orders, subscription cancellation, and rejected requests. The Agent persists tasks and monotonic events. LangGraph checkpoints preserve resumable execution state. ToolGateway records the actor, trace, tool name, result status, and error code.

**Gaps.** The default ToolGateway sink is process logging, not a durable audit store. There is no centralized SIEM, tamper-evident log chain, retention schedule, or privileged audit review console. Failure auditing in Core attributes requests to the configured development user, which is unsuitable for production. These are known production gaps, not claims of complete decision provenance.

### 4.4 Safety lock and suspicious behaviour

**Implemented.** Three failed MFA attempts lock the actor for 15 minutes. MFA challenges are time-limited and single-use. The daily transfer limit prevents unbounded same-day transfer escalation.

**Not implemented.** There is no global fraud engine, velocity check, device fingerprint, geo-anomaly rule, or automatic account freeze based on suspicious behaviour. `safety_locks.failure_count` is not used as an escalating global threshold. The daily limit is a financial control, not a fraud-detection system.

### 4.5 Sandbox

The Agent does not execute model-generated code. It emits structured intent, slots, and a verified `TaskPlan`; execution is limited to registered typed tools. There is no `eval`, dynamic import of model output, or arbitrary shell execution. In this architecture, the code-execution sandbox requirement is addressed by **eliminating code execution**, not by providing a sandbox.

If future work introduces model-generated code or arbitrary scripts, a dedicated sandbox with resource limits, network isolation, syscall filtering, and monitored egress must be added. Uploaded receipt images and audio are size-, MIME-, and signature-checked, but are not malware-scanned.

### 4.6 Financial integrity

| Control | Implementation |
|---|---|
| Money arithmetic | `Decimal` in Python and `NUMERIC(18,2)` in PostgreSQL; no binary floating point |
| Idempotency | Unique keys for transfers, wealth orders, savings pots, contributions, and expenses |
| Concurrency | Row locks on drafts, accounts, approvals, and holdings; deterministic ordering |
| Double-entry ledger | Every transfer posts balanced debit and credit entries; balance check before commit |
| Ledger immutability | PostgreSQL trigger rejects updates and deletes of posted ledger entries |
| Ownership | Core rechecks account, card, pot, order, and beneficiary ownership |
| State integrity | Explicit transfer, approval, and order state transitions; replay-safe terminal states |

**Residual risk.** Account balances are a stored projection updated in the same transaction as the ledger. There is no periodic ledger-to-balance reconciliation job, so independent drift detection is absent. A grant is consumed before the final balance check, so a failed commit can require a new approval. A crash between `PROCESSING` and `COMPLETED` has no dedicated recovery job.

### 4.7 Identity, transport, and secrets

**Implemented.** `.env` is untracked; secrets are `SecretStr`; the browser never holds service tokens; the Node proxy enforces an origin allowlist and injects tokens; CSP, `nosniff`, `no-referrer`, and `Cache-Control: no-store` are set; authorization references are memory-only and masked in the frontend API log.

**Simulation or gap.** Identity is a development stub bound to one configured user and a static service token. There is no user login, OAuth/OIDC, RBAC, token rotation, mTLS, or TLS between Agent and Core. Non-development mode fails closed with `401`. There is no application-level rate limiting or WAF. These controls are mandatory before any non-local deployment.

### 4.8 Privacy and data minimization

**Controls.** The input guard rejects authentication secrets. The optional Privacy Broker replaces emails, phone numbers, UUIDs, card-like numbers, account-like numbers, and configured names before model egress. The expense-labeling worker sends only an eligible merchant description with no digits, identifiers, or replacements. Local receipt OCR is the default; backend vision and speech are opt-in. The Agent sends only the minimum context required for the task.

**Residual risk.** Privacy Broker coverage is identifier-only and best-effort. Amounts, merchants, dates, and free-text names may still reach an external provider when LLM, Jev, or multimedia features are enabled. Vendor data-processing terms, regional storage, and deletion guarantees are deployment responsibilities, not properties of this repository.

## 5. Known-risk register

Severity reflects residual risk in a production deployment. The competition prototype operates with synthetic data.

| ID | Risk | Impact | Severity | Current mitigation | Required action |
|---|---|---|---|---|---|
| R-01 | Development identity and no RBAC | Any user maps to one configured actor; cross-user isolation depends on that stub | Critical | Static service token, development-only guard, Core ownership checks | Add OIDC/SSO, user sessions, roles, and tenant isolation |
| R-02 | No TLS/mTLS and static service tokens | Credential theft or traffic interception on a shared network | High | Local HTTP boundary, proxy token injection, `.env` untracked | TLS/mTLS, secret manager, rotation, network policy |
| R-03 | No API rate limiting or anti-automation | Brute force, cost exhaustion, denial of service | High | Request deadline; provider retries; MFA attempt lock | Gateway rate limits, quotas, bot detection, alerting |
| R-04 | Prompt injection remains possible in variants | Model manipulation, wasted turns, bad plans | High | Layered filters, evidence checks, capability narrowing, Core authority | Red-team corpus, classifier evaluation, regression gate |
| R-05 | No global fraud or velocity engine | Repeated suspicious operations below the daily threshold | High | Daily cumulative limit; MFA lock | Fraud rules, device/behaviour analytics, review queue |
| R-06 | Audit is not centralized or tamper-evident | Incomplete investigation and retention | High | Trace IDs, Core audit events, Agent events, checkpoints | Append-only audit store, SIEM, retention, access control |
| R-07 | Balance is a projection without reconciliation | Undetected drift after a future defect or manual change | High | Same-transaction update, ledger balance check, DB constraints | Scheduled reconciliation, alert on mismatch, repair runbook |
| R-08 | Grant consumed before final funds check | A failed commit burns the approval | Medium | Re-approval required; no funds move | Consume grant only after all preconditions pass |
| R-09 | Crash window in `PROCESSING` → `COMPLETED` | Transfer can remain stuck | Medium | Transaction rollback; status query | Recovery job, idempotent repair, operational alert |
| R-10 | Unknown-outcome reconciliation is incomplete | Some mutations require manual reconciliation | Medium | Transfer, wealth, and card status queries | Add reconciliation for savings and cancellation paths |
| R-11 | No code sandbox | Future model-generated code would be unsafe | Medium | No model code execution today | Add sandbox only if code execution is introduced |
| R-12 | Privacy Broker is identifiers-only | Amounts, merchants, dates, and names may leave | High | Redaction and eligibility policy | Data-classification policy, vendor DPA, regional controls |
| R-13 | External LLM/Jev/OCR governance | Third-party data retention and cross-border transfer | High | Opt-in features, minimal payloads | Vendor assessment, contractual controls, audit logs |
| R-14 | MFA is simulated | Not a real second factor | Medium | PBKDF2, expiry, attempt limit, lockout | SMS/TOTP/passkey integration for production |
| R-15 | Reads are not uniformly gated by `PolicyEngine` | Inconsistent future policy coverage | Medium | Authentication and ownership checks | Central read-policy middleware or explicit review |
| R-16 | No SCA/SBOM or vulnerability gate | Supply-chain exposure | Medium | Pinned dependencies, lock files | SCA, SBOM, signed builds, patch SLA |
| R-17 | Backup, DR, and DB privilege separation absent | Data loss or over-privileged compromise | High | Transactions, constraints, migration control | Backups, restore drills, least-privilege DB roles |
| R-18 | Product coverage gaps | Scheduled transfers, card application, annual reports, cross-scenario ordering | Medium | Explicit deferral and clarification | Roadmap with security review per new flow |

## 6. Verification and evidence

Run against the target revision:

```bash
python -m pytest
python -m ruff check .
python -m mypy

cd frontend/aegis-pwa
npm run typecheck
npm test
npm run build
```

PostgreSQL-specific checks require `DATABASE_TEST_URL`; without it, those tests are skipped. The security-relevant suites include:

- `tests/test_phase3_security.py` — Green read, cumulative threshold, fail-closed unknown action, salted MFA hash.
- `tests/test_transfer_daily_limit.py` — limit reservation, expiration, cancellation, cross-user rejection.
- `tests/test_savings_security.py` — ledger-backed contribution, idempotency, MFA, payload binding.
- `tests/test_postgres_integration.py` — immutable ledger, payload tampering, MFA lockout, duplicate resume, concurrent overspend.
- `tests/test_task1027_runtime.py` — verified plan execution, unknown-outcome reconciliation, confirmation-field rejection.
- `tests/test_agent_bundles.py` — dependent task items, per-item clarification, approval resume.
- `frontend/aegis-pwa/tests/` — money arithmetic, proxy token injection, path traversal, origin allowlist.

Passing tests demonstrate specified behaviour; they do not constitute a penetration test or a production security certification.