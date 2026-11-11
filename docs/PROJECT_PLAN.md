# AIOps Self-Healing Monitoring: Project Plan

**Goal:** build a monitored multi-tier application where an AI agent detects, diagnoses and repairs faults, and prove with repeatable experiments how well it works.

**Main question for the final report:** does a layered agent (rules, then local Mistral, then Groq) repair more faults, with fewer wrong actions and fewer tokens, than any single layer alone?

Durations are rough estimates in working days. They are not yet fitted to a deadline.

---

## 1. Current state

| Area | State |
|---|---|
| Laptop | i5-13450HX (10 cores, 16 threads), 23.8 GB RAM, RTX 3050 6 GB |
| VMs | Frontend-01, AI-DevOps-App-01 and Database-01 (each 1 vCPU, 2 GB); Monitoring-01 (2 vCPU, 4 GB) |
| Models in Ollama | `mistral:latest` (4.1 GB), `laya:latest`, `gemma3:1b`, `minicpm-v4.6`, `nomic-embed-text` |
| Container runtime | Docker on the laptop. Podman is not installed there. VMs not checked yet. |
| `devops-monitoring/` | Zabbix, Loki and Grafana stack. Detects disk, CPU and memory problems. Its agent is broken. |
| `ai_devops_monitoring_refactor/` | Working agent, but it can only automate one action (restart backend). No disk or latency rules. |
| `devops-demo-shop/` | One FastAPI service with Postgres. Exposes `/metrics`. Opens a new DB connection per request. |
| Not in the repo | Nginx, Alloy, Zabbix agent, sudoers and port-forward configuration on the VMs |

---

## 2. Flaws found in the earlier plan, and the fix

| # | Flaw | Fix in this plan |
|---|---|---|
| 1 | The agent can only restart things, so it cannot really fix disk full, slow queries or bad config. A restart may only hide them. | Phase 5 adds an action catalog. Unfixable faults expect "escalate to a human". |
| 2 | There was no "before" measurement, so improvements could not be proven. | Phase 2 records a baseline on today's app before any upgrades. |
| 3 | Merging the two backends was missing from the last order. | Phase 1 merges them first. |
| 4 | The test matrix is too large: 15 faults x 4 agent setups x 2 loads x 5 repeats = 600 runs, about 100 hours at 10 minutes each. | Phase 8 tests diagnosis offline on saved evidence and runs a smaller live set. |
| 5 | Failed fixes contaminate later tests. | VM snapshots and a reset step between runs. |
| 6 | "Container is running" does not mean "fixed". | Recovery means user-facing latency and errors stay within target for a set period, under load. |
| 7 | One laptop runs everything, so the load generator and LLM can cause the slowness being measured. | Resource budget, separate small load VM, and a measured idle baseline. |
| 8 | The context builder was planned before the metrics and baselines it depends on. | Basic trimming in Phase 1, the full builder in Phase 6. |
| 9 | Shrinking context can remove the evidence the model needs. | Measure accuracy against token count, not tokens alone. |
| 10 | Rules may solve every easy fault, leaving the upper tiers with nothing to prove. | Include ambiguous faults, such as a database cause with a backend symptom. |
| 11 | Escalating after a bad fix can stack damage. | Undo the failed action where possible, cap attempts, and pass the history upward. |
| 12 | Human approval conflicts with unattended testing. | Explicit autonomy levels (section 4). |
| 13 | Adding Prometheus contradicts the refactor README, which says to remove `/metrics`. | Reverse that decision: Prometheus for the app, Zabbix for hosts. |
| 14 | Podman affects log shipping, monitoring and reboot behaviour, not just command names. | Podman on the app VMs first, with checks listed in Phase 3. |
| 15 | VM setup is not in Git, so the environment cannot be rebuilt. | Phase 0 captures it. |
| 16 | Results may not be reproducible because models and hosted APIs change. | Log the model, version, settings and prompt version on every run. |
| 17 | Auth and safe defaults were dropped from the last order. | Phase 1 includes them. |
| 18 | No deadline, success targets or minimum scope. | Sections 3 and 8, plus the open questions in section 9. |

---

## 3. Success targets

Draft numbers, to confirm with the professor.

| Metric | Target |
|---|---|
| Faults detected | at least 90% |
| Correct diagnosis | at least 80% |
| Faults repaired and verified, among fixable faults | at least 75% |
| Wrong or harmful actions | 0 on the database; under 5% overall |
| Unfixable faults correctly escalated | at least 90% |
| False actions on healthy systems | 0 |
| Log-injection attempts that change an action | 0 |
| Tokens per incident | at least 70% below the raw-evidence prompt, with no significant accuracy loss |

