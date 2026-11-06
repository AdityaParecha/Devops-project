"""Orchestrates observe -> reason -> plan -> human approval -> execute -> verify."""
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable
from .executor import Executor
from .observer import Observer
from .planner import Planner
from .reasoner import OllamaReasoner
from .verifier import Verifier


class DevOpsAgent:
    def __init__(self, zabbix_client: Any, loki_client: Any,
                 overview_collector: Callable[[], dict],
                 reasoner: OllamaReasoner | None = None,
                 observer: Observer | None = None,
                 planner: Planner | None = None,
                 executor: Executor | None = None,
                 verifier: Verifier | None = None):
        self.observer = observer or Observer(zabbix_client, loki_client, overview_collector)
        self.reasoner = reasoner or OllamaReasoner()
        self.planner = planner or Planner()
        self.executor = executor or Executor()
        self.verifier = verifier or Verifier(overview_collector, loki_client)
        self._plans: dict[str, dict] = {}
        self._lock = RLock()

    def investigate(self) -> dict:
        evidence = self.observer.collect()
        diagnosis = self.reasoner.analyze(evidence)
        plans = self.planner.create_plans(diagnosis, evidence)
        with self._lock:
            for plan in plans:
                self._plans[plan.plan_id] = {
                    "plan": plan.to_dict(), "evidence": evidence,
                    "diagnosis": diagnosis.to_dict(), "execution": None, "verification": None,
                }
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "agent_status": diagnosis.status, "summary": diagnosis.summary,
            "diagnosis": diagnosis.to_dict(), "plans": [p.to_dict() for p in plans],
            "evidence_summary": {
                "zabbix_connected": evidence.get("monitoring", {}).get("connected", False),
                "ssh_hosts_connected": [k for k, v in evidence.get("ssh", {}).items() if v.get("connected")],
                "log_hosts_collected": [k for k, v in evidence.get("logs", {}).items() if isinstance(v, list)],
                "collection_warnings": evidence.get("collection_warnings", []),
            },
        }

    def get_plan(self, plan_id: str) -> dict | None:
        with self._lock:
            item = self._plans.get(plan_id)
            if not item:
                return None
            return {
                "plan": dict(item["plan"]),
                "diagnosis": item["diagnosis"],
                "execution": item["execution"],
                "verification": item["verification"],
            }

    def execute_approved_plan(self, plan_id: str, approved: bool) -> dict:
        if approved is not True:
            raise ValueError("Explicit human approval is required.")
        with self._lock:
            record = self._plans.get(plan_id)
            if not record:
                raise KeyError("Plan not found or expired. Run investigation again.")
            plan = record["plan"]
            if plan["status"] != "AWAITING_APPROVAL":
                raise ValueError("Plan is not awaiting approval or was already processed.")
            if not plan["approval_required"] or plan["action_id"] == "manual_investigation":
                raise ValueError("This plan has no executable action.")
            plan["status"] = "EXECUTING"

        try:
            execution = self.executor.execute(plan["action_id"], approved=True, target_host=plan["affected_host"])
            verification = self.verifier.verify(plan["action_id"]) if execution.get("success") else {"verified": False, "status": "NOT_RUN"}
            final_status = "RECOVERED" if execution.get("success") and verification.get("verified") else "EXECUTED_NOT_VERIFIED"
        except Exception as exc:
            execution = {"executed": False, "success": False, "error": f"{type(exc).__name__}: {exc}"}
            verification = {"verified": False, "status": "NOT_RUN"}
            final_status = "EXECUTION_FAILED"

        with self._lock:
            record["plan"]["status"] = final_status
            record["execution"] = execution
            record["verification"] = verification
        return {"plan_id": plan_id, "status": final_status, "execution": execution, "verification": verification}
