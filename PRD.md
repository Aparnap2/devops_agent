# DevOps/SRE Agent PRD

## Final revised PRD (portfolio-grade)

Build a single "hero loop": detect a Kubernetes incident, perform context-aware triage, propose a safe remediation plan, require human approval for risky actions, execute, then verify recovery and record a postmortem artifact.

---

## 1. Product Definition

**Autonomous Kubernetes SRE Intern** = an agent that listens to cluster/Prometheus signals, investigates with kubectl-equivalent tools, consults runbooks (memory), and executes a limited set of safe actions under explicit guardrails.

### Target User (Portfolio ICP)

- Hiring managers / SRE leads evaluating: incident thinking, safety, state machines, observability, and disciplined automation.
- Demo environment: local Kind/Minikube (or cheap VM) with reproducible failures via Chaos Mesh.

### Goals (What "Done" Means)

- End-to-end incident loop in <5 minutes: Alert → Triage → Plan → (HITL) → Execute → Verify → Record.
- Deterministic replay: the same chaos experiment produces the same agent decisions (given same policy + tools).
- Auditability: every tool call + decision + approval is logged.

### Non-Goals (Explicitly Cut)

- No "general DevOps copilot", no multi-cloud, no full AIOps anomaly detection platform.
- No auto-editing app code (only opens a GitHub issue optionally, like existing SRE-agent patterns).

---

## 2. Workflow Ownership (State Machine)

LangGraph-first design: explicit states, transitions, and stop conditions (HITL gates).

### Entry Points

- Alertmanager webhook (preferred)
- Manual trigger (CLI "simulate incident")
- Kubernetes event watcher (optional)

### Exit Conditions

- **Resolved**: service health checks pass + alert clears + verification succeeds
- **Escalated**: ambiguity too high / risk too high / insufficient permissions
- **Aborted**: policy denies action or human rejects plan

### Core Process Map (Text)

```
[Signal Ingest]
  → [Incident Create + Dedup]
  → [Gather Context] (pods/events/logs/metrics)
  → [Hypothesis + RCA] (LLM + deterministic checks)
  → [Plan Remediation] (generate steps + risk score)
  → decision:
      - Auto-execute (only allowlisted "safe" actions)
      - HITL approve (default)
      - Escalate (create Slack/GitHub artifact)
  → [Execute]
  → [Verify] (SLO-ish checks + pod health + alert cleared)
  → [Write Incident Report + Memory Update]
```

---

## 3. Tech Stack (Opinionated, Minimal)

### Runtime / Infra

- **Kubernetes**: Kind (local) or Minikube
- **Chaos Engineering**: Chaos Mesh for reproducible failures (OOM, pod kill, network delay)
- **Observability**: Prometheus + Alertmanager + Grafana
- **Logs**: Loki (skip ELK for portfolio)

### Agent Platform

- **Orchestrator**: LangGraph (explicit state machine + HITL edges)
- **Agent Tools Interface**:
  - Python subprocess wrappers around `kubectl` (simplest), or
  - MCP style "tool servers" (more advanced)

### Data + Memory

- **Postgres** for incidents + audit log
- **pgvector** for runbook + past incident retrieval (optional but strong "context-aware" proof)

### UI / Integrations

- **Streamlit** "Control Tower" UI (incident timeline, approvals, plan diff)
- Optional Slack notifications + GitHub issue creation

---

## 4. SOPs (Operating Procedures)

### SOP-OPS-001: Incident Intake & Dedup

- If alert fingerprint seen in last N minutes, attach as update (no new incident).
- Else create incident record with: start time, alert labels, affected namespace/app.

### SOP-OPS-002: Safe Actions Allowlist (Auto-Exec Eligible)

Allow only actions that are reversible and scoped:

- **Restart a single pod** (delete pod; relies on Deployment/ReplicaSet)
- **Scale Deployment replicas** within min/max bounds
- **Roll back last Deployment** only if:
  - rollout history available
  - last change < X minutes
  - traffic impact below threshold

Everything else requires HITL.

### SOP-OPS-003: HITL Approval Policy

Human approval mandatory when any condition true:

- Action touches prod namespace (in demo, simulate "prod" label)
- Risk score ≥ 0.4
- Plan includes rollback, config change, or scaling beyond 2x
- RCA confidence < 0.7

### SOP-OPS-004: Verification & Closure

To mark resolved, require:

- Affected pods Running/Ready
- No CrashLoopBackOff events in last N minutes
- Alert cleared in Alertmanager
- "Smoke check" endpoint returns 200 (demo app endpoint)

