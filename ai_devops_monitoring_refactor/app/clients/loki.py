import requests
from datetime import datetime, timedelta, timezone

class LokiError(RuntimeError):
    pass

class LokiClient:
    def __init__(self, base_url: str, timeout: int = 8, verify_tls: bool = True):
        self.base_url = base_url.rstrip("/")
        self.timeout, self.verify_tls = timeout, verify_tls
        self.session = requests.Session()

    def ready(self):
        r = self.session.get(f"{self.base_url}/ready", timeout=self.timeout, verify=self.verify_tls)
        r.raise_for_status()
        return r.text.strip()

    def query_range(self, query: str, minutes: int = 15, limit: int = 100):
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=minutes)
        params = {
            "query": query,
            "start": str(int(start.timestamp() * 1_000_000_000)),
            "end": str(int(end.timestamp() * 1_000_000_000)),
            "limit": limit,
            "direction": "BACKWARD"
        }
        try:
            r = self.session.get(f"{self.base_url}/loki/api/v1/query_range", params=params,
                                 timeout=self.timeout, verify=self.verify_tls)
            r.raise_for_status()
            body = r.json()
        except (requests.RequestException, ValueError) as exc:
            raise LokiError(f"Loki query failed: {exc}") from exc
        if body.get("status") != "success":
            raise LokiError(f"Loki returned status {body.get('status')}")
        rows = []
        for stream in body.get("data", {}).get("result", []):
            labels = stream.get("stream", {})
            for ts, line in stream.get("values", []):
                rows.append({"timestamp": ts, "labels": labels, "line": line})
        return rows

    def recent_errors(self, minutes: int = 15, limit: int = 100):
        return self.query_range('{job=~".+"} |~ "(?i)error|exception|fatal|panic|critical"', minutes, limit)
