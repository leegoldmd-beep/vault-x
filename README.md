# Vault-X — AI Business Operations Platform (code showcase)

Vault-X is a full-stack **AI operations platform** I designed and built for a real field-services business. It runs a fleet of autonomous and assistive agents that find and qualify leads, estimate jobs from a photo, scan public records and government-contract portals, re-engage cold prospects, and learn from outcomes — all behind a passcode-protected progressive web app.

> **This repository is a curated, de-identified _code showcase_ of a private production app** — not the full application and not runnable standalone. It contains a representative slice of the backend engineering (the AI / agent logic). The frontend, infrastructure, credentials, business identity, and proprietary targeting data are intentionally excluded. Built with the [Emergent](https://emergent.sh) AI app-builder using Claude (Anthropic) as the reasoning engine; I directed the architecture, the agent design, and the QA.

## The system (full app)
- **Stack:** React + Tailwind/shadcn frontend · FastAPI + MongoDB backend (~10k+ LOC) · APScheduler cron · passcode auth · per-route rate limiting.
- **~28 backend modules · ~70 API routes · ~26 services · 22 test files.**

### Agent fleet
| Agent / engine | What it does |
|---|---|
| **In-app AI assistant** | A chat assistant with live database awareness that **executes actions** (run a scan, generate leads, pull stats) and surfaces proactive recommendations. |
| **Vision quote engine** | A 3-pass **photo → classification → price** estimator: snap a photo of a job and get an instant price range, condition, and hours. |
| **Nightly learning loop** | A persistent learning service (`services/zeno_learning.py`) that analyzes lead sources, conversion rates, and outcomes nightly and feeds insights back to the other agents. |
| **Maintenance agent** | A self-learning / self-healing agent (`maintenance_agent.py`) that periodically optimizes lead discovery and follow-through and logs every corrective action. |
| **Workflow engine** | Orchestrates multi-step jobs across the agents (`services/workflow_engine.py`). |
| **Feedback loop** | Closes the loop from realized outcomes back into agent behavior (`services/feedback_loop.py`). |
| **Lead quality filter** | Scores and qualifies inbound / discovered leads (`lead_quality_filter.py`). |
| **Email guard** | A centralized send-cap + kill switch (`email_guard.py`) every outbound path must pass — a responsible-automation guardrail. |
| **QC gate** | A quality gate (`qc_gate.py`) that screens generated content before it sends. |

## What's in this repo (curated backend slice)
```
backend/
├── quote_engine.py              # 3-pass vision → classification → pricing engine
├── maintenance_agent.py         # self-learning / self-healing optimization agent
├── lead_quality_filter.py       # lead scoring / qualification
├── qc_gate.py                   # pre-send quality gate
├── email_guard.py               # send-cap + kill-switch guardrail
├── models.py                    # core data models
└── services/
    ├── zeno_learning.py         # nightly persistent learning loop
    ├── workflow_engine.py       # multi-step task orchestration
    └── feedback_loop.py         # outcome → behavior feedback loop
```

## What's intentionally excluded
- All secrets — every API key, DB URI, and token is read from environment variables; no `.env` is included.
- The React frontend, infrastructure, and deployment config.
- Proprietary rate tables (`pricing_config.py`), the business's identity, and its specific lead-targeting / outreach logic.
- Any customer data or personal information.

## Tech
Python · FastAPI · MongoDB · APScheduler · Claude (via Emergent LLM key) · web scraping (trafilatura / BeautifulSoup / whois) · vision-based estimation.

---
**More of my work:** [honest-backtester](https://github.com/leegoldmd-beep/honest-backtester) · [ai-content-pipeline](https://github.com/leegoldmd-beep/ai-content-pipeline) · [all repos](https://github.com/leegoldmd-beep)

_Part of my portfolio. The full app is private. Questions welcome._