### SOP-SEC-001: Prompt/Tool Safety

- Strict input validation: only allowlisted namespaces/apps accepted
- Never let the LLM produce raw shell; it must output a typed action schema

---

## 5. System Design & Architecture (Components)

### Services

| Service | Description |
|---------|-------------|
| `agent-orchestrator` | LangGraph workflow runner + policy engine |
| `tooling-layer` | K8s tools, Prometheus tools, GitHub tools (optional) |
| `incident-store` | Postgres: incidents, timelines, approvals, tool calls |
| `memory-store` | pgvector: runbook chunks + resolved incident embeddings |
| `ui` | Streamlit: incident dashboard + approval console |

### Typed Interfaces (Non-Negotiable)

Use Pydantic models for:

```python
class Incident(BaseModel)
class Observation(BaseModel)      # Tool outputs normalized
class Hypothesis(BaseModel)       # Root cause candidates with confidence
class Plan(BaseModel)             # Ordered actions
class Action(BaseModel)           # Typed, allowlisted
class ApprovalDecision(BaseModel)
class ExecutionResult(BaseModel)
```

### Key Design Decisions

- Deterministic policy engine decides if an action is allowed; LLM only proposes.
- Every tool call logged with: input params, output summary, latency, and incident id (audit).

---

## 6. Checklist (Build Order)

### MVP (Must-Have)

- [ ] Kind cluster + demo app + Chaos Mesh fault injection
- [ ] Prometheus + Alertmanager webhook into agent
- [ ] Incident DB schema + audit log table
- [ ] LangGraph workflow with states: Ingest → Gather → Diagnose → Plan → Approve → Execute → Verify → Report
- [ ] Allowlisted action executor (restart pod + scale deployment)
- [ ] Streamlit approval UI (Approve/Reject + reason)
- [ ] Incident report generator (Markdown)

### Strong Differentiators (Should-Have)

- [ ] pgvector runbook retrieval before planning
- [ ] Service dependency "mini-graph" (even static YAML) to compute blast radius
- [ ] GitHub issue creation on escalation

### Nice-to-Have

- [ ] Slack notifications
- [ ] "Read-only mode" toggle
- [ ] Replay mode (re-run from stored observations)

---

## 7. Tests (What Proves Engineering Maturity)

### Unit Tests

| Test | Description |
|------|-------------|
| Policy engine | Reject non-allowlisted actions; Require HITL above risk threshold |
| Risk scoring | Consistent output given same inputs |
| Dedup | Same fingerprint collapses into one incident |

### Integration Tests (Local)

| Scenario | Expected Behavior |
|----------|-------------------|
| Chaos Mesh OOM | Agent detects OOMKilled → proposes scaling/restart → requires approval → verifies recovery |
| Network delay | Agent distinguishes app latency vs pod crash → escalates if ambiguous |

### Safety Tests

- Prompt injection attempt via alert labels: Tool layer refuses invalid names; Plan schema validation fails closed

### Observability Tests

- Every incident has: Full timeline, Tool call trace, Approval record, Final outcome

---

## 8. Deliverables (Portfolio Package)

### Repository

- `/docs/`:
  - PRD.md (this)
  - ARCHITECTURE.md (components + data flow)
  - SOP.md (policies + approval gates)
  - THREAT_MODEL.md (top risks + mitigations)

### Demo Assets

- 3–5 minute screen recording: trigger Chaos Mesh → agent resolves
- `docker-compose.yml` for Postgres + Grafana + Prometheus
- `make demo` one-command setup script

### Evidence

- Sample incident reports (Markdown)
- Test report (pytest output)
- Performance notes: average time to triage/resolve

---

## 9. Open Questions

**Should the default mode be "HITL always" (safer, more realistic for a portfolio) or "auto-exec safe actions" (more impressive automation)?**

- **Recommendation**: HITL always for portfolio demo, with clear documentation of auto-exec capability.

---

## References

- [1] https://k8sgpt.ai
- [2] https://github.com/chaos-mesh/chaos-mesh
- [3] https://github.com/fuzzylabs/sre-agent
- [4] https://www.linkedin.com/posts/fuzzy-labs_are-ai-agents-ready-for-production-activity-7330159032462176258-KGUK
- [5] https://langchain-ai.github.io/langgraph/concepts/multi_agent/
- [6] https://www.fuzzylabs.ai/blog-post/how-we-built-our-sre-agent-using-fastmcp
- [7] https://www.linkedin.com/posts/fuzzy-labs_github-fuzzylabssre-agent-a-site-reliability-activity-7338503995050651648-MhWn