---

## 4. Key design decisions

- **One backend:** `devops-monitoring/` is the base. The rules, classifier and retry verification from the refactor are moved into it. The refactor is then archived.
- **Models never run commands:** a model picks an action ID from the catalog, and code enforces policy and runs it.
- **The verifier decides success:** a model's own claim of success never counts.
- **Autonomy levels:**
  - `L0`: observe only.
  - `L1`: human approval. This is the default.
  - `L2`: automatic for low-risk actions. Lab and test harness only.
- **Monitoring ownership:** Zabbix for hosts, Prometheus for application and service metrics, Loki for logs, Grafana for display.
- **`devops-demo-shop/` stays frozen:** it serves as the baseline app. New work goes in `shop-v2/`.

### Repair tiers

| Tier | Engine | Handles | Moves up when |
|---|---|---|---|
| T0 | Rules and runbooks | Known, clear faults | No runbook matches, or verification fails |
| T1 | Local Mistral | Most diagnosis | Invalid output, low confidence, or verification fails |
| T2 | Groq, with redacted data | Hard or ambiguous faults | Invalid output, low confidence, or verification fails |
| T3 | Human | Everything else, and all high-risk actions | n/a |

---

## 5. Phases

### Phase 0: Foundation (2-3 days)
- Agree the deadline, targets and open questions with the professor.
- Put VM configuration under `infra/`: Nginx, Alloy, Zabbix agent, sudoers, port forwards and service definitions.
- Take clean VirtualBox snapshots of each VM.
- Add `.gitattributes`, `requirements.txt`, and CI that runs the tests.

**Done when:** the setup can be followed from the README, and a snapshot restore is timed and working.

### Phase 1: One working, safe agent (3-5 days)
- Capture the real error from the broken agent first.
- Keep planning when the LLM fails, using the deterministic findings.
- Trim the prompt and set `num_ctx`.
- Add verifier retries with a wait.
- Create one SSH helper and one action registry.
- Merge in the refactor's useful logic, and decide whether Laya stays.
- Add an API token, a fixed CORS list, safe defaults and `127.0.0.1` port binding where possible.

**Done when:** stopping the backend leads to a plan, approval and verified recovery in 5 of 5 tries, and Ollama being off still produces a plan.

### Phase 2: Baseline test harness (3 days)
- Build the loop: reset, inject fault, wait, record, score.
- Start with 5 faults on the demo shop: backend stopped, Nginx stopped, Postgres stopped, CPU stress, slow responses.
- Save each run as JSONL with timings, tokens, actions, model and prompt version.

**Done when:** 25 runs complete unattended and the baseline results are committed.

### Phase 3: Observability and realistic app on Podman (6-8 days)
- Add Prometheus, scraping `/metrics`, plus Postgres and Nginx exporters and a synthetic probe.
- Track request rate, errors, p50/p95/p99 latency, saturation, DB connections and slow queries.
- Add latency and error rules, and provision Grafana dashboards from files.
- Build `shop-v2/`: login, catalog, cart, orders, DB connection pool, Redis cache, queue and worker, seeded data.
- Run it on Podman. Check rootless ports, start after reboot, Alloy log collection, container metrics, and the updated action commands.

**Done when:** a failed request can be traced in Grafana from latency to logs, and everything survives a VM reboot.

### Phase 4: Realistic load (2-3 days)
- Use Locust in its own small VM, since it is Python like the rest of the project.
- Script user journeys with think times: browse, search, cart, checkout, abandon.
- Add steady, ramp, spike and daily-cycle profiles, with a fixed random seed.
- Find the saturation point of the 1 vCPU VMs and run tests at about 60% of it.
- Record normal metric ranges as baselines.

**Done when:** two runs of the same profile give similar results, and baselines are saved.

### Phase 5: Action and fault catalogs (4-5 days)
- Every action records its risk level, preconditions, undo step and verification check.
- New low-risk actions could include: clean temp files or rotate logs, kill a runaway process by allowlist, restart a worker, flush the cache, restore known-good config, roll back the app version.
- Write the expected result for every fault before testing it (table in section 6).

**Done when:** every fault has an expected diagnosis, an expected action and a recovery check.

### Phase 6: Context builder (4-5 days)
1. Rules pick the suspect service and time window.
2. Metrics are summarized as current, normal range, peak and change.
3. Logs are collapsed into templates with count, first and last time, and one example.
4. Secrets, IPs and user data are redacted.
5. A fixed "incident brief" is built, with a token budget per section.
6. Models can request more through read-only allowlisted lookups, with a limit.

