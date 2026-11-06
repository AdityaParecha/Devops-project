import json
import threading
import time
from datetime import datetime
from getpass import getpass

import paramiko
import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn


# ============================================================
# CONFIGURATION
# ============================================================

BACKEND_URL = "http://localhost:8001"

# Ollama running on Windows host
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral:latest"

# IMPORTANT:
# Windows -> VirtualBox SSH forwarding
# localhost:2222 -> Backend VM :22
BACKEND_HOST = "localhost"
BACKEND_PORT = 2222
BACKEND_USER = "aditya"

# Monitoring interval
CHECK_INTERVAL = 3

# Automatically run AI remediation when backend goes DOWN
AUTO_REMEDIATE = True


# ============================================================
# GLOBAL STATE
# ============================================================

state = {
    "backend": "UNKNOWN",
    "database": "UNKNOWN",
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


# ============================================================
# EVENT LOG
# ============================================================

def add_event(message, level="info"):
    timestamp = datetime.now().strftime("%H:%M:%S")

    event = {
        "time": timestamp,
        "message": message,
        "level": level,
    }

    with state_lock:
        state["events"].insert(0, event)

        # Keep dashboard manageable
        state["events"] = state["events"][:30]


# ============================================================
# BACKEND HEALTH CHECK
# ============================================================

def check_backend():
    try:
        response = requests.get(
            f"{BACKEND_URL}/api/health",
            timeout=3,
        )

        if response.status_code == 200:
            data = response.json()

            database_status = data.get("database", "unknown")

            return True, database_status

        return False, "unknown"

    except Exception:
        return False, "unknown"


# ============================================================
# SSH EXECUTION
# ============================================================

def ssh_command(command, timeout=10):
    """
    Execute a restricted command on Backend VM.

    Windows:
        localhost:2222
             |
             v
    Backend VM :22
    """

    if not ssh_password:
        raise RuntimeError("SSH password not configured")

    client = paramiko.SSHClient()

    try:
        client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()
        )

        add_event(
            f"Connecting to backend via SSH localhost:{BACKEND_PORT}",
            "info",
        )

        client.connect(
            hostname=BACKEND_HOST,
            port=BACKEND_PORT,
            username=BACKEND_USER,
            password=ssh_password,

            # Prevent Paramiko from trying random local keys
            look_for_keys=False,
            allow_agent=False,

            # Connection/auth timeouts
            timeout=10,
            banner_timeout=10,
            auth_timeout=10,
        )

        add_event(
            f"SSH connected. Executing: {command}",
            "info",
        )

        stdin, stdout, stderr = client.exec_command(
            command,
            timeout=timeout,
        )

        output = stdout.read().decode(errors="ignore").strip()
        error = stderr.read().decode(errors="ignore").strip()

        exit_code = stdout.channel.recv_exit_status()

        if exit_code != 0:
            raise RuntimeError(
                f"Command failed (exit {exit_code}): {error or output}"
            )

        return output

    finally:
        client.close()


# ============================================================
# FAULT INJECTION
# ============================================================

def inject_backend_failure():
    """
    Intentionally stop backend container.
    This is the fault injection used for the demo.
    """

    command = "docker stop devops-demo-app"

    try:
        ssh_command(command)

        add_event(
            "Fault injected: backend container stopped",
            "critical",
        )

        with state_lock:
            state["incident"] = "BackendDown"

        return True, "Backend failure injected"

    except Exception as exc:
        add_event(
            f"Fault injection failed: {exc}",
            "critical",
        )

        return False, str(exc)


# ============================================================
# AI / MISTRAL
# ============================================================

def ask_mistral():
    """
    Ask local Mistral model for an incident remediation decision.
    """

    with state_lock:
        backend_status = state["backend"]
        database_status = state["database"]

    prompt = f"""
You are an autonomous DevOps incident response agent.

Current system state:

Backend: {backend_status}
Database: {database_status}
Incident: BackendDown

The backend service is unreachable.

Choose exactly ONE action:

restart_backend
no_action
escalate

Rules:

1. If Backend is DOWN and Database is healthy, choose restart_backend.
2. Do not invent shell commands.
3. Do not return commands.
4. Do not choose actions outside the allowed list.
5. Return ONLY valid JSON.

Required JSON format:

{{
  "action": "restart_backend",
  "reason": "short explanation"
}}
"""

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
        },
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=60,
    )

    response.raise_for_status()

    result = response.json()

    raw = result.get("response", "").strip()

    decision = json.loads(raw)

    action = decision.get("action")
    reason = decision.get("reason", "")

    allowed_actions = {
        "restart_backend",
        "no_action",
        "escalate",
    }

    if action not in allowed_actions:
        raise RuntimeError(
            f"Invalid AI action: {action}"
        )

    return action, reason


