
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {
        "1", "true", "yes", "on"
    }


@dataclass
class Settings:
    # Application
    app_name: str = "AI DevOps Control Center"
    check_interval: int = int(os.getenv("CHECK_INTERVAL", "15"))
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "10"))
    max_log_lines: int = int(os.getenv("MAX_LOG_LINES", "35"))

    # Zabbix API
    zabbix_url: str = os.getenv(
        "ZABBIX_URL",
        "http://localhost:8085/api_jsonrpc.php"
    )
    zabbix_user: str = os.getenv("ZABBIX_USER", "Admin")
    zabbix_password: str = os.getenv("ZABBIX_PASSWORD", "")

    # Loki API
    loki_url: str = os.getenv(
        "LOKI_URL",
        "http://localhost:3100"
    )

    # Grafana
    grafana_url: str = os.getenv(
        "GRAFANA_URL",
        "http://localhost:3000"
    ).rstrip("/")

    grafana_dashboard_uid: str = os.getenv(
        "GRAFANA_DASHBOARD_UID",
        ""
    )

    # Ollama - kept configured, but AI pipeline is not our
    # current integration priority.
    ollama_url: str = os.getenv(
        "OLLAMA_URL",
        "http://localhost:11434"
    ).rstrip("/")

    laya_model: str = os.getenv("LAYA_MODEL", "laya")
    ministral_model: str = os.getenv(
        "MINISTRAL_MODEL",
        "mistral:latest"
    )

    ollama_timeout: int = int(os.getenv("OLLAMA_TIMEOUT", "90"))
    laya_timeout: int = int(os.getenv("LAYA_TIMEOUT", "300"))

    # SSH
    ssh_user: str = os.getenv("SSH_USER", "aditya")
    ssh_password: str = os.getenv("SSH_PASSWORD", "")
    ssh_key_file: str = os.getenv("SSH_KEY_FILE", "")

    # Remediation policy
    automatic_remediation: bool = env_bool(
        "AUTOMATIC_REMEDIATION", False
    )
    allow_backend_restart: bool = env_bool(
        "ALLOW_BACKEND_RESTART", False
    )
    min_classifier_confidence: float = float(
        os.getenv("MIN_CLASSIFIER_CONFIDENCE", "0.70")
    )
    incident_cooldown_seconds: int = int(
        os.getenv("INCIDENT_COOLDOWN_SECONDS", "180")
    )

    # Existing VirtualBox SSH forwarded ports
    servers: dict = None

    def __post_init__(self):
        self.servers = {
            "frontend": {
                "name": "Frontend",
                "zabbix_host": os.getenv(
                    "ZABBIX_FRONTEND_HOST", "Frontend"
                ),
                "ssh_host": os.getenv(
                    "FRONTEND_SSH_HOST", "localhost"
                ),
                "ssh_port": int(os.getenv(
                    "FRONTEND_SSH_PORT", "2223"
                )),
            },
            "backend": {
                "name": "Backend",
                "zabbix_host": os.getenv(
                    "ZABBIX_BACKEND_HOST", "Backend"
                ),
                "ssh_host": os.getenv(
                    "BACKEND_SSH_HOST", "localhost"
                ),
                "ssh_port": int(os.getenv(
                    "BACKEND_SSH_PORT", "2222"
                )),
            },
            "database": {
                "name": "Database",
                "zabbix_host": os.getenv(
                    "ZABBIX_DATABASE_HOST", "Database"
                ),
                "ssh_host": os.getenv(
                    "DATABASE_SSH_HOST", "localhost"
                ),
                "ssh_port": int(os.getenv(
                    "DATABASE_SSH_PORT", "2224"
                )),
            },
        }


settings = Settings()
