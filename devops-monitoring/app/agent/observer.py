"""Collect read-only evidence from Zabbix, Loki and the three SSH hosts."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Callable
import paramiko
from app.config import settings


class Observer:
    # Fixed diagnostic commands only. No model-generated shell commands are run.
    COMMON_COMMANDS = {
        "system": "hostname && uptime",
        "memory": "free -m",
        "disk": "df -h",
        "cpu_processes": "ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head -10",
        "memory_processes": "ps -eo pid,comm,%cpu,%mem --sort=-%mem | head -10",
    }
    HOST_COMMANDS = {
        "frontend": {
            "nginx_status": "systemctl is-active nginx",
            "nginx_config_test": "nginx -t",
            "nginx_recent_logs": "journalctl -u nginx -n 60 --no-pager",
        },
        "backend": {
            "app_container_state": "docker inspect -f '{{.State.Status}}' devops-demo-app",
            "app_container_health": "docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' devops-demo-app",
            "app_recent_logs": "docker logs --tail 60 devops-demo-app",
        },
        "database": {
            "postgres_container_state": "docker inspect -f '{{.State.Status}}' postgres",
            "postgres_recent_logs": "docker logs --tail 60 postgres",
        },
    }

    def __init__(self, zabbix_client: Any, loki_client: Any,
                 overview_collector: Callable[[], dict],
                 ssh_timeout: int = 8, command_timeout: int = 12):
        self.zabbix = zabbix_client
        self.loki = loki_client
        self.overview_collector = overview_collector
        self.ssh_timeout = ssh_timeout
        self.command_timeout = command_timeout

    def _run_ssh_command(self, client: paramiko.SSHClient, command: str) -> dict:
        _, stdout, stderr = client.exec_command(command, timeout=self.command_timeout)
        output = stdout.read().decode("utf-8", errors="replace").strip()
        error = stderr.read().decode("utf-8", errors="replace").strip()
        return {
            "command": command,
            "output": output[:5000],
            "error": error[:1500],
            "exit_code": stdout.channel.recv_exit_status(),
        }

    def _ssh_diagnostics(self, server_key: str) -> dict:
        server = settings.servers[server_key]
        result = {"connected": False, "host": server["name"], "diagnostics": {}, "error": None}
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=server["ssh_host"], port=server["ssh_port"],
                username=settings.ssh_user,
                password=settings.ssh_password or None,
                key_filename=settings.ssh_key_file or None,
                timeout=self.ssh_timeout, banner_timeout=self.ssh_timeout,
                auth_timeout=self.ssh_timeout, look_for_keys=False, allow_agent=False,
            )
            result["connected"] = True
            commands = dict(self.COMMON_COMMANDS)
            commands.update(self.HOST_COMMANDS.get(server_key, {}))
            for name, command in commands.items():
                try:
                    result["diagnostics"][name] = self._run_ssh_command(client, command)
                except Exception as exc:
                    result["diagnostics"][name] = {
                        "command": command, "output": "",
                        "error": f"{type(exc).__name__}: {exc}", "exit_code": None,
                    }
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            client.close()
        return result

    def collect(self) -> dict:
        evidence = {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "monitoring": {}, "logs": {}, "ssh": {}, "collection_warnings": [],
        }
        try:
            overview = self.overview_collector()
            evidence["monitoring"] = {
                "connected": True,
                "servers": overview.get("servers", {}),
                "problems": overview.get("problems", []),
            }
        except Exception as exc:
            evidence["monitoring"] = {"connected": False, "error": str(exc)}
            evidence["collection_warnings"].append(f"Zabbix collection failed: {exc}")

        for server in settings.servers.values():
            host = server["name"]
            try:
                evidence["logs"][host] = self.loki.recent_logs(minutes=30, limit=100, host=host)
            except Exception as exc:
                evidence["logs"][host] = {"error": str(exc)}
                evidence["collection_warnings"].append(f"Loki collection failed for {host}: {exc}")

        for key in settings.servers:
            evidence["ssh"][key] = self._ssh_diagnostics(key)
            if not evidence["ssh"][key]["connected"]:
                evidence["collection_warnings"].append(
                    f"SSH unavailable for {settings.servers[key]['name']}"
                )
        return evidence
