from app.engine.rules import evaluate_rules, normalize_zabbix

def test_cpu_threshold_creates_incident():
    servers = {"backend": {"metrics": {"cpu_utilization": {"value": 95}}, "status": "HEALTHY"}}
    result = evaluate_rules(servers, [], [])
    assert any(x["type"] == "high_cpu" for x in result)

def test_error_burst_creates_incident():
    logs = [{"labels": {"host": "Backend"}, "line": "ERROR test"} for _ in range(6)]
    result = evaluate_rules({}, [], logs)
    assert any(x["type"] == "log_error_burst" for x in result)

def test_missing_host_is_unknown():
    result = normalize_zabbix({}, {"frontend": {"name": "Frontend", "zabbix_host": "Frontend"}})
    assert result["frontend"]["status"] == "UNKNOWN"
    assert "Zabbix host not found" in result["frontend"]["missing"][0]


def test_zabbix_problem_uses_actual_severity_and_host():
    problem = {
        "eventid": "55",
        "name": "Linux: Number of installed packages has been changed",
        "severity": "1",
        "hosts": [{"name": "Frontend", "host": "Frontend"}]
    }
    result = evaluate_rules({}, [problem], [])
    assert result[0]["target"] == "frontend"
    assert result[0]["severity"] == "INFO"
