import json
import threading
import time
from datetime import datetime
from getpass import getpass

import paramiko
import requests
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BACKEND_URL = "http://localhost:8000"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:latest"
SSH_USER = "aditya"
CHECK_INTERVAL = 3
AUTO_REMEDIATE = True

SERVERS = {
    "frontend": {"name": "Frontend", "host": "localhost", "port": 2223},
    "backend": {"name": "Backend", "host": "localhost", "port": 2222},
    "database": {"name": "Database", "host": "localhost", "port": 2224},
}

state = {
    "frontend": "UNKNOWN",
    "backend": "UNKNOWN",
    "database": "UNKNOWN",
    "servers": {
        key: {
            "status": "UNKNOWN",
            "cpu": None,
            "ram_used": None,
            "ram_total": None,
            "ram_percent": None,
            "disk_percent": None,
            "uptime": None,
            "last_check": None,
        }
        for key in SERVERS
    },
    "incident": None,
    "agent": "READY",
    "action": None,
    "verification": None,
    "last_check": None,
    "events": [],
}

ssh_password = None
state_lock = threading.Lock()
remediation_lock = threading.Lock()
monitor_running = True
remediation_running = False


def add_event(message, level="info"):
    event = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "message": message,
        "level": level,
    }
    with state_lock:
        state["events"].insert(0, event)
        state["events"] = state["events"][:40]


def ssh_command(server_key, command, timeout=10):
    if not ssh_password:
        raise RuntimeError("SSH password not configured")

    server = SERVERS[server_key]
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            hostname=server["host"],
            port=server["port"],
            username=SSH_USER,
            password=ssh_password,
            look_for_keys=False,
            allow_agent=False,
            timeout=10,
            banner_timeout=10,
            auth_timeout=10,
        )
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        output = stdout.read().decode(errors="ignore").strip()
        error = stderr.read().decode(errors="ignore").strip()
        exit_code = stdout.channel.recv_exit_status()

        if exit_code != 0:
            raise RuntimeError(error or output or f"exit {exit_code}")

        return output
    finally:
        client.close()


RESOURCE_COMMAND = r"""
echo "__CPU__"
top -bn1 | awk '/Cpu\(s\)/ {print 100 - $8; exit}'
echo "__RAM__"
free -m | awk '/^Mem:/ {print $3, $2}'
echo "__DISK__"
df -P / | awk 'NR==2 {gsub("%","",$5); print $5}'
echo "__UPTIME__"
uptime -p
""".strip()


def parse_resources(output):
    lines = [x.strip() for x in output.splitlines() if x.strip()]
    data = {
        "cpu": None,
        "ram_used": None,
        "ram_total": None,
        "ram_percent": None,
        "disk_percent": None,
        "uptime": None,
    }

    try:
        ci = lines.index("__CPU__")
        ri = lines.index("__RAM__")
        di = lines.index("__DISK__")
        ui = lines.index("__UPTIME__")

        data["cpu"] = round(float(lines[ci + 1]), 1)

        ram = lines[ri + 1].split()
        data["ram_used"] = int(ram[0])
        data["ram_total"] = int(ram[1])
        data["ram_percent"] = round(
            data["ram_used"] / data["ram_total"] * 100, 1
        ) if data["ram_total"] else None

        data["disk_percent"] = round(float(lines[di + 1]), 1)
        data["uptime"] = lines[ui + 1]
    except (ValueError, IndexError, TypeError):
        pass

    return data


def monitor_server(server_key):
    try:
        metrics = parse_resources(
            ssh_command(server_key, RESOURCE_COMMAND)
        )
        with state_lock:
            state["servers"][server_key].update(metrics)
            state["servers"][server_key]["status"] = "HEALTHY"
            state["servers"][server_key]["last_check"] = (
                datetime.now().strftime("%H:%M:%S")
            )
        return True
    except Exception:
        with state_lock:
            state["servers"][server_key]["status"] = "DOWN"
            state["servers"][server_key]["last_check"] = (
                datetime.now().strftime("%H:%M:%S")
            )
        return False


def check_backend():
    try:
        response = requests.get(f"{BACKEND_URL}/api/health", timeout=3)
        if response.status_code == 200:
            data = response.json()
            return True, data.get("database", "unknown")
        return False, "unknown"
    except Exception:
        return False, "unknown"


def inject_backend_failure():
    try:
        ssh_command("backend", "docker stop devops-demo-app")
        with state_lock:
            state["incident"] = "BackendDown"
        add_event("Fault injected: backend container stopped", "critical")
        return True, "Backend failure injected"
    except Exception as exc:
        add_event(f"Fault injection failed: {exc}", "critical")
        return False, str(exc)


def ask_mistral():
    with state_lock:
        backend = state["backend"]
        database = state["database"]

    prompt = f"""
You are an autonomous DevOps incident response agent.

Current state:
Backend: {backend}
Database: {database}
Incident: BackendDown

Choose exactly one:
restart_backend
no_action
escalate

Rules:
- If Backend is DOWN and Database is HEALTHY, choose restart_backend.
- Never invent shell commands.
- Return only valid JSON.

Format:
{{"action":"restart_backend","reason":"short explanation"}}
"""

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
        },
        timeout=60,
    )
    response.raise_for_status()

    decision = json.loads(response.json().get("response", ""))
    action = decision.get("action")
    reason = decision.get("reason", "")

    if action not in {"restart_backend", "no_action", "escalate"}:
        raise RuntimeError(f"Invalid AI action: {action}")

    return action, reason


