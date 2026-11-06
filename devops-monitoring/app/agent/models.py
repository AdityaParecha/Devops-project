from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentFinding:
    title: str
    severity: str
    affected_hosts: list[str]
    summary: str
    evidence: list[str] = field(default_factory=list)
    likely_causes: list[str] = field(default_factory=list)
    confidence: float = 0.0
    recommended_next_step: str = "Continue read-only investigation."
    requires_human_review: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentDiagnosis:
    status: str
    summary: str
    findings: list[AgentFinding]
    model: str
    generated_at: str = field(default_factory=utc_now)
    raw_model_output: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "findings": [item.to_dict() for item in self.findings],
            "model": self.model,
            "generated_at": self.generated_at,
            "raw_model_output": self.raw_model_output,
            "warnings": self.warnings,
        }


@dataclass
class RemediationPlan:
    plan_id: str
    status: str
    title: str
    explanation: str
    affected_host: str | None
    action_id: str
    action_label: str
    approval_required: bool
    risk: str
    verification: list[str]
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
