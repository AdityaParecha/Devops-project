class MinistralReasoner:
    def __init__(self, ollama, model: str):
        self.ollama, self.model = ollama, model

    def analyze(self, incident: dict, classification: dict, evidence: dict):
        prompt = f"""
Analyze this DevOps incident. Use only the supplied evidence.
Return JSON with exactly: probable_root_cause, supporting_evidence (array of strings),
recommended_action, action_risk, expected_verification, confidence.
recommended_action must be one of: restart_backend, no_action, escalate.
Never produce shell commands. Never invent facts. If evidence is insufficient, choose escalate.
The system has an allowlisted backend restart action only; it is not automatically authorized by your recommendation.

INCIDENT:
{incident}

CLASSIFICATION:
{classification}

EVIDENCE:
{evidence}
"""
        result = self.ollama.generate_json(
            self.model, prompt,
            "You are a cautious SRE assistant. Output JSON only. Do not issue commands."
        )
        allowed = {"restart_backend", "no_action", "escalate"}
        action = result.get("recommended_action", "escalate")
        if action not in allowed:
            action = "escalate"
        return {
            "probable_root_cause": str(result.get("probable_root_cause", "Insufficient evidence"))[:600],
            "supporting_evidence": [str(x)[:250] for x in result.get("supporting_evidence", [])[:8]],
            "recommended_action": action,
            "action_risk": str(result.get("action_risk", "unknown"))[:200],
            "expected_verification": str(result.get("expected_verification", "Recheck service health"))[:300],
            "confidence": max(0.0, min(1.0, float(result.get("confidence", 0) or 0)))
        }