def restart_backend():
    add_event("Executing approved remediation: restart_backend", "warning")
    try:
        ssh_command("backend", "docker restart devops-demo-app", timeout=15)
        add_event(
            "Backend restart command executed successfully",
            "success",
        )
        return True
    except Exception as exc:
        add_event(f"Backend restart failed: {exc}", "critical")
        return False


def verify_recovery():
    with state_lock:
        state["agent"] = "VERIFYING"

    add_event("Verifying backend recovery...", "info")

    for attempt in range(1, 8):
        time.sleep(2)
        healthy, database = check_backend()

        with state_lock:
            state["backend"] = "HEALTHY" if healthy else "DOWN"
            state["database"] = (
                "HEALTHY" if database == "healthy" else database.upper()
            )

        if healthy:
            with state_lock:
                state["verification"] = "PASSED"
                state["incident"] = None
                state["agent"] = "RECOVERED"

            add_event(
                f"Health verification PASSED (attempt {attempt})",
                "success",
            )
            add_event(
                "Backend recovered through AI remediation",
                "success",
            )
            return True

    with state_lock:
        state["verification"] = "FAILED"
        state["agent"] = "FAILED"

    add_event("Health verification FAILED", "critical")
    return False


def handle_incident():
    global remediation_running

    if not remediation_lock.acquire(blocking=False):
        return

    remediation_running = True

    try:
        with state_lock:
            state["agent"] = "ANALYZING"
            state["action"] = None
            state["verification"] = None

        add_event("Mistral analyzing incident", "info")

        try:
            action, reason = ask_mistral()
        except Exception as exc:
            with state_lock:
                state["agent"] = "FAILED"
            add_event(f"Mistral error: {exc}", "critical")
            return

        with state_lock:
            state["action"] = action

        add_event(f"AI decision: {action}", "info")

        if reason:
            add_event(f"AI reasoning: {reason}", "info")

        if action == "no_action":
            with state_lock:
                state["agent"] = "READY"
            add_event("AI decided no remediation is required", "warning")
            return

        if action == "escalate":
            with state_lock:
                state["agent"] = "ESCALATED"
            add_event(
                "Incident escalated for human intervention",
                "critical",
            )
            return

        with state_lock:
            state["agent"] = "EXECUTING"

        if restart_backend():
            verify_recovery()
        else:
            with state_lock:
                state["agent"] = "FAILED"

    finally:
        remediation_running = False
        remediation_lock.release()


def monitoring_loop():
    previous_backend = None
    add_event("AI DevOps monitoring started", "success")

    while monitor_running:
        try:
            for server_key in SERVERS:
                monitor_server(server_key)

            healthy, database = check_backend()
            current_backend = "HEALTHY" if healthy else "DOWN"
            database_status = (
                "HEALTHY"
                if database == "healthy"
                else database.upper()
            )

            with state_lock:
                state["backend"] = current_backend
                state["database"] = database_status
                state["frontend"] = state["servers"]["frontend"]["status"]
                state["last_check"] = datetime.now().strftime("%H:%M:%S")

            if previous_backend == "HEALTHY" and current_backend == "DOWN":
                with state_lock:
                    state["incident"] = "BackendDown"
                    state["agent"] = "DETECTED"

                add_event("Backend failure detected", "critical")

                if AUTO_REMEDIATE:
                    threading.Thread(
                        target=handle_incident,
                        daemon=True,
                    ).start()

            elif previous_backend == "DOWN" and current_backend == "HEALTHY":
                with state_lock:
                    state["incident"] = None

                if not remediation_running:
                    add_event("Backend recovered", "success")

            previous_backend = current_backend

        except Exception as exc:
            add_event(f"Monitoring error: {exc}", "critical")

        time.sleep(CHECK_INTERVAL)


app = FastAPI(title="AI DevOps Control Center")
app.mount(
    "/static",
    StaticFiles(directory="frontend"),
    name="static",
)


@app.get("/")
def dashboard():
    return FileResponse("frontend/index.html")


@app.get("/api/status")
def api_status():
    with state_lock:
        return json.loads(json.dumps(state))


@app.post("/api/fault")
def api_fault():
    success, message = inject_backend_failure()
    return (
        {"status": "success", "message": message}
        if success
        else {"status": "failed", "error": message}
    )


@app.post("/api/analyze")
def api_analyze():
    with state_lock:
        backend = state["backend"]
        incident = state["incident"]

    if backend != "DOWN":
        return {
            "status": "ignored",
            "message": "Backend is not currently DOWN",
        }

    if remediation_running:
        return {
            "status": "running",
            "message": "AI remediation already running",
        }

    if not incident:
        with state_lock:
            state["incident"] = "BackendDown"

    threading.Thread(
        target=handle_incident,
        daemon=True,
    ).start()

    return {
        "status": "started",
        "message": "AI remediation started",
    }


def startup():
    global ssh_password

    print("=" * 60)
    print("AI DEVOPS CONTROL CENTER")
    print("=" * 60)
    print("SSH targets:")
    for key, server in SERVERS.items():
        print(
            f"  {server['name']}: "
            f"{server['host']}:{server['port']}"
        )

    ssh_password = getpass("Enter SSH password for aditya: ")

    threading.Thread(
        target=monitoring_loop,
        daemon=True,
    ).start()

    print("Monitoring started.")
    print("Dashboard: http://localhost:9000")


if __name__ == "__main__":
    startup()
    uvicorn.run(app, host="0.0.0.0", port=9000)
