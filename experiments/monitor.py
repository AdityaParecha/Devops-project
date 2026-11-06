import json
import time
import requests
import paramiko
import getpass
import subprocess
from datetime import datetime


# ============================================================
# CONFIG
# ============================================================

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "mistral:latest"

SSH_HOST = "127.0.0.1"
SSH_PORT = 2222
SSH_USER = "aditya"

CONTAINER = "ai-devops-container"

POLL_INTERVAL = 1

# Thresholds
CPU_YELLOW = 70
CPU_RED = 90

MEM_YELLOW = 70
MEM_RED = 90

LATENCY_YELLOW = 1.0
LATENCY_RED = 3.0


# ============================================================
# LLAMA SERVER CLEANUP
# ============================================================

def stop_llama_server():

    print("[+] Stopping llama-server...")

    subprocess.run(
        [
            "taskkill",
            "/IM",
            "llama-server.exe",
            "/T",
            "/F"
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False
    )

    print("[+] llama-server stopped.")


# ============================================================
# SSH
# ============================================================

def connect_ssh():

    password = getpass.getpass("VM password: ")

    ssh = paramiko.SSHClient()

    ssh.set_missing_host_key_policy(
        paramiko.AutoAddPolicy()
    )

    ssh.connect(
        SSH_HOST,
        port=SSH_PORT,
        username=SSH_USER,
        password=password
    )

    print("[+] Connected to app-01")

    return ssh


def run_command(ssh, command):

    stdin, stdout, stderr = ssh.exec_command(
        command
    )

    output = stdout.read().decode(
        errors="replace"
    ).strip()

    return output


# ============================================================
# DOCKER STATS
# ============================================================

def get_stats(ssh):

    command = (
        f"docker stats {CONTAINER} "
        "--no-stream "
        "--format "
        "'{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}'"
    )

    output = run_command(
        ssh,
        command
    )

    if not output:
        return None

    try:

        cpu, memory, mem_percent = output.split("|")

        cpu = float(
            cpu.replace("%", "")
        )

        mem_percent = float(
            mem_percent.replace("%", "")
        )

        return {
            "cpu": cpu,
            "memory": memory,
            "memory_percent": mem_percent
        }

    except Exception:

        return None


# ============================================================
# CONTAINER STATUS
# ============================================================

def get_container_status(ssh):

    command = (
        f"docker inspect "
        f"--format='{{{{.State.Status}}}}' "
        f"{CONTAINER}"
    )

    return run_command(
        ssh,
        command
    )


# ============================================================
# APPLICATION HEALTH
# ============================================================

def check_health(ssh):

    start = time.perf_counter()

    command = (
        "curl -s -o /dev/null "
        "-w '%{http_code}' "
        "http://localhost:8000/"
    )

    status = run_command(
        ssh,
        command
    )

    latency = time.perf_counter() - start

    return {
        "status_code": status,
        "latency": latency
    }


# ============================================================
# RECENT LOGS
# ============================================================

def get_logs(ssh):

    command = (
        f"docker logs "
        f"--tail 30 "
        f"{CONTAINER}"
    )

    return run_command(
        ssh,
        command
    )


# ============================================================
# DETERMINISTIC DECISION
# ============================================================

def determine_state(
    container_status,
    stats,
    health
):

    # --------------------------------------------------------
    # Hard failure
    # --------------------------------------------------------

    if container_status != "running":
        return "RED"

    if health["status_code"] != "200":
        return "RED"

    if health["latency"] >= LATENCY_RED:
        return "RED"

    if stats:

        if stats["cpu"] >= CPU_RED:
            return "RED"

        if stats["memory_percent"] >= MEM_RED:
            return "RED"

    # --------------------------------------------------------
    # Warning conditions
    # --------------------------------------------------------

    if health["latency"] >= LATENCY_YELLOW:
        return "YELLOW"

    if stats:

        if stats["cpu"] >= CPU_YELLOW:
            return "YELLOW"

        if stats["memory_percent"] >= MEM_YELLOW:
            return "YELLOW"

    return "GREEN"


# ============================================================
# OLLAMA
# ============================================================

def ask_llm(
    state,
    stats,
    health,
    logs
):

    prompt = f"""
You are a DevOps incident analysis agent.

The deterministic monitoring system detected:

STATE: {state}

Container:
{json.dumps(stats, indent=2)}

Health:
{json.dumps(health, indent=2)}

Recent logs:
{logs}

Analyze the incident.

Return ONLY JSON:

{{
    "severity": "GREEN/YELLOW/RED",
    "diagnosis": "...",
    "evidence": ["...", "..."],
    "recommended_action": "..."
}}
"""

    response = requests.post(

        OLLAMA_URL,

        json={
            "model": MODEL,

            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a DevOps incident "
                        "analysis agent."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],

            "format": "json",

            "stream": False,

            # Keep Mistral loaded while monitor is running
            "keep_alive": -1,

            "options": {
                "temperature": 0
            }
        },

        timeout=30
    )

    response.raise_for_status()

    return response.json()["message"]["content"]


# ============================================================
# MONITOR
# ============================================================

def monitor():

    ssh = connect_ssh()

    print("\n====================================")
    print(" AI DEVOPS REAL-TIME MONITOR")
    print("====================================")
    print(f"Container : {CONTAINER}")
    print(f"Interval  : {POLL_INTERVAL}s")
    print("LLM       : Mistral (warm)")
    print("====================================\n")

    previous_state = None

    try:

        while True:

            timestamp = datetime.now().strftime(
                "%H:%M:%S"
            )

            # ----------------------------------------------
            # Collect deterministic metrics
            # ----------------------------------------------

            container_status = get_container_status(
                ssh
            )

            stats = get_stats(
                ssh
            )

            health = check_health(
                ssh
            )

            # ----------------------------------------------
            # Determine state
            # ----------------------------------------------

            state = determine_state(
                container_status,
                stats,
                health
            )

            cpu = (
                stats["cpu"]
                if stats
                else 0
            )

            mem = (
                stats["memory_percent"]
                if stats
                else 0
            )

            latency = health["latency"]

            print(
                f"[{timestamp}] "
                f"{state:6} | "
                f"CPU {cpu:5.1f}% | "
                f"MEM {mem:5.1f}% | "
                f"LAT {latency:5.2f}s | "
                f"HTTP {health['status_code']}"
            )

            # ----------------------------------------------
            # LLM ONLY ON ANOMALY
            # ----------------------------------------------

            if state in ("YELLOW", "RED"):

                # Avoid hammering LLM every second
                # for the same incident.
                if state != previous_state:

                    print(
                        "\n"
                        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
                        f" LLM TRIGGERED: {state}\n"
                        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
                    )

                    logs = get_logs(
                        ssh
                    )

                    result = ask_llm(
                        state,
                        stats,
                        health,
                        logs
                    )

                    print(
                        "\n[LLM ANALYSIS]"
                    )

                    print(result)

                    print()

            previous_state = state

            time.sleep(
                POLL_INTERVAL
            )

    except KeyboardInterrupt:

        print(
            "\n[+] Monitoring stopped."
        )

    finally:

        # Close SSH connection
        try:
            ssh.close()
            print("[+] SSH connection closed.")
        except Exception:
            pass

        # Stop llama-server when monitor exits
        stop_llama_server()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    monitor()