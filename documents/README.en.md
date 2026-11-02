[中文](README.md) | English

# Aegis Technical Documentation

This directory contains the canonical technical description of the current code. First read the root [project overview](../README.en.md) and [glossary](../GLOSSARY.en.md), then continue in this order.

| Document | Question answered | Primary audience |
| --- | --- | --- |
| [Architecture](Architecture.en.md) | How do PWA, Agent, Core, models, and the three persistence responsibilities connect? Where are the trust and deployment boundaries? | Architects, developers, judges |
| [Algorithms](Algorithm.en.md) | How are compound requests decomposed, confirmed, calculated, planned, executed, and recovered? | Agent and backend developers |
| [Security](Security.en.md) | Which inputs can models influence? Who authorizes financial actions? How are failures and unknown outcomes handled? | Security reviewers and backend developers |
| [Glossary](../GLOSSARY.en.md) | What are Task Bundles, Parameter Confirmation, Risk Approval, and Authorization Grants? | Everyone |

## Sources of truth

The documentation describes the system using this priority:

1. Pydantic/API contracts and database models;
2. Agent orchestration, the tool gateway, and Core business code;
3. automated tests;
4. example configuration and UI copy.

Model capabilities, external services, and test results are marked as optional, bounded, or dated snapshots. A configuration flag is not presented as an uptime guarantee.

## Current boundaries

- The online conversation path uses persistent Task Bundles; legacy single-turn and Durable Task endpoints remain available.
- Jev is wired into the online application, but participates only when enabled and supplied with an API key.
- Natural-language savings-pot items are currently deferred; the structured UI and Core APIs remain available.
- Compose currently starts PostgreSQL and Banking Core only; Agent and PWA are separate processes.
- This repository is a simulated financial prototype and does not implement every security or compliance control required by a real bank.

If documentation and implementation diverge, migrated Core financial state is the execution authority. Update the relevant documentation in the same change.

