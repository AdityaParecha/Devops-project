# AWS lab setup (free tier, Mumbai)

The app runs on 3 small EC2 servers. Monitoring (Zabbix, Loki, Grafana), Ollama and the agent stay on the laptop. Tailscale joins all of them on one private network, so **no ports except SSH are opened on AWS**.

```
Laptop (Tailscale)                       AWS ap-south-1 (Tailscale)
  Zabbix server :10051  <-- agent2 ---   frontend  nginx :80  -> backend:8000
  Loki          :3100   <-- Alloy ----   backend   devops-demo-app (Podman) :8000 -> database:5432
  Agent + Ollama  ------- SSH -------->  database  postgres (Podman) :5432
```

You do every AWS step yourself. Steps marked **(Claude)** are mine.

---

## 1. Protect against charges (5 min)
1. AWS console → **Billing and Cost Management → Budgets → Create budget → Use a template → Zero spend budget**. Enter your email.
2. Check **Billing → Free tier** to see which free plan your account has.
3. **Always stop the 3 instances when you finish testing** (EC2 → select all 3 → Instance state → Stop). Three servers running 24 hours use 72 of about 750 free hours a month.

## 2. Tailscale on the laptop (5 min)
1. Install from https://tailscale.com/download/windows and sign in.
2. Run `tailscale ip -4` and note the `100.x.y.z` address. This is **LAPTOP_TS_IP**.
3. Open **PowerShell as Administrator** and allow the servers to reach Zabbix and Loki. The rule applies only to Tailscale addresses:
   ```powershell
   New-NetFirewallRule -DisplayName "AIOps lab: Zabbix + Loki from Tailscale" -Direction Inbound -Protocol TCP -LocalPort 10051,3100 -RemoteAddress 100.64.0.0/10 -Action Allow
   ```

## 3. Launch the servers (10 min)
EC2 → region **Asia Pacific (Mumbai) ap-south-1** → **Launch instances**:

| Setting | Value |
|---|---|
| Name | `aiops` (rename to frontend, backend, database afterwards) |
| AMI | **Ubuntu Server 24.04 LTS**, 64-bit (x86) |
| Instance type | the micro type marked **Free tier eligible** (t3.micro or t2.micro) |
| Key pair | Create new → name `aiops-ec2`, type **RSA**, format **.pem** → save to `C:\Users\adity\.ssh\aiops-ec2.pem` |
| Network | Create security group → **only** "Allow SSH from **My IP**". Do not allow HTTP or anything else. |
| Storage | 8 GiB gp3 (the default) |
| Number of instances | **3** |

Then rename the three instances `frontend`, `backend` and `database`.

Lock down the key file, or Windows SSH will refuse it. Run in normal PowerShell:
```powershell
icacls "$env:USERPROFILE\.ssh\aiops-ec2.pem" /inheritance:r /grant:r "$($env:USERNAME):R"
```

## 4. Set up each server, in this order: database, backend, frontend
For each server, use its **Public IPv4 address** from the EC2 console. Run these from `C:\coding\Devops` in PowerShell:

```powershell
$KEY = "$env:USERPROFILE\.ssh\aiops-ec2.pem"
$IP  = "<public IP of this server>"
scp -i $KEY -r infra\aws ubuntu@${IP}:~/
# backend only:
scp -i $KEY -r devops-demo-shop ubuntu@${IP}:~/
ssh -i $KEY ubuntu@$IP
```

On the server:
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --hostname=database      # use frontend / backend / database
# open the printed link and approve the device, then:
tailscale ip -4                            # note this server's 100.x address
```

Then run the setup for that server. Each one takes about 3-6 minutes:
```bash
sudo bash aws/setup.sh database <LAPTOP_TS_IP>
sudo bash aws/setup.sh backend  <LAPTOP_TS_IP> <DATABASE_TS_IP>
sudo bash aws/setup.sh frontend <LAPTOP_TS_IP> <BACKEND_TS_IP>
```
Each run ends with a check. Backend should print `{"status":"healthy",...}` and frontend should print `200`.

To use a database password other than `devops`, put the same value before both the database and backend commands: `sudo DB_PASSWORD=... bash aws/setup.sh ...`.

## 5. Send Claude
- The three Tailscale IPs (frontend, backend, database)
- Your laptop's Tailscale IP
- Whether every setup run ended with its success check

Don't send the `.pem` file or any passwords.

## 6. Laptop side (Claude)
- Start the monitoring stack, `docker compose up -d` in `devops-monitoring/`.
- Point the agent at the servers in `devops-monitoring/.env`: Tailscale IPs, port 22, `SSH_USER=ubuntu`, `SSH_KEY_FILE` = the `.pem` path.
- Switch the Zabbix hosts to the "Linux by Zabbix agent active" template through the Zabbix API.
- Confirm metrics in Zabbix, logs in Loki (`{host="Backend"}`), and agent SSH access.

---

## Daily use
- **Start:** EC2 → select the 3 instances → Start. Tailscale IPs stay the same, so nothing needs reconfiguring.
- **Stop:** select the 3 instances → Stop.
- **Rebuild a broken server:** terminate it, launch a new one, and repeat step 4 for it. No snapshots are needed.

## What runs where
| Server | Runs | Container names (the agent depends on these) |
|---|---|---|
| frontend | nginx (systemd), proxies to backend:8000 | n/a |
| backend | shop app, rootless Podman, host network | `devops-demo-app` |
| database | PostgreSQL 16, rootless Podman, host network | `postgres` |

Podman is installed with `podman-docker`, so the agent's existing `docker ...` commands work unchanged. Container logs go to the journal, and Alloy ships them to Loki with labels `host`, `job`, `unit`, `container` and `level`.
