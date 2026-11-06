
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import settings
from app.clients.zabbix import ZabbixClient, ZabbixError
from app.clients.loki import LokiClient, LokiError
from app.engine.incident_engine import IncidentEngine
from app.agent import DevOpsAgent
from app.agent.reasoner import ReasonerError


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(
    title="AI DevOps Control Center",
    description="Central monitoring with Zabbix, Loki and Grafana",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONTEND_DIR.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(FRONTEND_DIR)),
        name="static",
    )

zabbix = ZabbixClient(
    url=settings.zabbix_url,
    username=settings.zabbix_user,
    password=settings.zabbix_password,
    timeout=settings.request_timeout,
)

loki = LokiClient(
    base_url=settings.loki_url,
    timeout=settings.request_timeout,
)

incident_engine = IncidentEngine()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def find_metric(items, include_patterns, exclude_patterns=None):
    exclude_patterns = exclude_patterns or []

    for item in items:
        name = item.get("name", "")
        key = item.get("key_", "")
        combined = f"{name} {key}".lower()

        if any(
            re.search(pattern, combined, re.IGNORECASE)
            for pattern in exclude_patterns
        ):
            continue

        if any(
            re.search(pattern, combined, re.IGNORECASE)
            for pattern in include_patterns
        ):
            try:
                value = float(item.get("lastvalue", ""))
            except (TypeError, ValueError):
                continue

            return {
                "value": value,
                "unit": item.get("units", ""),
                "item_name": name,
                "lastclock": item.get("lastclock"),
            }

    return None


def normalize_host(host_name, host_data):
    host = host_data["host"]
    items = host_data.get("items", [])

    cpu_idle = find_metric(
        items,
        [r"cpu.*idle", r"system\.cpu\.util.*idle"],
    )

    cpu_utilization = find_metric(
        items,
        [
            r"^cpu utilization$",
            r"total cpu utilization",
            r"system\.cpu\.util\[.*total",
        ],
        [
            r"guest", r"nice", r"idle", r"interrupt",
            r"iowait", r"user time", r"system time",
        ],
    )

    # Prefer idle-derived total CPU utilization when available.
    if cpu_idle is not None:
        idle = max(0.0, min(100.0, cpu_idle["value"]))
        cpu_utilization = {
            "value": round(100.0 - idle, 2),
            "unit": "%",
            "item_name": "Derived from CPU idle time",
            "lastclock": cpu_idle["lastclock"],
        }

    memory_utilization = find_metric(
        items, [r"memory utilization"]
    )

    memory_available = find_metric(
        items, [r"available memory", r"memory available"]
    )

    load_5m = find_metric(
        items,
        [
            r"avg5\b",
            r"avg5\]",
            r"5 minute load",
            r"load average.*\b5m\b",
        ],
        [r"15m", r"avg15", r"15 minute"],
    )

    load_15m = find_metric(
        items,
        [
            r"avg15\b",
            r"avg15\]",
            r"15 minute load",
            r"load average.*\b15m\b",
        ],
    )

    disk_utilization = find_metric(
        items, [r"disk utilization"]
    )

    metrics = {
        "cpu_utilization": cpu_utilization,
        "cpu_idle": cpu_idle,
        "memory_utilization": memory_utilization,
        "memory_available": memory_available,
        "load_5m": load_5m,
        "load_15m": load_15m,
        "disk_utilization": disk_utilization,
    }

    timestamps = []

    for item in items:
        clock = item.get("lastclock")
        if str(clock).isdigit() and int(clock) > 0:
            timestamps.append(int(clock))

    latest_timestamp = max(timestamps) if timestamps else None
    age_seconds = None

    if latest_timestamp:
        age_seconds = max(
            0,
            int(datetime.now(timezone.utc).timestamp()) - latest_timestamp,
        )

    interfaces = host.get("interfaces", [])

    agent_availability = [
        interface.get("available")
        for interface in interfaces
        if interface.get("type") == "1"
    ]

    if str(host.get("status")) != "0":
        status = "DISABLED"
    elif latest_timestamp and age_seconds <= 600:
        status = "HEALTHY"
    elif any(value == "2" for value in agent_availability):
        status = "DOWN"
    else:
        status = "UNKNOWN"

    primary_ip = next(
        (
            interface.get("ip")
            for interface in interfaces
            if interface.get("main") == "1"
        ),
        None,
    )

    return {
        "name": host_name,
        "hostid": host.get("hostid"),
        "technical_name": host.get("host"),
        "ip": primary_ip,
        "status": status,
        "agent_available": agent_availability,
        "item_count": len(items),
        "last_data_timestamp": latest_timestamp,
        "data_age_seconds": age_seconds,
        "metrics": metrics,
    }


