from app.engine.classifier import LayaClassifier

class FakeOllama:
    def systemone(self, model, state, questions, timeout=None):
        return {"answers": {
            "incident_type": {"choice": "application_error", "confidence": 0.91, "probabilities": {"application_error": 0.91}},
            "severity": {"choice": "HIGH"}
        }}

def test_laya_typed_decision_is_validated():
    result = LayaClassifier(FakeOllama(), "laya", 0.7).classify(
        {"type": "backend_service_down", "target": "backend", "summary": "health failed"},
        {"servers": {}, "recent_error_logs": [], "zabbix_problems": []}
    )
    assert result["incident_type"] == "application_error"
    assert result["accepted"] is True
    assert result["confidence"] == 0.91
