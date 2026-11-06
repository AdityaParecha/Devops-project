import time

class RemediationService:
    """Strict allowlist. LLM output can select an identifier, never a shell command."""
    def __init__(self, settings, ssh, health_check, add_event):
        self.settings, self.ssh = settings, ssh
        self.health_check, self.add_event = health_check, add_event

    def execute(self, action: str):
        if action != "restart_backend":
            return {"status": "blocked", "reason": "Action is not allowlisted"}
        if not self.settings.allow_backend_restart:
            return {"status": "blocked", "reason": "Backend restart is disabled by policy"}
        self.add_event("Policy approved allowlisted action: restart_backend", "warning")
        self.ssh.run("backend", "docker restart devops-demo-app", timeout=20)
        self.add_event("Backend container restart command completed", "success")
        for attempt in range(1, 9):
            time.sleep(2)
            healthy, db = self.health_check()
            if healthy and db == "healthy":
                self.add_event(f"Recovery verification passed (attempt {attempt})", "success")
                return {"status": "verified", "attempts": attempt}
        self.add_event("Recovery verification failed after backend restart", "critical")
        return {"status": "verification_failed", "attempts": 8}