def collect_overview():
    host_names = [
        server["zabbix_host"]
        for server in settings.servers.values()
    ]

    try:
        snapshot = zabbix.snapshot(host_names)
        problems = zabbix.problems(limit=30)
    except ZabbixError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Zabbix error: {exc}",
        )

    servers = {}

    for key, server in settings.servers.items():
        host_data = next(
            (
                value
                for name, value in snapshot.items()
                if name.lower() == server["zabbix_host"].lower()
            ),
            None,
        )

        if host_data:
            servers[key] = normalize_host(
                server["name"],
                host_data,
            )
        else:
            servers[key] = {
                "name": server["name"],
                "hostid": None,
                "ip": None,
                "status": "NOT_FOUND",
                "item_count": 0,
                "data_age_seconds": None,
                "metrics": {},
            }

    return {"servers": servers, "problems": problems}


def check_zabbix():
    try:
        return {
            "status": "CONNECTED",
            **zabbix.test_connection(),
        }
    except ZabbixError as exc:
        return {
            "status": "DISCONNECTED",
            "connected": False,
            "error": str(exc),
        }


def check_loki():
    try:
        return {
            "status": "CONNECTED",
            **loki.test_connection(),
        }
    except LokiError as exc:
        return {
            "status": "DISCONNECTED",
            "connected": False,
            "error": str(exc),
        }


def grafana_dashboard_url():
    if settings.grafana_dashboard_uid:
        return (
            f"{settings.grafana_url}/d/"
            f"{settings.grafana_dashboard_uid}"
        )
    return settings.grafana_url


def build_incident_report():
    data = collect_overview()

    try:
        logs_data = loki.recent_logs(
            minutes=30,
            limit=500,
        )
    except LokiError:
        logs_data = []

    return incident_engine.analyze(
        servers=data["servers"],
        problems=data["problems"],
        logs=logs_data,
    )


@app.get("/")
def home():
    index_file = FRONTEND_DIR / "index.html"

    if index_file.exists():
        return FileResponse(str(index_file))

    return {
        "application": settings.app_name,
        "status": "RUNNING",
        "documentation": "/docs",
    }


@app.get("/api/health")
def health():
    return {
        "status": "RUNNING",
        "application": settings.app_name,
        "timestamp": now_iso(),
    }


@app.get("/api/integrations")
def integrations():
    return {
        "zabbix": check_zabbix(),
        "loki": check_loki(),
        "grafana": {
            "status": "CONFIGURED",
            "url": settings.grafana_url,
            "dashboard_url": grafana_dashboard_url(),
        },
        "timestamp": now_iso(),
    }


@app.get("/api/overview")
@app.get("/api/status")
def overview():
    data = collect_overview()

    try:
        loki_status = "CONNECTED" if loki.ready() else "DISCONNECTED"
    except LokiError:
        loki_status = "DISCONNECTED"

    return {
        "status": "RUNNING",
        "timestamp": now_iso(),
        "sources": {
            "zabbix": "CONNECTED",
            "loki": loki_status,
        },
        "servers": data["servers"],
        "problems": data["problems"],
        "grafana_url": settings.grafana_url,
        "grafana_dashboard_url": grafana_dashboard_url(),
    }


@app.get("/api/hosts")
def hosts():
    return collect_overview()["servers"]


@app.get("/api/problems")
def problems(limit: int = Query(default=30, ge=1, le=100)):
    try:
        result = zabbix.problems(limit=limit)
        return {"count": len(result), "problems": result}
    except ZabbixError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/logs")
def logs(
    minutes: int = Query(default=30, ge=1, le=1440),
    limit: int = Query(default=100, ge=1, le=1000),
    host: str | None = None,
    errors_only: bool = False,
):
    try:
        if errors_only:
            results = loki.recent_errors(
                minutes=minutes,
                limit=limit,
            )
            if host:
                results = [
                    entry for entry in results
                    if entry.get("host", "").lower() == host.lower()
                ]
        else:
            results = loki.recent_logs(
                minutes=minutes,
                limit=limit,
                host=host,
            )

        return {
            "count": len(results),
            "minutes": minutes,
            "host": host,
            "errors_only": errors_only,
            "logs": results,
        }
    except LokiError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/hosts/{host_name}/logs")