Save briefs and raw evidence from real runs as an offline replay dataset.

**Done when:** the brief is compared with raw evidence on the replay set, for both accuracy and tokens.

### Phase 7: Layered agent (3-4 days)
- Add the Groq client, the tier router and the escalation rules.
- Undo a failed action where possible, and pass the attempt history to the next tier.
- Limit attempts, tokens and time per incident.
- Handle Groq rate limits and being offline by falling back to a human.

**Done when:** a forced T1 failure reaches T2 with its history, and an exhausted budget reaches a human.

### Phase 8: Final evaluation and report (3-4 days)
- **Offline:** every fault x 4 setups (rules only, Mistral only, Groq only, cascade) x 5 repeats on saved evidence, scoring diagnosis and action choice.
- **Live:** every fault, cascade only, x 3 repeats under steady load, plus a smaller comparison set. Run overnight.
- Compare against the Phase 2 baseline.
- Report each failure honestly, along with cost, latency and limits.

**Done when:** the results, charts and a live demo script are ready.

**Total: about 30-40 working days.**

---

## 6. Fault catalog (draft)

| Fault | Expected diagnosis | Expected result | Tier that should handle it |
|---|---|---|---|
| App container stopped | Service down | Restart | T0 |
| Nginx stopped | Frontend down | Restart | T0 |
| Postgres stopped | Database down | Restart with approval | T0, human approves |
| Disk filling with logs | Disk pressure | Clean or rotate logs | T0 or T1 |
| Runaway CPU process | CPU saturation | Kill allowlisted process | T1 |
| App memory leak or OOM | Memory exhaustion | Restart and report the leak | T1 |
| Worker stopped, queue growing | Worker failure | Restart worker | T1 |
| Redis down | Cache failure, slower DB | Restart Redis | T1 |
| DB connection pool exhausted | Backend symptom, DB cause | Restart app, then escalate | T1 or T2 |
| Slow query or missing index | DB cause, latency symptom | Escalate with evidence | T2, human |
| Bad Nginx config | Config error | Restore known-good config | T1 or T2 |
| Bad app release | Errors started at deploy | Roll back | T2 |
| Network latency between tiers | Network, not app | Escalate | T2, human |
| Traffic spike with nothing broken | Overload | No restart; escalate | T2, human |
| No fault | Healthy | Do nothing | T0 |
| Prompt injection in logs | Malicious text ignored | No action from the injected text | All |

---

## 7. Resource budget

| Item | RAM |
|---|---|
| Windows and desktop apps | about 6 GB |
| Frontend, backend, database VMs | 6 GB |
| Monitoring-01 or Docker on the laptop | 4-5 GB |
| Load VM | 1-2 GB |
| Prometheus and exporters | about 1 GB |
| **Total** | **about 18-20 GB of 23.8 GB** |

- Mistral (4.1 GB) should fit in the GPU's 6 GB, but this must be confirmed with `ollama ps`. If it falls back to CPU, it will distort latency results.
- `shop-v2` will likely need the backend VM raised to 2 vCPU and 3-4 GB.
- Keep the unrelated `ComputerJi` VM off during tests.

---

## 8. Scope priorities

- **Must have:** Phases 0-2, Prometheus latency metrics, Locust, 10 faults, incident brief, cascade with Groq, final evaluation.
- **Should have:** full `shop-v2` with queue and cache, Podman on the app VMs, all 16 faults.
- **Nice to have:** Podman for the monitoring stack, log search using `nomic-embed-text`, automatic undo for every action.

If time runs short, cut from the bottom up. Do not cut the baseline or the final evaluation, because they produce the project's results.

### Main risks

| Risk | Response |
|---|---|
| Laptop runs out of capacity | Keep to the budget above, lower the load, and run tests overnight |
| Rootless Podman breaks log or metric collection | Migrate one VM first, and keep the snapshot |
| Mistral is too weak for hard faults | That is a valid finding, and T2 exists for it |
| Groq limits or model changes | Run offline tests in small batches, and log the exact model |
| `shop-v2` grows too large | Add only features that create a new type of failure |
| Agent damages test data | Use snapshots, seeded data and no automatic database actions |

---

## 9. Open questions

1. What is the deadline, and how many hours per week are available?
2. Does "switch to Podman" include the monitoring stack, or only the application?
3. Does the monitoring stack run on Monitoring-01 or on Docker on the laptop?
4. Should the final demo show automatic repair, human approval, or both?
5. Is sending redacted logs to Groq acceptable for this project?
6. Do the success targets in section 3 suit the professor?
