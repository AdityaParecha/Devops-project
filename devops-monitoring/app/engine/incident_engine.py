
from datetime import datetime, timezone
from collections import Counter
import re


class IncidentEngine:
    SEVERITY_ORDER = {
        "INFO": 1,
        "LOW": 2,
        "MEDIUM": 3,
        "HIGH": 4,
        "CRITICAL": 5,
    }

    def analyze(self, servers, problems, logs):
        incidents = []
        events = []
        managed_hosts = {
            str(server.get("name", key)).strip().lower(): server
            for key, server in servers.items()
        }

        # 1. Process Zabbix problems only for managed hosts.
        for problem in problems:
            hosts = problem.get("hosts") or []

            for host in hosts:
                host_name = (
                    host.get("name")
                    or host.get("host")
                    or ""
                ).strip()

                server = managed_hosts.get(host_name.lower())

                # Ignore Zabbix server and any unmanaged host.
                if not server:
                    continue

                title = problem.get("name", "Zabbix problem")
                title_lower = title.lower()
                severity_number = int(problem.get("severity", 0))

                # Package changes are informational, not operational incidents.
                if "installed packages" in title_lower and "changed" in title_lower:
                    events.append({
                        "source": "Zabbix",
                        "host": host_name,
                        "title": title,
                        "severity": "INFO",
                        "description": "Installed package inventory changed.",
                        "recommendation": (
                            "Review package-management history if this change "
                            "was unexpected."
                        ),
                    })
                    continue

                # Passive agent availability is distinct from fresh active data.
                if "agent is not available" in title_lower:
                    age = server.get("data_age_seconds")
                    fresh = age is not None and age <= 600

                    if fresh:
                        incidents.append({
                            "id": f"agent-connectivity-{problem.get('eventid', host_name)}",
                            "type": "AGENT_CONNECTIVITY_WARNING",
                            "source": "Zabbix",
                            "title": f"Passive Zabbix agent unavailable on {host_name}",
                            "severity": "LOW",
                            "hosts": [host_name],
                            "description": (
                                "Zabbix reports that passive agent checks are "
                                "unavailable, but recent monitoring data is "
                                "still being received."
                            ),
                            "evidence": [
                                f"Zabbix event ID: {problem.get('eventid', 'N/A')}",
                                f"Latest metric age: {age} seconds",
                                "Recent host metrics are available.",
                            ],
                            "root_cause": (
                                "The passive Zabbix agent interface is unavailable "
                                "or its checks are timing out. Active checks or "
                                "previously collected data may still be working."
                            ),
                            "recommendation": (
                                "Check agent service status, Server and "
                                "ServerActive configuration, port 10050 reachability, "
                                "and the Zabbix server allowed-host settings."
                            ),
                            "action": {
                                "type": "CHECK_ZABBIX_AGENT",
                                "automatic": False,
                            },
                            "status": "OPEN",
                        })
                    else:
                        incidents.append(self._make_incident(
                            problem,
                            host_name,
                            "HIGH",
                            "HOST_AGENT_UNAVAILABLE",
                            "No sufficiently recent host metrics are available.",
                            "Check VM availability, network connectivity, agent service and port 10050.",
                            "MANUAL_INVESTIGATION",
                        ))
                    continue

                severity = {
                    0: "INFO",
                    1: "INFO",
                    2: "LOW",
                    3: "MEDIUM",
                    4: "HIGH",
                    5: "CRITICAL",
                }.get(severity_number, "MEDIUM")

                incidents.append(self._make_incident(
                    problem,
                    host_name,
                    severity,
                    "ZABBIX_TRIGGER",
                    "Zabbix has an active trigger for this managed host.",
                    "Inspect the trigger expression, host metrics and related Loki logs.",
                    "MANUAL_INVESTIGATION",
                ))

        # 2. Check resource thresholds.
        for key, server in servers.items():
            name = server.get("name", key)
            metrics = server.get("metrics", {})

            if server.get("status") in ("DOWN", "NOT_FOUND"):
                incidents.append({
                    "id": f"host-unavailable-{key}",
                    "type": "HOST_UNAVAILABLE",
                    "source": "Monitoring Engine",
                    "title": f"{name} is unavailable",
                    "severity": "CRITICAL",
                    "hosts": [name],
                    "description": "The host is unavailable or missing from monitoring.",
                    "evidence": [
                        f"Host status: {server.get('status')}"
                    ],
                    "root_cause": "The monitoring host is not available or cannot be found.",
                    "recommendation": "Check VM power state, network connectivity and Zabbix agent.",
                    "action": {
                        "type": "MANUAL_INVESTIGATION",
                        "automatic": False,
                    },
                    "status": "OPEN",
                })

            cpu = self._value(metrics.get("cpu_utilization"))
            memory = self._value(metrics.get("memory_utilization"))
            disk = self._value(metrics.get("disk_utilization"))

            if cpu is not None and cpu >= 90:
                incidents.append(self._resource_incident(
                    key, name, "HIGH_CPU", "HIGH",
                    f"CPU utilization is {cpu:.1f}%.",
                    "CPU utilization has crossed 90%.",
                    "Inspect CPU-intensive processes and recent application activity.",
                    "INSPECT_PROCESSES",
                ))

            if memory is not None and memory >= 90:
                incidents.append(self._resource_incident(
                    key, name, "HIGH_MEMORY", "HIGH",
                    f"Memory utilization is {memory:.1f}%.",
                    "Memory utilization has crossed 90%.",
                    "Inspect memory-consuming processes and application memory usage.",
                    "INSPECT_MEMORY",
                ))

            if disk is not None and disk >= 90:
                incidents.append(self._resource_incident(
                    key, name, "HIGH_DISK", "CRITICAL",
                    f"Disk utilization is {disk:.1f}%.",
                    "Disk utilization has crossed 90%.",
                    "Identify large files and growing logs. Do not delete files automatically.",
                    "INSPECT_DISK",
                ))

        # 3. Correlate repeated Loki error logs by host.
        error_groups = Counter()
        samples = {}

        for log in logs:
            line = str(log.get("line", ""))
            host = str(log.get("host", "Unknown"))

            if re.search(
                r"\b(error|exception|fatal|panic|critical)\b",
                line,
                re.IGNORECASE,
            ):
                error_groups[host] += 1
                samples.setdefault(host, [])
                if len(samples[host]) < 3:
                    samples[host].append(line[:500])

        for host, count in error_groups.items():
            if host.lower() not in managed_hosts:
                continue

            if count >= 5:
                incidents.append({
                    "id": f"repeated-log-errors-{host.lower()}",
                    "type": "REPEATED_LOG_ERRORS",
                    "source": "Loki",
                    "title": f"{count} error log entries on {host}",
                    "severity": "MEDIUM",
                    "hosts": [host],
                    "description": "Repeated error-like messages were found in recent logs.",
                    "evidence": samples[host],
                    "root_cause": (
                        "Repeated application or service errors were found. "
                        "The log messages need correlation with metrics and timestamps."
                    ),
                    "recommendation": (
                        "Inspect the sample log messages, identify the failing "
                        "endpoint or service, and correlate with Zabbix metrics."
                    ),
                    "action": {
                        "type": "INSPECT_LOGS",
                        "automatic": False,
                    },
                    "status": "OPEN",
                })

        # 4. Sort incidents by severity.
        incidents.sort(
            key=lambda item: self.SEVERITY_ORDER.get(item["severity"], 0),
            reverse=True,
        )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "incident_count": len(incidents),
            "incidents": incidents,
            "informational_events": events,
            "automatic_remediation_enabled": False,
        }

    @staticmethod
    def _value(metric):
        if not metric:
            return None
        try:
            return float(metric.get("value"))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _make_incident(problem, host, severity, kind, cause, recommendation, action):
        return {
            "id": f"zabbix-{problem.get('eventid', kind)}-{host.lower()}",
            "type": kind,
            "source": "Zabbix",
            "title": problem.get("name", "Zabbix problem"),
            "severity": severity,
            "hosts": [host],
            "description": problem.get("name", ""),
            "evidence": [
                f"Zabbix event ID: {problem.get('eventid', 'N/A')}",
                f"Severity: {severity}",
            ],
            "root_cause": cause,
            "recommendation": recommendation,
            "action": {
                "type": action,
                "automatic": False,
            },
            "status": "OPEN",
        }

    @staticmethod
    def _resource_incident(key, host, kind, severity, title, cause, recommendation, action):
        return {
            "id": f"{kind.lower()}-{key}",
            "type": kind,
            "source": "Monitoring Engine",
            "title": title,
            "severity": severity,
            "hosts": [host],
            "description": cause,
            "evidence": [title],
            "root_cause": cause,
            "recommendation": recommendation,
            "action": {
                "type": action,
                "automatic": False,
            },
            "status": "OPEN",
        }
