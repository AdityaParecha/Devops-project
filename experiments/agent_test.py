import json
import requests
import paramiko
import getpass
import re


# ============================================================
# CONFIG
# ============================================================

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "mistral:latest"

SSH_HOST = "127.0.0.1"
SSH_PORT = 2222
SSH_USER = "aditya"


# ============================================================
# ALLOWED COMMANDS
# ============================================================

# Read-only diagnostic commands + ONE remediation command.
ALLOWED_COMMANDS = {
    # Diagnostics
    "docker ps",
    "docker ps -a",
    "docker logs ai-devops-container",
    "docker inspect ai-devops-container",
    "ss -lntp",
    "curl -s http://localhost:8000/",
    "nproc",
    "free -h",
    "df -h",
    "uptime",
    "systemctl status docker --no-pager",

    # Remediation
    "docker start ai-devops-container",
}


# ============================================================
# SSH CONNECTION
# ============================================================

def connect_ssh():

    password = getpass.getpass("VM password: ")

    ssh = paramiko.SSHClient()

    ssh.set_missing_host_key_policy(
        paramiko.AutoAddPolicy()
    )

    ssh.connect(
        hostname=SSH_HOST,
        port=SSH_PORT,
        username=SSH_USER,
        password=password
    )

    print("[+] Connected to app-01")

    return ssh


# ============================================================
# TERMINAL EXECUTION
# ============================================================

def execute_command(ssh, command):

    # Security boundary
    if command not in ALLOWED_COMMANDS:

        result = (
            f"ERROR: Command '{command}' "
            "is not allowed."
        )

        print(f"\n[SECURITY] {result}")

        return result

    print(f"\n[TERMINAL] $ {command}")

    stdin, stdout, stderr = ssh.exec_command(command)

    output = stdout.read().decode(
        errors="replace"
    ).strip()

    error = stderr.read().decode(
        errors="replace"
    ).strip()

    if error:

        output += (
            "\nSTDERR:\n"
            + error
        )

    print(output)

    return output


# ============================================================
# OLLAMA
# ============================================================

def ask_ollama(messages):

    response = requests.post(
        OLLAMA_URL,

        json={
            "model": MODEL,
            "messages": messages,

            # Force JSON output
            "format": "json",

            "stream": False,

            # Keep Mistral loaded
            "keep_alive": -1,

            "options": {
                "temperature": 0
            }
        },

        timeout=120
    )

    response.raise_for_status()

    return response.json()["message"]["content"]


# ============================================================
# PARSE LLM JSON
# ============================================================

def parse_action(raw):

    print("\n[LLM RAW]")
    print(raw)

    # Normal JSON
    try:
        return json.loads(raw)

    except json.JSONDecodeError:
        pass

    # Try extracting JSON from accidental text
    match = re.search(
        r"\{.*\}",
        raw,
        re.DOTALL
    )

    if match:

        try:
            return json.loads(
                match.group()
            )

        except json.JSONDecodeError:
            pass

    return {
        "action": "final",
        "diagnosis": "Model returned invalid JSON.",
        "evidence": [],
        "confidence": "low"
    }


# ============================================================
# AGENT LOOP
# ============================================================

