
import requests
from typing import Any


class ZabbixError(RuntimeError):
    """Raised when the Zabbix API request fails."""


class ZabbixClient:
    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        timeout: int = 10,
    ):
        self.url = url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.auth_token = None
        self.request_id = 0
        self.session = requests.Session()

    def _rpc(
        self,
        method: str,
        params: dict[str, Any],
        authenticated: bool = True,
    ) -> Any:
        self.request_id += 1

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self.request_id,
        }

        if authenticated and self.auth_token:
            payload["auth"] = self.auth_token

        try:
            response = self.session.post(
                self.url,
                json=payload,
                headers={"Content-Type": "application/json-rpc"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            result = response.json()
        except requests.RequestException as exc:
            raise ZabbixError(
                f"Zabbix connection failed: {exc}"
            ) from exc
        except ValueError as exc:
            raise ZabbixError(
                "Zabbix returned invalid JSON."
            ) from exc

        if "error" in result:
            error = result["error"]
            raise ZabbixError(
                f"{method}: {error.get('message')} "
                f"{error.get('data', '')}"
            )

        return result.get("result")

    def login(self) -> str:
        if not self.username or not self.password:
            raise ZabbixError(
                "Set ZABBIX_USER and ZABBIX_PASSWORD in .env"
            )

        self.auth_token = self._rpc(
            "user.login",
            {
                "username": self.username,
                "password": self.password,
            },
            authenticated=False,
        )

        if not self.auth_token:
            raise ZabbixError("Zabbix login failed.")

        return self.auth_token

    def ensure_login(self):
        if not self.auth_token:
            self.login()

    def hosts(self) -> list[dict]:
        self.ensure_login()

        return self._rpc(
            "host.get",
            {
                "output": [
                    "hostid",
                    "host",
                    "name",
                    "status",
                ],
                "selectInterfaces": [
                    "interfaceid",
                    "ip",
                    "dns",
                    "port",
                    "available",
                    "error",
                    "type",
                    "main",
                ],
                "sortfield": "name",
            },
        ) or []

    def snapshot(self, host_names: list[str]) -> dict:
        self.ensure_login()

        all_hosts = self.hosts()
        wanted = {name.strip().lower() for name in host_names}

        selected_hosts = [
            host for host in all_hosts
            if host.get("name", "").strip().lower() in wanted
            or host.get("host", "").strip().lower() in wanted
        ]

        result = {}

        for host in selected_hosts:
            items = self._rpc(
                "item.get",
                {
                    "output": [
                        "itemid",
                        "name",
                        "key_",
                        "lastvalue",
                        "lastclock",
                        "units",
                        "value_type",
                        "state",
                    ],
                    "hostids": host["hostid"],
                    "monitored": True,
                    "sortfield": "name",
                },
            ) or []

            result[host.get("name") or host["host"]] = {
                "host": host,
                "items": items,
            }

        return result

    def problems(self, limit: int = 30) -> list[dict]:
        self.ensure_login()

        problems = self._rpc(
            "problem.get",
            {
                "output": "extend",
                "sortfield": ["eventid"],
                "sortorder": "DESC",
                "limit": limit,
            },
        ) or []

        trigger_ids = list({
            str(problem["objectid"])
            for problem in problems
            if problem.get("objectid")
        })

        if not trigger_ids:
            return problems

        triggers = self._rpc(
            "trigger.get",
            {
                "output": [
                    "triggerid",
                    "description",
                    "priority",
                ],
                "triggerids": trigger_ids,
                "selectHosts": [
                    "hostid",
                    "host",
                    "name",
                ],
            },
        ) or []

        trigger_map = {
            str(trigger["triggerid"]): trigger
            for trigger in triggers
        }

        for problem in problems:
            trigger = trigger_map.get(str(problem.get("objectid")))
            problem["hosts"] = trigger.get("hosts", []) if trigger else []
            problem["trigger_description"] = (
                trigger.get("description") if trigger else None
            )

        return problems

    def test_connection(self) -> dict:
        token = self.login()
        hosts = self.hosts()

        return {
            "connected": bool(token),
            "host_count": len(hosts),
            "hosts": [
                {
                    "name": host.get("name"),
                    "technical_name": host.get("host"),
                    "hostid": host.get("hostid"),
                    "status": host.get("status"),
                    "interfaces": host.get("interfaces", []),
                }
                for host in hosts
            ],
        }
