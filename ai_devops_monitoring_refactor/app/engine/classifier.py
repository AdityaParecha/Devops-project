from app.clients.ollama import OllamaError

INCIDENT_TYPES = {
    "high_cpu": "CPU utilization is persistently high",
    "high_memory": "Memory utilization is persistently high",
    "host_unavailable": "The monitored virtual machine or host is unavailable",
    "high_system_load": "System load average is elevated",
    "zabbix_problem": "Zabbix has raised an infrastructure problem",
    "log_error_burst": "A burst of error-like application or system logs was observed",
    "application_error": "The application is returning errors or failing health checks",
    "database_connectivity": "The application cannot connect to its database",
    "unknown": "The evidence does not fit another incident category"
}
SEVERITY_LEVELS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

class LayaClassifier:
    """Uses Laya's typed decision API; it does not ask Laya to generate prose."""
    def __init__(self, ollama, model: str, min_confidence: float = 0.70, timeout: int = 300):
        self.ollama, self.model, self.min_confidence, self.timeout = ollama, model, min_confidence, timeout

    def classify(self, incident: dict, evidence: dict):
        # Keep state compact: Laya's documented state/question budget is intentionally small.
        compact = {
            "incident": {
                "type": incident.get("type"),
                "target": incident.get("target"),
                "summary": incident.get("summary")
            },
            "evidence_summary": {
                "server_metrics": {
                    k: {mk: (mv.get("value") if isinstance(mv, dict) else mv)
                        for mk, mv in v.get("metrics", {}).items()}
                    for k, v in evidence.get("servers", {}).items()
                },
                "recent_log_lines": [x.get("line", "")[:180] for x in evidence.get("recent_error_logs", [])[:5]],
                "zabbix_problem_count": len(evidence.get("zabbix_problems", []))
            }
        }
        questions = {
            "incident_type": {
                "type": "choice",
                "instructions": "Which single incident category best matches the supplied DevOps evidence?",
                "criteria": INCIDENT_TYPES
            },
            "severity": {
                "type": "choice",
                "instructions": "What is the operational severity of this incident?",
                "criteria": {
                    "LOW": "Minor issue with no meaningful service impact",
                    "MEDIUM": "Degraded component or limited impact",
                    "HIGH": "Major service degradation or likely user impact",
                    "CRITICAL": "Core service unavailable or severe ongoing outage"
                }
            }
        }
        try:
            body = self.ollama.systemone(self.model, compact, questions, timeout=self.timeout)
        except OllamaError:
            raise
        answers = body["answers"]
        kind_answer = answers.get("incident_type", {})
        severity_answer = answers.get("severity", {})
        kind = kind_answer.get("choice", "unknown")
        if kind not in INCIDENT_TYPES:
            kind = "unknown"
        severity = severity_answer.get("choice", "MEDIUM")
        if severity not in SEVERITY_LEVELS:
            severity = "MEDIUM"
        try:
            confidence = float(kind_answer.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        return {
            "incident_type": kind,
            "affected_component": str(incident.get("target", "unknown"))[:80],
            "severity": severity,
            "confidence": confidence,
            "probabilities": kind_answer.get("probabilities", {}),
            "accepted": confidence >= self.min_confidence
        }
