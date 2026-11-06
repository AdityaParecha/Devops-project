# AI DevOps Control Center — Modular Refactor

Extract this bundle into the existing project root. It preserves the uploaded FastAPI control-center UI and adds a layered monitoring/incident pipeline:
1. Deterministic rules over Zabbix metrics/problems and Loki error logs.
2. Laya classification through the local Ollama HTTP API.
3. Ministral root-cause analysis and action recommendation through Ollama.
4. A strict action allowlist and policy gate.
5. Backend restart and health verification.

## Important safety behavior
`AUTOMATIC_REMEDIATION=true` enables automation, but only the hard-coded `restart_backend` action can run. The action is restricted to backend availability incidents, requires the configured allowlist flag, and is followed by health verification. The LLM cannot supply shell commands. Unknown incidents, low classifier confidence, invalid model output, or source failures fail closed.

## Prerequisites
- Python 3.10+
- Existing Zabbix web/API reachable at `http://localhost:8085`
- Existing Loki reachable at `http://localhost:3100`
- Ollama reachable at `http://localhost:11434`
- Existing SSH port forwards: Frontend 2223, Backend 2222, Database 2224
- Backend demo app reachable at `http://localhost:8000`
- Zabbix hosts named Frontend, Backend and Database, with Linux agent templates attached.
- Alloy forwarding the existing VM logs to Loki.

## Setup (PowerShell)
```powershell
cd C:\coding\Devops\ai-devops-refactor
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```
Fill `ZABBIX_PASSWORD` and `SSH_PASSWORD`. Use SSH key authentication if possible. Never commit `.env`.

Install/pull the selected Ollama models. Verify actual tags first:
```powershell
ollama list
ollama pull laya
ollama pull ministral-3:3b
```
The official Ollama library currently lists `ministral-3:3b`, `ministral-3:8b`, and `ministral-3:14b`. For the current host, start with `ministral-3:3b`; set `MINISTRAL_MODEL` to the exact tag shown by `ollama list`.

Run:
```powershell
uvicorn app.main:app --host 0.0.0.0 --port 9000
```
Open `http://localhost:9000`.

## First-run validation
- `GET /api/health` checks the controller process.
- `GET /api/diagnostics` shows configured endpoints/model tags (not passwords).
- `GET /api/status` shows source health, metrics, incidents, model stages and actions.
- Run tests: `pytest -q`.

## Integration notes
- Zabbix 7 JSON-RPC login uses `user.login`; this client retrieves monitored host items and active problems.
- Loki uses `/ready` and `/loki/api/v1/query_range`.
- The current rules are initial baselines; thresholds should be tuned from observed VM behavior.
- Laya uses Ollama's typed decision endpoint `/v1/systemone` (not `/api/generate`): it returns category choices and confidence/probability data. Ollama's Laya page documents the typed decision API and states Ollama 0.40.0+ is required. Ministral uses Ollama's `/api/generate` JSON mode for root-cause analysis.
- Zabbix item names vary by template version. Review `/api/status` `missing` arrays and tune patterns in `app/engine/rules.py`.
- The existing demo backend exposes Prometheus client metrics. Prometheus is not used by this monitoring architecture; remove its `/metrics` instrumentation in a separate backend cleanup after confirming nothing depends on it.