def run_agent(task):

    ssh = connect_ssh()

    messages = [

        # ----------------------------------------------------
        # SYSTEM
        # ----------------------------------------------------

        {
            "role": "system",

            "content": """

You are an autonomous Linux DevOps incident-response agent.

You operate on a server called app-01.

Your job is:

DETECT → DIAGNOSE → REMEDIATE → VERIFY

You do NOT directly execute commands.

Instead, return ONE JSON action at a time.

============================================================
AVAILABLE ACTIONS
============================================================

To execute a terminal command:

{
    "action": "run_terminal",
    "command": "docker ps"
}

To finish:

{
    "action": "final",
    "diagnosis": "description of what happened",
    "evidence": [
        "observed fact 1",
        "observed fact 2"
    ],
    "remediation": "what was done",
    "verification": "whether the application recovered",
    "confidence": "high"
}

============================================================
IMPORTANT RULES
============================================================

1. Return ONLY valid JSON.

2. Never use markdown.

3. Never invent terminal output.

4. Never claim that a command was executed unless
   the terminal result was actually returned to you.

5. Use the terminal whenever information is required.

6. You may perform multiple investigation steps.

7. Analyze the result of every terminal command before
   choosing your next action.

8. If docker ps shows no running containers,
   use docker ps -a.

9. If ai-devops-container is stopped, inspect its logs.

10. If the container is stopped and the evidence indicates
    that this is the cause of the application outage,
    you MAY start it using:

    docker start ai-devops-container

11. After starting the container, ALWAYS verify recovery
    using:

    curl -s http://localhost:8000/

12. Do not perform any other modifying operation.

13. Do not restart Docker.

14. Do not modify files.

15. Do not install packages.

16. Do not delete containers.

17. Do not delete images.

18. Do not execute arbitrary shell commands.

============================================================
ALLOWED COMMANDS
============================================================

docker ps
docker ps -a
docker logs ai-devops-container
docker inspect ai-devops-container
ss -lntp
curl -s http://localhost:8000/
nproc
free -h
df -h
uptime
systemctl status docker --no-pager
docker start ai-devops-container

============================================================
DECISION PROCESS
============================================================

First determine the state of the application.

If the container is running:
    investigate whether the application itself is responding.

If the container is stopped:
    inspect its logs and determine whether the stopped
    container explains the outage.

If the stopped container clearly explains the outage:
    start the container.

After starting:
    verify the application using curl.

Only finish once you have enough evidence.

============================================================
"""

        },

        # ----------------------------------------------------
        # USER TASK
        # ----------------------------------------------------

        {
            "role": "user",

            "content": task
        }
    ]


    MAX_STEPS = 10


    # ========================================================
    # AGENT LOOP
    # ========================================================

    for step in range(MAX_STEPS):

        print(
            f"\n========== AGENT STEP {step + 1} =========="
        )


        # ----------------------------------------------------
        # Ask LLM
        # ----------------------------------------------------

        raw = ask_ollama(messages)


        # ----------------------------------------------------
        # Parse JSON
        # ----------------------------------------------------

        action = parse_action(raw)


        action_type = action.get(
            "action"
        )


        # ====================================================
        # FINAL
        # ====================================================

        if action_type == "final":

            print(
                "\n========== AGENT FINAL ==========\n"
            )

            print(
                json.dumps(
                    action,
                    indent=2
                )
            )

            break


        # ====================================================
        # TERMINAL ACTION
        # ====================================================

        if action_type == "run_terminal":

            command = action.get(
                "command"
            )


            # -----------------------------------------------
            # Security validation
            # -----------------------------------------------

            if command not in ALLOWED_COMMANDS:

                result = (
                    "SECURITY ERROR: "
                    "Requested command is not allowed."
                )

                print(
                    f"\n[SECURITY] {command}"
                )

            else:

                result = execute_command(
                    ssh,
                    command
                )


            # -----------------------------------------------
            # Give terminal result back to LLM
            # -----------------------------------------------

            messages.append(
                {
                    "role": "user",

                    "content": (
                        "TERMINAL RESULT:\n\n"
                        + result
                        + "\n\n"
                        "Analyze this terminal result. "
                        "Then return exactly ONE JSON action."
                    )
                }
            )


            continue


        # ====================================================
        # INVALID ACTION
        # ====================================================

        print(
            "\n[ERROR] Invalid action:"
        )

        print(
            json.dumps(
                action,
                indent=2
            )
        )


        messages.append(
            {
                "role": "user",

                "content": (
                    "Your previous response was invalid. "
                    "Return ONLY one valid JSON action."
                )
            }
        )


    else:

        print(
            "\n[!] Maximum agent steps reached."
        )


    ssh.close()


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    task = input(
        "\nWhat should the agent investigate?\n> "
    )

    run_agent(task)