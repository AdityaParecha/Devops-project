
import requests
import time
from datetime import datetime, timezone
from typing import Any


class LokiError(RuntimeError):
    """Raised when a Loki API request fails."""


class LokiClient:
    def __init__(self, base_url: str, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{endpoint}"

        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()

        except requests.RequestException as exc:
            raise LokiError(f"Loki connection failed: {exc}") from exc
        except ValueError as exc:
            raise LokiError("Loki returned invalid JSON.") from exc

    def ready(self) -> bool:
        try:
            response = self.session.get(
                f"{self.base_url}/ready",
                timeout=self.timeout,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def labels(self) -> list[str]:
        result = self._get("/loki/api/v1/labels")
        return result.get("data", [])

    def label_values(self, label: str) -> list[str]:
        result = self._get(
            f"/loki/api/v1/label/{label}/values"
        )
        return result.get("data", [])

    def query_range(
        self,
        query: str = '{host=~".+"}',
        minutes: int = 30,
        limit: int = 100,
        direction: str = "backward",
    ) -> list[dict[str, Any]]:

        end = time.time()
        start = end - (minutes * 60)

        params = {
            "query": query,
            "start": str(int(start * 1_000_000_000)),
            "end": str(int(end * 1_000_000_000)),
            "limit": limit,
            "direction": direction,
        }

        result = self._get(
            "/loki/api/v1/query_range",
            params=params,
        )

        logs = []

        for stream in result.get("data", {}).get("result", []):
            stream_labels = stream.get("stream", {})

            for entry in stream.get("values", []):
                timestamp_ns, line = entry

                timestamp = datetime.fromtimestamp(
                    int(timestamp_ns) / 1_000_000_000,
                    tz=timezone.utc,
                ).isoformat()

                logs.append({
                    "timestamp": timestamp,
                    "labels": stream_labels,
                    "host": stream_labels.get("host", "Unknown"),
                    "job": stream_labels.get("job", "Unknown"),
                    "line": line,
                })

        return logs

    def recent_logs(
        self,
        minutes: int = 30,
        limit: int = 100,
        host: str | None = None,
    ) -> list[dict]:

        if host:
            query = f'{{host="{host}"}}'
        else:
            query = '{host=~".+"}'

        return self.query_range(
            query=query,
            minutes=minutes,
            limit=limit,
        )

    def recent_errors(
        self,
        minutes: int = 30,
        limit: int = 100,
    ) -> list[dict]:

        query = (
            '{host=~".+"} '
            '|~ "(?i)error|exception|fatal|panic|critical"'
        )

        return self.query_range(
            query=query,
            minutes=minutes,
            limit=limit,
        )

    def test_connection(self) -> dict:
        if not self.ready():
            raise LokiError(
                f"Loki is not ready at {self.base_url}"
            )

        available_labels = self.labels()

        return {
            "connected": True,
            "url": self.base_url,
            "labels": available_labels,
            "hosts": self.label_values("host")
            if "host" in available_labels else [],
            "jobs": self.label_values("job")
            if "job" in available_labels else [],
        }
