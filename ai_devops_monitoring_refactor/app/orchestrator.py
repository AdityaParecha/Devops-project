import threading
import time
from datetime import datetime, timezone

from app.clients.zabbix import ZabbixClient, ZabbixError
from app.clients.loki import LokiClient, LokiError
from app.clients.ollama import OllamaClient, OllamaError
from app.config import settings
from app.engine.rules import normalize_zabbix, evaluate_rules
from app.engine.classifier import LayaClassifier
from app.engine.reasoner import MinistralReasoner
from app.services.ssh import SSHExecutor
from app.services.remediation import RemediationService
import requests

class Orchestrator:
    def __init__(self):
        self.lock = threading.RLock()
        self.remediation_lock = threading.Lock()
        self.running = True
        self.last_incident_at = {}
        self.state = {
            "status": "STARTING", "last_check": None,
            "sources": {"zabbix": "UNKNOWN", "loki": "UNKNOWN", "ollama": "UNKNOWN"},
            "servers": {}, "services": {"backend": "UNKNOWN"}, "incidents": [], "classification": None,
            "analysis": None, "action": None, "verification": None,
            "events": [], "layers": {
                "deterministic": "WAITING", "laya": "WAITING",
                "ministral": "WAITING", "policy": "WAITING", "remediation": "IDLE"
            }
        }
        self.zabbix = ZabbixClient(settings.zabbix_url, settings.zabbix_user, settings.zabbix_password,
                                   settings.request_timeout, settings.zabbix_verify_tls)
        self.loki = LokiClient(settings.loki_url, settings.request_timeout, settings.loki_verify_tls)
        self.ollama = OllamaClient(settings.ollama_url, settings.ollama_timeout)
        self.classifier = LayaClassifier(self.ollama, settings.laya_model, settings.min_classifier_confidence, settings.laya_timeout)
        self.reasoner = MinistralReasoner(self.ollama, settings.ministral_model)
        self.ssh = SSHExecutor(settings)
        self.remediator = RemediationService(settings, self.ssh, self.backend_health, self.add_event)

    def add_event(self, message, level="info"):
        event = {"time": datetime.now().strftime("%H:%M:%S"), "message": message, "level": level}
        with self.lock:
            self.state["events"].insert(0, event)
            self.state["events"] = self.state["events"][:100]

    def backend_health(self):
        try:
            r = requests.get("http://localhost:8000/api/health", timeout=3)
            if r.status_code == 200:
                return True, r.json().get("database", "unknown")
        except requests.RequestException:
            pass
        return False, "unknown"

    def collect(self):
        snapshot = self.zabbix.snapshot([v["zabbix_host"] for v in settings.servers.values()])
        servers = normalize_zabbix(snapshot, settings.servers)
        problems = self.zabbix.problems()
        logs = self.loki.recent_errors(minutes=15, limit=settings.max_log_lines)
        return servers, logs, problems

    def cycle(self):
        source_status = {}
        try:
            snapshot = self.zabbix.snapshot([v["zabbix_host"] for v in settings.servers.values()])
            servers = normalize_zabbix(snapshot, settings.servers)
            problems = self.zabbix.problems()
            source_status["zabbix"] = "CONNECTED"
        except ZabbixError as exc:
            source_status["zabbix"] = "ERROR"
            self.add_event(f"Zabbix integration error: {exc}", "critical")
            with self.lock:
                self.state["sources"].update(source_status)
                self.state["status"] = "DEGRADED"
                self.state["last_check"] = datetime.now().isoformat()
            return
        try:
            logs = self.loki.recent_errors(minutes=15, limit=settings.max_log_lines)
            source_status["loki"] = "CONNECTED"
        except LokiError as exc:
            logs = []
            source_status["loki"] = "ERROR"
            self.add_event(f"Loki integration error: {exc}", "critical")
        incidents = evaluate_rules(servers, problems, logs)
        app_healthy, app_database = self.backend_health()
        if not app_healthy:
            incidents.insert(0, {
                "id": "backend_service_down:backend",
                "type": "backend_service_down",
                "target": "backend",
                "severity": "CRITICAL",
                "summary": "Backend /api/health endpoint is unavailable",
                "source": "deterministic"
            })
        evidence = {"servers": servers, "backend_health": {"healthy": app_healthy, "database": app_database},
                    "recent_error_logs": logs[:settings.max_log_lines],
                    "zabbix_problems": problems[:20]}
        try:
            self.ollama.tags()
            source_status["ollama"] = "CONNECTED"
        except Exception:
            source_status["ollama"] = "ERROR"
        with self.lock:
            self.state["services"]["backend"] = "HEALTHY" if app_healthy else "DOWN"
            self.state.update({
                "status": "RUNNING" if source_status.get("loki") == "CONNECTED" else "DEGRADED",
                "last_check": datetime.now().isoformat(),
                "sources": {**self.state["sources"], **source_status},
                "servers": servers, "incidents": incidents
            })
            self.state["layers"]["deterministic"] = "COMPLETE"

        if incidents:
            self.process_incident(incidents[0], evidence)
        else:
            with self.lock:
                self.state["layers"].update({"laya": "IDLE", "ministral": "IDLE", "policy": "IDLE"})
                self.state["action"] = None
                self.state["verification"] = None

    def process_incident(self, incident, evidence):
        key = incident["id"]
        now = time.time()
        if now - self.last_incident_at.get(key, 0) < settings.incident_cooldown_seconds:
            return
        if not self.remediation_lock.acquire(blocking=False):
            return
        self.last_incident_at[key] = now
        try:
            self.add_event(f"Deterministic incident: {incident['summary']}", "warning")
            with self.lock: self.state["layers"]["laya"] = "RUNNING"
            classification = self.classifier.classify(incident, evidence)
            with self.lock:
                self.state["classification"] = classification
                self.state["layers"]["laya"] = "COMPLETE"
            self.add_event(f"Laya classified incident as {classification['incident_type']} ({classification['confidence']:.2f})", "info")
            if not classification["accepted"]:
                with self.lock:
                    self.state["layers"]["policy"] = "BLOCKED_LOW_CONFIDENCE"
                    self.state["action"] = {"status": "escalated", "reason": "Classifier confidence below threshold"}
                return
            with self.lock: self.state["layers"]["ministral"] = "RUNNING"
            analysis = self.reasoner.analyze(incident, classification, evidence)
            with self.lock:
                self.state["analysis"] = analysis
                self.state["layers"]["ministral"] = "COMPLETE"
            self.add_event(f"Ministral recommends: {analysis['recommended_action']}", "info")
            action = analysis["recommended_action"]
            # Only a backend-down incident can trigger the one automatic restart action.
            allowed_context = incident["type"] == "backend_service_down" and incident.get("target") == "backend"
            if action == "restart_backend" and not allowed_context:
                action = "escalate"
            if not settings.automatic_remediation:
                action = "escalate" if action == "restart_backend" else action
            with self.lock:
                self.state["layers"]["policy"] = "APPROVED" if action == "restart_backend" else "NO_EXECUTION"
                self.state["action"] = {"requested": analysis["recommended_action"], "approved": action}
            if action == "restart_backend":
                with self.lock: self.state["layers"]["remediation"] = "EXECUTING"
                result = self.remediator.execute(action)
                with self.lock:
                    self.state["action"] = {"requested": analysis["recommended_action"], "approved": action, **result}
                    self.state["verification"] = result["status"]
                    self.state["layers"]["remediation"] = result["status"].upper()
            elif action == "escalate":
                self.add_event("Incident escalated; no automatic action executed", "critical")
            else:
                self.add_event("No remediation required", "info")
        except (OllamaError, Exception) as exc:
            self.add_event(f"Incident analysis pipeline failed safely: {exc}", "critical")
            with self.lock:
                self.state["status"] = "DEGRADED"
                self.state["action"] = {"status": "blocked", "reason": str(exc)}
        finally:
            self.remediation_lock.release()

    def loop(self):
        self.add_event("AI DevOps modular controller started", "success")
        while self.running:
            try:
                self.cycle()
            except Exception as exc:
                self.add_event(f"Monitoring cycle failed: {exc}", "critical")
            time.sleep(settings.check_interval)

    def start(self):
        thread = threading.Thread(target=self.loop, daemon=True, name="monitoring-loop")
        thread.start()
        return thread


    def inject_backend_fault(self):
        # Fault injection uses the same explicitly allowlisted demo-container operation.
        try:
            self.ssh.run("backend", "docker stop devops-demo-app", timeout=20)
            self.add_event("Demo fault injected: backend container stopped", "critical")
            return {"status": "success", "message": "Backend demo container stopped"}
        except Exception as exc:
            self.add_event(f"Fault injection failed: {exc}", "critical")
            return {"status": "failed", "error": str(exc)}

    def analyze_now(self):
        threading.Thread(target=self.cycle, daemon=True, name="manual-analysis").start()
        return {"status": "started", "message": "A monitoring and analysis cycle was requested"}

    def snapshot(self):
        with self.lock:
            data = self.state.copy()
            # Compatibility fields keep the uploaded frontend functional during the refactor.
            data["frontend"] = data["servers"].get("frontend", {}).get("status", "UNKNOWN")
            data["backend"] = data.get("services", {}).get("backend", data["servers"].get("backend", {}).get("status", "UNKNOWN"))
            data["database"] = data["servers"].get("database", {}).get("status", "UNKNOWN")
            data["agent"] = data.get("layers", {}).get("ministral", "WAITING")
            data["incident"] = (data.get("incidents") or [None])[0]
            data["action_text"] = data.get("action")
            data["verification_text"] = data.get("verification")
            # Legacy metric names expected by the original browser UI.
            for key, server in data["servers"].items():
                metrics = server.get("metrics", {})
                cpu = metrics.get("cpu_utilization") or metrics.get("cpu_idle")
                mem = metrics.get("memory_utilization")
                server["cpu"] = cpu.get("value") if cpu else None
                server["ram_percent"] = mem.get("value") if mem else None
                server["ram_used"] = None
                server["ram_total"] = None
                server["disk_percent"] = (metrics.get("disk_utilization") or {}).get("value")
                server["uptime"] = None
                server["last_check"] = data.get("last_check")
            data["events"] = data.get("events", [])
            data["verification"] = data.get("verification")
            data["action"] = data.get("action")
            return data
