import paramiko

class SSHExecutor:
    def __init__(self, settings):
        self.settings = settings

    def run(self, server_key: str, command: str, timeout: int = 15):
        # Deliberately accept only internal action identifiers; no caller-supplied shell text.
        if server_key not in self.settings.servers:
            raise ValueError("Unknown server")
        server = self.settings.servers[server_key]
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = {
            "hostname": server["host"], "port": server["port"],
            "username": self.settings.ssh_user,
            "look_for_keys": False, "allow_agent": False,
            "timeout": self.settings.ssh_connect_timeout,
            "banner_timeout": self.settings.ssh_connect_timeout,
            "auth_timeout": self.settings.ssh_connect_timeout
        }
        if self.settings.ssh_key_file:
            kwargs["key_filename"] = self.settings.ssh_key_file
        elif self.settings.ssh_password:
            kwargs["password"] = self.settings.ssh_password
        else:
            raise RuntimeError("Set SSH_PASSWORD or SSH_KEY_FILE in .env")
        try:
            client.connect(**kwargs)
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            output = stdout.read().decode(errors="replace").strip()
            error = stderr.read().decode(errors="replace").strip()
            code = stdout.channel.recv_exit_status()
            if code != 0:
                raise RuntimeError(error or output or f"SSH command exited {code}")
            return output
        finally:
            client.close()
