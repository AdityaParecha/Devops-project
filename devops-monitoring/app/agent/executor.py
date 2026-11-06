"""Fixed SSH action allowlist. No free-form command execution."""
from typing import Any
import paramiko
from app.config import settings


class ExecutionRejected(RuntimeError):
    pass


class Executor:
    ACTIONS = {
        "restart_nginx": {
            "server_key": "frontend",
            "command": "sudo -n systemctl restart nginx",
            "description": "Restart Nginx service on Frontend",
        },
        "restart_backend": {
            "server_key": "backend",
            "command": "docker restart devops-demo-app",
            "description": "Restart demo application container on Backend",
        },
        "restart_database": {
            "server_key": "database",
            "command": "docker restart postgres",
            "description": "Restart PostgreSQL container on Database",
        },
    }

    def __init__(self, timeout: int = 25):
        self.timeout = timeout

    def execute(self, action_id: str, approved: bool, target_host: str | None = None) -> dict[str, Any]:
        if approved is not True:
            raise ExecutionRejected("Explicit human approval is required.")
        if action_id not in self.ACTIONS:
            raise ExecutionRejected("Action is not in the fixed allowlist.")
        action = self.ACTIONS[action_id]
        server = settings.servers[action["server_key"]]
        if target_host and target_host != server["name"]:
            raise ExecutionRejected("Requested host does not match the allowlisted target.")

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=server["ssh_host"], port=server["ssh_port"],
                username=settings.ssh_user,
                password=settings.ssh_password or None,
                key_filename=settings.ssh_key_file or None,
                timeout=self.timeout, banner_timeout=self.timeout,
                auth_timeout=self.timeout, look_for_keys=False, allow_agent=False,
            )
            _, stdout, stderr = client.exec_command(action["command"], timeout=self.timeout)
            output = stdout.read().decode("utf-8", errors="replace").strip()
            error = stderr.read().decode("utf-8", errors="replace").strip()
            code = stdout.channel.recv_exit_status()
            return {
                "executed": True, "action_id": action_id, "host": server["name"],
                "description": action["description"], "command": action["command"],
                "exit_code": code, "output": output[:2000], "error": error[:1200],
                "success": code == 0,
            }
        finally:
            client.close()

    def inject_backend_fault(self, confirmed: bool) -> dict[str, Any]:
        """Demo-only fault: stop the known demo container after explicit UI confirmation."""
        if confirmed is not True:
            raise ExecutionRejected("Explicit confirmation is required for demo fault injection.")
        server = settings.servers["backend"]
        command = "docker stop devops-demo-app"
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=server["ssh_host"], port=server["ssh_port"],
                username=settings.ssh_user,
                password=settings.ssh_password or None,
                key_filename=settings.ssh_key_file or None,
                timeout=self.timeout, banner_timeout=self.timeout,
                auth_timeout=self.timeout, look_for_keys=False, allow_agent=False,
            )
            _, stdout, stderr = client.exec_command(command, timeout=self.timeout)
            output = stdout.read().decode("utf-8", errors="replace").strip()
            error = stderr.read().decode("utf-8", errors="replace").strip()
            code = stdout.channel.recv_exit_status()
            return {
                "success": code == 0, "host": server["name"],
                "fault": "BACKEND_CONTAINER_STOPPED", "command": command,
                "exit_code": code, "output": output[:1000], "error": error[:1000],
            }
        finally:
            client.close()
