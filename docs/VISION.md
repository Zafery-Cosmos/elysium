# Elysium Vision

Elysium is a source-available **AI Development Environment** (proprietary
license — see `LICENSE`; the code is viewable and runnable for personal
evaluation, not for reuse or redistribution).

It is not a chatbot. It is not only a code generator.

Elysium is a collaborative workspace where multiple specialized AI agents — project
manager, architect, frontend developer, backend developer, database engineer, DevOps,
security auditor, QA — work together to transform a human idea into functional software.

> A chatbot answers. An assistant codes. **A team builds.**

The user can start with a single sentence ("I want an app to book restaurants") and
Elysium progressively understands, asks adaptive questions, writes a specification,
plans, develops, tests and deploys the project — while the user keeps full control at
every step.

## Core principles

1. **User in control** — every important action is visible, explained, approvable and
   reversible. Deny by default.
2. **Simplicity first** — a beginner never sees frameworks, tokens or Docker unless
   they want to. An expert can open every panel.
3. **Multi-model** — Anthropic, OpenAI, Google, Mistral, DeepSeek, OpenRouter, and
   fully local models (Ollama, LM Studio, any OpenAI-compatible server). No vendor
   lock-in. Usable with zero external API key.
4. **Multi-agent** — a real team structure with roles, permissions, memory and debate,
   orchestrated by a Project Manager agent. Not one prompt doing everything.
5. **Privacy first** — can run 100% locally. No mandatory telemetry. Secrets never
   leave the machine without explicit consent.
6. **Extensible** — agents, model providers, tools, MCP servers and plugins are all
   pluggable. Elysium is a platform, not a product feature list.
7. **Open source, built to last** — documented architecture, contribution-friendly,
   professional engineering standards.

## What makes Elysium different

| | Chat assistants | AI code editors (Cursor…) | App builders (Lovable, Bolt…) | **Elysium** |
|---|---|---|---|---|
| Runs locally, open source | varies | no | no | **yes** |
| Multi-provider + local models | limited | limited | no | **yes** |
| Explicit team of role agents | no | no | hidden | **yes** |
| Requirements elicitation (adaptive questions → spec) | no | no | partial | **yes** |
| Permission system / human-in-the-loop | partial | partial | no | **yes, core** |
| Deploy to your own NAS/VPS | no | no | vendor cloud | **yes** |

## Long-term vision

A complete team of artificial intelligences, accessible from a single open source
application — for beginners, indie developers, startups and enterprises.
