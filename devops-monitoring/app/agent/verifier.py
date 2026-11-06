"""Verify service recovery after a human-approved action."""
from typing import Any, Callable
import paramiko
from app.config import settings


class Verifier:
    CHECKS = {
        "restart_nginx": ("frontend", "systemctl is-active nginx"),
        "restart_backend": ("backend", "docker inspect -f '{{.State.Status}}' devops-demo-app"),
        "restart_database": ("database", "docker inspect -f '{{.State.Status}}' postgres"),
    }

    def __init__(self, overview_collector: Callable[[], dict], loki_client: Any, timeout: int = 12):
        self.overview_collector = overview_collector
        self.loki = loki_client
        self.timeout = timeout

    def _ssh(self, server_key: str, command: str) -> dict:
        server = settings.servers[server_key]
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
            out = stdout.read().decode("utf-8", errors="replace").strip()
            err = stderr.read().decode("utf-8", errors="replace").strip()
            code = stdout.channel.recv_exit_status()
            return {"connected": True, "output": out, "error": err, "exit_code": code}
        except Exception as exc:
            return {"connected": False, "error": f"{type(exc).__name__}: {exc}"}
        finally:
            client.close()

    def verify(self, action_id: str) -> dict:
        checks = {}
        if action_id not in self.CHECKS:
            return {"verified": False, "status": "NOT_VERIFIED", "checks": {"reason": "Unknown action"}}
        server_key, command = self.CHECKS[action_id]
        service = self._ssh(server_key, command)
        checks["service_or_container"] = service
        expected = "active" if action_id == "restart_nginx" else "running"
        service_ok = service.get("connected") is True and service.get("exit_code") == 0 and service.get("output", "").strip().lower() == expected
        checks["service_or_container_healthy"] = service_ok

        if action_id == "restart_nginx":
            http = self._ssh("frontend", "curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1/")
            code = http.get("output", "").strip()
            http_ok = http.get("connected") is True and http.get("exit_code") == 0 and len(code) == 3 and code.startswith("2")
            checks["frontend_http"] = http
            checks["frontend_http_healthy"] = http_ok
            service_ok = service_ok and http_ok
        elif action_id == "restart_backend":
            http = self._ssh("backend", "curl -sS -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:8000/api/health")
            code = http.get("output", "").strip()
            http_ok = http.get("connected") is True and http.get("exit_code") == 0 and len(code) == 3 and code.startswith("2")
            checks["backend_http"] = http
            checks["backend_http_healthy"] = http_ok
            service_ok = service_ok and http_ok

        try:
            overview = self.overview_collector()
            checks["zabbix_fresh_collection"] = {"success": True, "servers": overview.get("servers", {})}
        except Exception as exc:
            checks["zabbix_fresh_collection"] = {"success": False, "error": str(exc)}
        try:
            checks["recent_logs"] = self.loki.recent_logs(minutes=5, limit=50, host=settings.servers[server_key]["name"])
        except Exception as exc:
            checks["recent_logs"] = {"error": str(exc)}
        return {"verified": bool(service_ok), "status": "RECOVERED" if service_ok else "NOT_VERIFIED", "checks": checks}
