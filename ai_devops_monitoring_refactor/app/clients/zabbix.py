import requests
from typing import Any

class ZabbixError(RuntimeError):
    pass

class ZabbixClient:
    def __init__(self, url: str, username: str, password: str, timeout: int = 8, verify_tls: bool = True):
        self.url, self.username, self.password = url, username, password
        self.timeout, self.verify_tls = timeout, verify_tls
        self.session = requests.Session()
        self.auth = None
        self._request_id = 0

    def _rpc(self, method: str, params: dict, authenticated: bool = True):
        self._request_id += 1
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": self._request_id}
        if authenticated and self.auth:
            payload["auth"] = self.auth
        try:
            response = self.session.post(self.url, json=payload, timeout=self.timeout, verify=self.verify_tls)
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            raise ZabbixError(f"Zabbix API request failed: {exc}") from exc
        except ValueError as exc:
            raise ZabbixError("Zabbix API returned invalid JSON") from exc
        if body.get("error"):
            err = body["error"]
            raise ZabbixError(f"{err.get('message', 'Zabbix API error')}: {err.get('data', '')}")
        return body.get("result")

    def login(self):
        if not self.username or not self.password:
            raise ZabbixError("Set ZABBIX_USER and ZABBIX_PASSWORD in .env")
        # Zabbix 7.x uses username/password with user.login.
        self.auth = self._rpc("user.login", {"username": self.username, "password": self.password}, authenticated=False)
        if not self.auth:
            raise ZabbixError("Zabbix login returned no authentication token")
        return True

    def ensure_login(self):
        if not self.auth:
            self.login()

    def hosts(self):
        self.ensure_login()
        return self._rpc("host.get", {
            "output": ["hostid", "host", "name", "status", "available"],
            "selectInterfaces": ["ip", "available", "error"],
            "sortfield": "name"
        }) or []

    def snapshot(self, host_names: list[str]):
        self.ensure_login()
        hosts = self._rpc("host.get", {
            "output": ["hostid", "host", "name", "status", "available"],
            "filter": {"name": host_names},
            "selectInterfaces": ["ip", "available", "error"]
        }) or []
        result = {}
        for host in hosts:
            items = self._rpc("item.get", {
                "output": ["itemid", "name", "key_", "lastvalue", "lastclock", "units", "value_type"],
                "hostids": host["hostid"], "filter": {"state": 0},
                "monitored": True, "sortfield": "name"
            }) or []
            result[host.get("name") or host.get("host")] = {
                "host": host, "items": items
            }
        return result

    def problems(self, limit: int = 30):
        self.ensure_login()
        return self._rpc("problem.get", {
            "output": "extend", "selectHosts": ["hostid", "host", "name"], "sortfield": ["eventid"],
            "sortorder": "DESC", "limit": limit
        }) or []