# ============================================================
# BACKEND RESTART
# ============================================================

def restart_backend():
    """
    AI-approved remediation.

    IMPORTANT:
    The AI does NOT generate this command.
    The command is hard-coded and allowlisted here.
    """

    command = "docker restart devops-demo-app"

    add_event(
        "Executing approved remediation: restart_backend",
        "warning",
    )

    try:
        output = ssh_command(command)

        add_event(
            "Backend restart command executed successfully",
            "success",
        )

        return True, output

    except Exception as exc:

        add_event(
            f"Backend restart failed: {exc}",
            "critical",
        )

        return False, str(exc)


# ============================================================
# VERIFICATION
# ============================================================

def verify_recovery():
    """
    Verify backend health after remediation.
    """

    add_event(
        "Verifying backend recovery...",
        "info",
    )

    with state_lock:
        state["agent"] = "VERIFYING"

    # Give Docker a little time to restart
    for attempt in range(1, 8):

        time.sleep(2)

        healthy, database = check_backend()

        with state_lock:
            state["database"] = (
                "HEALTHY"
                if database == "healthy"
                else database.upper()
            )

        if healthy:

            with state_lock:
                state["backend"] = "HEALTHY"
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

        add_event(
            f"Recovery check {attempt}/7: backend still DOWN",
            "warning",
        )

    with state_lock:
        state["verification"] = "FAILED"
        state["agent"] = "FAILED"

    add_event(
        "Health verification FAILED",
        "critical",
    )

    return False


# ============================================================
# INCIDENT HANDLER
# ============================================================

def handle_incident():
    global remediation_running

    # Prevent duplicate remediation threads
    if not remediation_lock.acquire(blocking=False):
        return

    remediation_running = True

    try:

        with state_lock:
            state["agent"] = "ANALYZING"
            state["action"] = None
            state["verification"] = None

        add_event(
            "Mistral analyzing incident",
            "info",
        )

        try:
            action, reason = ask_mistral()

        except Exception as exc:

            with state_lock:
                state["agent"] = "FAILED"

            add_event(
                f"Mistral error: {exc}",
                "critical",
            )

            return

        with state_lock:
            state["action"] = action

        add_event(
            f"AI decision: {action}",
            "info",
        )

        if reason:
            add_event(
                f"AI reasoning: {reason}",
                "info",
            )

        # ----------------------------------------------------
        # NO ACTION
        # ----------------------------------------------------

        if action == "no_action":

            with state_lock:
                state["agent"] = "READY"

            add_event(
                "AI decided no remediation is required",
                "warning",
            )

            return

        # ----------------------------------------------------
        # ESCALATE
        # ----------------------------------------------------

        if action == "escalate":

            with state_lock:
                state["agent"] = "ESCALATED"

            add_event(
                "Incident escalated for human intervention",
                "critical",
            )

            return

        # ----------------------------------------------------
        # RESTART BACKEND
        # ----------------------------------------------------

        if action == "restart_backend":

            with state_lock:
                state["agent"] = "EXECUTING"

            success, result = restart_backend()

            if not success:

                with state_lock:
                    state["agent"] = "FAILED"

                add_event(
                    f"Remediation failed: {result}",
                    "critical",
                )

                return

            verify_recovery()

    finally:

        remediation_running = False

        try:
            remediation_lock.release()
        except RuntimeError:
            pass


# ============================================================
# MONITORING LOOP
# ============================================================

def monitoring_loop():

    previous_backend = None

    add_event(
        "AI DevOps monitoring started",
        "success",
    )

    while monitor_running:

        try:

            healthy, database = check_backend()

            current_backend = (
                "HEALTHY"
                if healthy
                else "DOWN"
            )

            database_status = (
                "HEALTHY"
                if database == "healthy"
                else database.upper()
            )

            with state_lock:
                state["backend"] = current_backend
                state["database"] = database_status
                state["last_check"] = datetime.now().strftime(
                    "%H:%M:%S"
                )

            # ------------------------------------------------
            # HEALTHY -> DOWN
            # ------------------------------------------------

            if (
                previous_backend == "HEALTHY"
                and current_backend == "DOWN"
            ):

                with state_lock:
                    state["incident"] = "BackendDown"
                    state["agent"] = "DETECTED"

                add_event(
                    "Backend failure detected",
                    "critical",
                )

                if AUTO_REMEDIATE:
                    threading.Thread(
                        target=handle_incident,
                        daemon=True,
                    ).start()

            # ------------------------------------------------
            # DOWN -> HEALTHY
            # ------------------------------------------------

            elif (
                previous_backend == "DOWN"
                and current_backend == "HEALTHY"
            ):

                with state_lock:
                    state["incident"] = None

                    if state["agent"] not in (
                        "EXECUTING",
                        "VERIFYING",
                        "RECOVERED",
                    ):
                        state["agent"] = "READY"

                add_event(
                    "Backend recovered",
                    "success",
                )

            previous_backend = current_backend

        except Exception as exc:

            add_event(
                f"Monitoring error: {exc}",
                "critical",
            )

        time.sleep(CHECK_INTERVAL)


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="AI DevOps Control Center"
)


