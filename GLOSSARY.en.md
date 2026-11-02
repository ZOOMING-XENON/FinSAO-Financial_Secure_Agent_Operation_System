[中文](GLOSSARY.md) | English

# Aegis Glossary

This page defines the core terms used by the repository. Code identifiers remain authoritative; the definitions below describe their product meaning.

| Term | Definition |
| --- | --- |
| **Aegis** | The complete simulated banking-agent product: PWA, Agent Service, Banking Core, and persistence layers. |
| **Agent Service** | The service responsible for language understanding, task decomposition, context, plan verification, and tool orchestration. It cannot directly mutate the financial ledger. |
| **Banking Core** | The authority for financial facts and business rules. It enforces identity and ownership, risk approval, grant consumption, business transactions, and double-entry bookkeeping. |
| **Task Bundle** | Up to five dependency-linked Bundle Items derived from one user request, plus their aggregate state. |
| **Bundle Item** | One independent intent inside a Task Bundle. It may need clarification, parameter confirmation, or risk approval; it may also complete, fail, or be deferred. |
| **Durable Task** | A persisted Agent execution containing its plan, result, events, and recovery state. A Bundle Item may reference one Durable Task. |
| **Parameter Confirmation** | The user reviews structured fields proposed by the model or system, such as account, recipient, amount, and currency. It is neither Risk Approval nor proof that funds moved. |
| **Risk Approval** | A Green, Yellow, or Red decision made by Banking Core from the exact operation and payload. Yellow requires explicit confirmation; Red also requires simulated MFA. |
| **Authorization Grant** | A short-lived, single-use, payload-bound reference issued by Banking Core after approval. It is not a model argument and should not appear in browser logs. |
| **Verified Fact** | Data returned by Core, explicitly provided by the user, or supplied by trusted context and type-checked. Model suggestions remain candidates with provenance until verified. |
| **Jev** | An optional external classification and plan-review service. High-confidence simple requests may take its fast path; complex or low-confidence requests go to the primary LLM. |
| **Privacy Broker** | An optional deterministic, best-effort redaction layer for model-bound text. It reduces exposure of common identifiers but is not complete anonymization. |

## Three distinct states

```text
Parameter Confirmation → Risk Approval → Grant consumption and business commit
```

- Parameter Confirmation means only that the user accepts the fields for review.
- Risk Approval means Core permits the bound payload to continue; the business transaction may still be uncommitted.
- A funds-moving action is successful only after Core returns a completed state.

