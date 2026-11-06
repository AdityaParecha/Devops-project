# DevOps / AIOps Monitoring

Monitoring stack plus an AI agent that detects incidents and (optionally) remediates them on VMs.

| Folder | What it is | Status |
|---|---|---|
| `devops-demo-shop/` | Demo app (Docker) used as a monitoring target | Stable |
| `devops-monitoring/` | Zabbix + Loki + Grafana stack, dashboards, FastAPI control center, and its own `app/agent/` (planner/executor/observer/verifier/reasoner) | Stack works; agent does not |
| `ai_devops_monitoring_refactor/` | Modular agent: orchestrator, classifier, rules, Ollama reasoner, SSH remediation | Agent works |
| `experiments/` | Early single-file prototypes (`monitor.py`, `agent_test.py`, `subsecond_llm.py`, `project_app.py`) | Reference only |
| `docs/` | Workflow deck and architecture diagrams | |

## Setup
Each project has its own `.env.example`. Copy it to `.env` and fill in values. `.env` files are git-ignored; never commit them.

## Roadmap
- Fix the agent in `devops-monitoring/` (or port the working agent from `ai_devops_monitoring_refactor/`).
- Pick one canonical Grafana dashboard from the three JSON variants.