# ============================================================
# STATUS API
# ============================================================

@app.get("/api/status")
def api_status():

    with state_lock:
        return dict(state)


# ============================================================
# FAULT API
# ============================================================

@app.post("/api/fault")
def api_fault():

    success, message = inject_backend_failure()

    if success:
        return {
            "status": "success",
            "message": message,
        }

    return {
        "status": "failed",
        "error": message,
    }


# ============================================================
# MANUAL AI REMEDIATION API
# ============================================================

@app.post("/api/analyze")
def api_analyze():

    with state_lock:
        backend_status = state["backend"]
        incident = state["incident"]

    if backend_status != "DOWN":
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


# ============================================================
# DASHBOARD
# ============================================================

@app.get("/", response_class=HTMLResponse)
def dashboard():

    return HTMLResponse(
        """
<!DOCTYPE html>

<html>

<head>

<meta charset="UTF-8">

<title>AI DevOps Control Center</title>

<style>

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: #07111f;
    color: #e5edf8;
    font-family: Arial, Helvetica, sans-serif;
}

.container {
    max-width: 1500px;
    margin: auto;
    padding: 35px;
}

h1 {
    margin-bottom: 5px;
    font-size: 32px;
}

.subtitle {
    color: #7f91ad;
    margin-bottom: 30px;
}

.grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 18px;
}

.card {
    background: #101b2d;
    border: 1px solid #20304a;
    border-radius: 14px;
    padding: 22px;
    margin-bottom: 20px;
}

.card-title {
    color: #8ca0bd;
    font-size: 13px;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 12px;
}

.status {
    font-size: 22px;
    font-weight: bold;
}

.healthy {
    color: #45e38a;
}

.down {
    color: #ff5263;
}

.unknown {
    color: #f2c94c;
}

.agent {
    color: #6f8cff;
}

.controls {
    display: flex;
    gap: 15px;
}

button {
    border: 0;
    padding: 14px 22px;
    border-radius: 9px;
    font-size: 15px;
    font-weight: bold;
    cursor: pointer;
}

button:hover {
    opacity: 0.85;
}

.fault {
    background: #ff5263;
    color: white;
}

.remediate {
    background: #6f8cff;
    color: white;
}

.incident {
    font-size: 24px;
    font-weight: bold;
}

.timeline {
    max-height: 430px;
    overflow-y: auto;
}

.event {
    background: #0a1424;
    border-left: 4px solid #52627c;
    margin-bottom: 9px;
    padding: 13px 15px;
    border-radius: 5px;
}

.event.critical {
    border-color: #ff5263;
}

.event.success {
    border-color: #45e38a;
}

.event.warning {
    border-color: #f2c94c;
}

.event.info {
    border-color: #6f8cff;
}

.time {
    font-weight: bold;
    margin-right: 10px;
}

@media(max-width: 900px) {
    .grid {
        grid-template-columns: repeat(2, 1fr);
    }
}

</style>

</head>

<body>

<div class="container">

    <h1>AI DEVOPS CONTROL CENTER</h1>

    <div class="subtitle">
        Autonomous Incident Detection & Remediation
    </div>


    <!-- SYSTEM STATUS -->

    <div class="grid">

        <div class="card">

            <div class="card-title">
                Frontend
            </div>

            <div class="status healthy">
                ● HEALTHY
            </div>

        </div>


        <div class="card">

            <div class="card-title">
                Backend
            </div>

            <div
                id="backend"
                class="status unknown"
            >
                ● UNKNOWN
            </div>

        </div>


        <div class="card">

            <div class="card-title">
                Database
            </div>

            <div
                id="database"
                class="status unknown"
            >
                ● UNKNOWN
            </div>

        </div>


        <div class="card">

            <div class="card-title">
                AI Agent
            </div>

            <div
                id="agent"
                class="status agent"
            >
                READY
            </div>

        </div>

    </div>


    <!-- CONTROLS -->

    <div class="card">

        <div class="card-title">
            Demo Controls
        </div>

        <div class="controls">

            <button
                class="fault"
                onclick="injectFault()"
            >
                INJECT BACKEND FAILURE
            </button>


            <button
                class="remediate"
                onclick="runRemediation()"
            >
                RUN AI REMEDIATION
            </button>

        </div>

    </div>


    <!-- INCIDENT -->

    <div class="card">

        <div class="card-title">
            Incident Status
        </div>

        <div
            id="incident"
            class="incident"
        >
            No active incident
        </div>

        <div
            id="action"
            style="margin-top:10px;color:#8ca0bd;"
        >
        </div>

    </div>


    <!-- TIMELINE -->

    <div class="card">

        <div class="card-title">
            Incident Timeline
        </div>

        <div
            id="timeline"
            class="timeline"
        >
        </div>

    </div>

</div>


<script>

async function getStatus() {

    try {

        const response = await fetch(
            "/api/status",
            {
                cache: "no-store"
            }
        );

        const data = await response.json();

        updateDashboard(data);

    } catch (error) {

        console.error(
            "Status error:",
            error
        );

    }

}


function updateDashboard(data) {

    const backend =
        document.getElementById("backend");

    backend.innerText =
        "● " + data.backend;

    backend.className =
        "status " +
        (
            data.backend === "HEALTHY"
                ? "healthy"
                : data.backend === "DOWN"
                    ? "down"
                    : "unknown"
        );


    const database =
        document.getElementById("database");

    database.innerText =
        "● " + data.database;

    database.className =
        "status " +
        (
            data.database === "HEALTHY"
                ? "healthy"
                : "unknown"
        );


    const agent =
        document.getElementById("agent");

    agent.innerText =
        data.agent;


    const incident =
        document.getElementById("incident");

    if (data.incident) {

        incident.innerText =
            "⚠ " + data.incident;

        incident.style.color =
            "#ff5263";

    } else {

        incident.innerText =
            "No active incident";

        incident.style.color =
            "#45e38a";
    }


    const action =
        document.getElementById("action");

    if (data.action) {

        action.innerText =
            "AI Action: " +
            data.action +
            (
                data.verification
                    ? " | Verification: " +
                      data.verification
                    : ""
            );

    } else {

        action.innerText = "";

    }


    const timeline =
        document.getElementById("timeline");

    timeline.innerHTML = "";


    for (const event of data.events) {

        const div =
            document.createElement("div");

        div.className =
            "event " +
            event.level;

        div.innerHTML =
            '<span class="time">' +
            event.time +
            '</span>' +
            event.message;

        timeline.appendChild(div);
    }

}


async function injectFault() {

    try {

        const response = await fetch(
            "/api/fault",
            {
                method: "POST"
            }
        );

        const result =
            await response.json();

        console.log(
            "Fault:",
            result
        );

        await getStatus();

    } catch (error) {

        alert(
            "Fault injection failed: " +
            error
        );

    }

}


async function runRemediation() {

    try {

        const response = await fetch(
            "/api/analyze",
            {
                method: "POST"
            }
        );

        const result =
            await response.json();

        console.log(
            "Remediation:",
            result
        );

        await getStatus();

    } catch (error) {

        alert(
            "AI remediation failed: " +
            error
        );

    }

}


// Refresh dashboard every 2 seconds

getStatus();

setInterval(
    getStatus,
    2000
);

</script>

</body>

</html>
        """
    )


# ============================================================
# STARTUP
# ============================================================

def startup():

    global ssh_password

    print()
    print("=" * 60)
    print("AI DEVOPS CONTROL CENTER")
    print("=" * 60)
    print()
    print(
        f"Backend SSH: "
        f"{BACKEND_HOST}:{BACKEND_PORT}"
    )
    print(
        f"Backend API: "
        f"{BACKEND_URL}"
    )
    print(
        f"Ollama: "
        f"{OLLAMA_URL}"
    )
    print()

    ssh_password = getpass(
        "Enter backend VM password for aditya: "
    )

    # Start monitoring thread
    thread = threading.Thread(
        target=monitoring_loop,
        daemon=True,
    )

    thread.start()

    print()
    print("Monitoring started.")
    print("Dashboard: http://localhost:9000")
    print()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    startup()

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=9000,
    )