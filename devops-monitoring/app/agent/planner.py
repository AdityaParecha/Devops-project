"""Deterministic planner. Never executes or trusts model-generated commands."""
import uuid
from typing import Any
from .models import AgentDiagnosis, RemediationPlan


class Planner:
    ACTIONS = {
        "Frontend": ("restart_nginx", "Restart Nginx on Frontend", "MEDIUM"),
        "Backend": ("restart_backend", "Restart demo application container", "HIGH"),
        "Database": ("restart_database", "Restart PostgreSQL container", "CRITICAL"),
    }

    def create_plans(self, diagnosis: AgentDiagnosis, evidence: dict[str, Any]) -> list[RemediationPlan]:
        plans = []
        ssh = evidence.get("ssh", {})
        # One plan per positively observed failed service. A model finding alone is not enough.
        observations = [
            ("frontend", "Frontend", "nginx_status", {"inactive", "failed"}),
            ("backend", "Backend", "app_container_state", {"exited", "dead"}),
            ("database", "Database", "postgres_container_state", {"exited", "dead"}),
        ]
        for key, host, diagnostic, failed_states in observations:
            host_evidence = ssh.get(key, {})
            item = host_evidence.get("diagnostics", {}).get(diagnostic, {})
            state = str(item.get("output", "")).strip().lower()
            if not host_evidence.get("connected") or state not in failed_states:
                continue
            action_id, label, risk = self.ACTIONS[host]
            plans.append(RemediationPlan(
                plan_id=str(uuid.uuid4()), status="AWAITING_APPROVAL",
                title=f"{label}: {host}",
                explanation=(f"SSH confirms {diagnostic} returned '{state}'. "
                             "This restart is a predefined action and requires explicit approval."),
                affected_host=host, action_id=action_id, action_label=label,
                approval_required=True, risk=risk,
                verification=["Confirm service/container is running.",
                              "Check fresh Zabbix metrics and Loki logs.",
                              "Confirm application/database health where applicable."],
            ))

        # If no service failure is proven, return a non-executable manual-review plan for each finding.
        if not plans:
            for finding in diagnosis.findings:
                host = finding.affected_hosts[0] if finding.affected_hosts else None
                plans.append(RemediationPlan(
                    plan_id=str(uuid.uuid4()), status="MANUAL_REVIEW",
                    title=f"Investigate: {finding.title}",
                    explanation=finding.recommended_next_step,
                    affected_host=host, action_id="manual_investigation",
                    action_label="Read-only investigation; no command will be executed",
                    approval_required=False, risk="LOW",
                    verification=["Review metrics, logs and SSH diagnostics."],
                ))
        return plans
