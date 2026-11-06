import re
from datetime import datetime, timezone

def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _item_value(items, patterns):
    for item in items:
        name = item.get("name", "")
        if any(re.search(p, name, re.I) for p in patterns):
            value = _num(item.get("lastvalue"))
            if value is not None:
                return {"name": name, "value": value, "units": item.get("units", "")}
    return None

def normalize_zabbix(snapshot: dict, configured_hosts: dict):
    normalized = {}
    for key, cfg in configured_hosts.items():
        host_data = snapshot.get(cfg["zabbix_host"])
        if not host_data:
            # Zabbix host names may be the technical host field, not visible name.
            host_data = next((v for n, v in snapshot.items() if n.lower() == cfg["zabbix_host"].lower()), None)
        if not host_data:
            normalized[key] = {"name": cfg["name"], "status": "UNKNOWN", "metrics": {}, "missing": ["Zabbix host not found"]}
            continue
        items = host_data["items"]
        metrics = {
            "cpu_utilization": _item_value(items, [r"CPU utilization", r"CPU used"]),
            "cpu_idle": _item_value(items, [r"CPU idle time"]),
            "memory_utilization": _item_value(items, [r"Memory utilization"]),
            "memory_available": _item_value(items, [r"Available memory", r"Available memory in"]),
            "load_5m": _item_value(items, [r"Load average \(5m"]),
            "load_15m": _item_value(items, [r"Load average \(15m"]),
            "disk_utilization": _item_value(items, [r"Space utilization", r"Disk.*utilization"]),
        }
        if metrics["cpu_utilization"] is None and metrics["cpu_idle"] is not None:
            idle = metrics["cpu_idle"]
            metrics["cpu_utilization"] = {
                "name": "Derived CPU utilization (100 - idle)",
                "value": max(0.0, min(100.0, 100.0 - idle["value"])),
                "units": "%"
            }
        missing = [k for k, v in metrics.items() if v is None]
        host = host_data["host"]
        # Zabbix host.available: 0=unknown, 1=available, 2=unavailable.
        import time
        agent_available = str(host.get("available", "0"))
        newest_item_clock = max((int(i.get("lastclock", 0) or 0) for i in items), default=0)
        has_fresh_data = newest_item_clock > 0 and (time.time() - newest_item_clock) <= 600
        if str(host.get("status", "0")) != "0":
            status = "DISABLED"
        elif agent_available == "2":
            status = "DOWN"
        elif agent_available == "1" or has_fresh_data:
            status = "HEALTHY"
        else:
            status = "UNKNOWN"
        normalized[key] = {"name": cfg["name"], "status": status, "metrics": metrics, "missing": missing}
    return normalized

def evaluate_rules(servers: dict, problems: list, logs: list):
    incidents = []
    for key, server in servers.items():
        m = server.get("metrics", {})
        cpu = (m.get("cpu_utilization") or {}).get("value")
        mem = (m.get("memory_utilization") or {}).get("value")
        load15 = (m.get("load_15m") or {}).get("value")
        if cpu is not None and cpu >= 90:
            incidents.append(_incident("high_cpu", key, "HIGH", f"CPU utilization is {cpu:.1f}%"))
        if mem is not None and mem >= 90:
            incidents.append(_incident("high_memory", key, "HIGH", f"Memory utilization is {mem:.1f}%"))
        if server.get("status") == "DOWN":
            incidents.append(_incident("host_unavailable", key, "CRITICAL", "Zabbix reports host unavailable"))
        if load15 is not None and load15 >= 4:
            incidents.append(_incident("high_system_load", key, "MEDIUM", f"15-minute load average is {load15:.2f}"))
    if problems:
        severity_map = {"0": "INFO", "1": "INFO", "2": "LOW", "3": "MEDIUM", "4": "HIGH", "5": "CRITICAL"}
        for p in problems[:20]:
            raw_severity = str(p.get("severity", "0"))
            severity = severity_map.get(raw_severity, "INFO")
            hosts = p.get("hosts") or []
            host = hosts[0] if hosts else {}
            host_name = host.get("name") or host.get("host") or "unknown"
            target = host_name.lower().replace(" ", "")
            if target not in {"frontend", "backend", "database"}:
                target = "unknown"
            incidents.append(_incident(
                "zabbix_problem", target, severity,
                p.get("name", "Active Zabbix problem"), event_id=p.get("eventid"),
                zabbix_severity=raw_severity, host_name=host_name
            ))
    if logs:
        by_host = {}
        for row in logs:
            labels = row.get("labels", {})
            host = labels.get("host", "unknown")
            by_host[host] = by_host.get(host, 0) + 1
        for host, count in by_host.items():
            if count >= 5:
                incidents.append(_incident("log_error_burst", host.lower(), "MEDIUM", f"{count} error-like log lines in recent window"))
    return _dedupe(incidents)

def _incident(kind, target, severity, summary, **extra):
    return {
        "id": f"{kind}:{target}:{extra.get('event_id', '')}",
        "type": kind, "target": target, "severity": severity,
        "summary": summary, "source": "deterministic", "created_at": datetime.now(timezone.utc).isoformat(),
        **extra
    }

def _dedupe(incidents):
    seen, result = set(), []
    for item in incidents:
        if item["id"] not in seen:
            seen.add(item["id"]); result.append(item)
    return result