def host_logs(
    host_name: str,
    minutes: int = Query(default=30, ge=1, le=1440),
    limit: int = Query(default=100, ge=1, le=1000),
):
    allowed_hosts = {
        server["name"].lower()
        for server in settings.servers.values()
    }

    if host_name.lower() not in allowed_hosts:
        raise HTTPException(status_code=404, detail="Unknown monitoring host.")

    try:
        results = loki.recent_logs(
            minutes=minutes,
            limit=limit,
            host=host_name,
        )
        return {
            "host": host_name,
            "count": len(results),
            "logs": results,
        }
    except LokiError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/grafana")
def grafana():
    return {
        "status": "CONFIGURED",
        "grafana_url": settings.grafana_url,
        "dashboard_url": grafana_dashboard_url(),
    }


@app.get("/api/incidents")
def get_incidents():
    return build_incident_report()


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str):
    report = build_incident_report()

    for incident in report["incidents"]:
        if incident["id"] == incident_id:
            return incident

    raise HTTPException(
        status_code=404,
        detail="Incident not found.",
    )


# ---------------------------------------------------------------------------
# AI DevOps Agent API
# ---------------------------------------------------------------------------

# The agent reuses the existing Zabbix, Loki and overview integrations.
# Its executor has a strict action allowlist and requires explicit approval.
devops_agent = DevOpsAgent(
    zabbix_client=zabbix,
    loki_client=loki,
    overview_collector=collect_overview,
)


class AgentApprovalRequest(BaseModel):
    approved: bool


@app.get("/api/agent/status")
def agent_status():
    return {
        "status": "READY",
        "model": devops_agent.reasoner.model,
        "workflow": [
            "OBSERVE",
            "REASON",
            "PLAN",
            "HUMAN_APPROVAL",
            "EXECUTE",
            "VERIFY",
        ],
        "automatic_remediation": False,
        "approval_mode": "HUMAN_APPROVAL_REQUIRED",
        "demo_fault_injection": "BACKEND_CONTAINER_STOP",
        "allowed_actions": ["restart_nginx", "restart_backend", "restart_database"],
    }


@app.post("/api/agent/investigate")
def agent_investigate():
    try:
        return devops_agent.investigate()
    except ReasonerError as exc:
        raise HTTPException(status_code=502, detail=f"AI reasoning failed: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent investigation failed: {exc}")


@app.get("/api/agent/plans/{plan_id}")
def agent_get_plan(plan_id: str):
    record = devops_agent.get_plan(plan_id)
    if not record:
        raise HTTPException(status_code=404, detail="Agent plan not found.")

    # Do not expose the full collected SSH/log evidence through this endpoint.
    return {
        "plan": record.get("plan"),
        "diagnosis": record.get("diagnosis"),
        "execution": record.get("execution"),
        "verification": record.get("verification"),
    }


@app.post("/api/agent/plans/{plan_id}/approve")
def agent_approve_plan(plan_id: str, request: AgentApprovalRequest):
    if request.approved is not True:
        raise HTTPException(
            status_code=400,
            detail="Set approved=true to explicitly authorize this plan.",
        )

    try:
        return devops_agent.execute_approved_plan(
            plan_id=plan_id,
            approved=True,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent plan not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Plan execution failed: {exc}")


class DemoFaultRequest(BaseModel):
    confirm: bool


@app.post("/api/agent/demo/fault")
def agent_demo_fault(request: DemoFaultRequest):
    """Stop only the demo backend container, then immediately investigate it."""
    if request.confirm is not True:
        raise HTTPException(status_code=400, detail="Explicit demo fault confirmation is required.")
    try:
        injection = devops_agent.executor.inject_backend_fault(confirmed=True)
        if not injection.get("success"):
            raise HTTPException(status_code=502, detail=injection.get("error") or injection.get("stderr") or "Fault injection failed.")
        investigation = devops_agent.investigate()
        return {"fault_injection": injection, "investigation": investigation}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Demo fault workflow failed: {exc}")
