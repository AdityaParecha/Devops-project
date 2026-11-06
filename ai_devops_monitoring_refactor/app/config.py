import os
from dataclasses import dataclass

def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}

@dataclass(frozen=True)
class Settings:
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = int(os.getenv("APP_PORT", "9000"))
    check_interval: int = int(os.getenv("CHECK_INTERVAL", "15"))
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "8"))

    zabbix_url: str = os.getenv("ZABBIX_URL", "http://localhost:8085/api_jsonrpc.php")
    zabbix_user: str = os.getenv("ZABBIX_USER", "Admin")
    zabbix_password: str = os.getenv("ZABBIX_PASSWORD", "")
    zabbix_verify_tls: bool = _bool("ZABBIX_VERIFY_TLS", True)

    loki_url: str = os.getenv("LOKI_URL", "http://localhost:3100")
    loki_verify_tls: bool = _bool("LOKI_VERIFY_TLS", True)

    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    laya_model: str = os.getenv("LAYA_MODEL", "laya")
    ministral_model: str = os.getenv("MINISTRAL_MODEL", "ministral-3:3b")
    ollama_timeout: int = int(os.getenv("OLLAMA_TIMEOUT", "90"))
    laya_timeout: int = int(os.getenv("LAYA_TIMEOUT", "300"))

    ssh_user: str = os.getenv("SSH_USER", "aditya")
    ssh_password: str = os.getenv("SSH_PASSWORD", "")
    ssh_key_file: str = os.getenv("SSH_KEY_FILE", "")
    ssh_connect_timeout: int = int(os.getenv("SSH_CONNECT_TIMEOUT", "8"))

    automatic_remediation: bool = _bool("AUTOMATIC_REMEDIATION", True)
    allow_backend_restart: bool = _bool("ALLOW_BACKEND_RESTART", True)
    min_classifier_confidence: float = float(os.getenv("MIN_CLASSIFIER_CONFIDENCE", "0.70"))
    incident_cooldown_seconds: int = int(os.getenv("INCIDENT_COOLDOWN_SECONDS", "180"))
    max_log_lines: int = int(os.getenv("MAX_LOG_LINES", "35"))

    # SSH is routed through the existing Windows host-only port forwards.
    servers: dict = None

    def __post_init__(self):
        object.__setattr__(self, "servers", {
            "frontend": {"name": "Frontend", "host": os.getenv("FRONTEND_SSH_HOST", "localhost"), "port": int(os.getenv("FRONTEND_SSH_PORT", "2223")), "zabbix_host": os.getenv("FRONTEND_ZABBIX_HOST", "Frontend")},
            "backend": {"name": "Backend", "host": os.getenv("BACKEND_SSH_HOST", "localhost"), "port": int(os.getenv("BACKEND_SSH_PORT", "2222")), "zabbix_host": os.getenv("BACKEND_ZABBIX_HOST", "Backend")},
            "database": {"name": "Database", "host": os.getenv("DATABASE_SSH_HOST", "localhost"), "port": int(os.getenv("DATABASE_SSH_PORT", "2224")), "zabbix_host": os.getenv("DATABASE_ZABBIX_HOST", "Database")},
        })

settings = Settings()
