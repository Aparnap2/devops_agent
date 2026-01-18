# Architectural Decisions

> Why we chose LangGraph over generic chains.

## 1. State Machine vs. Linear Chain

### Decision: LangGraph StateGraph for Workflow Orchestration

**Alternative Considered:** LangChain's `SequentialChain` or `SimpleSequentialChain`

**Why LangGraph Wins for SRE:**

| Aspect | LangChain Chain | LangGraph StateGraph |
|--------|-----------------|---------------------|
| **State Persistence** | Lost between calls | Persisted via Checkpointer |
| **Cycle Support** | Linear only | Can loop back (retry, human-in-loop) |
| **Type Safety** | Dict-based | Pydantic model enforced |
| **Conditional Branching** | Hard-coded | Dynamic via router nodes |
| **Interrupts** | Not supported | `interrupt()` for approval |

### The Problem with Chains
```python
# LangChain - state is implicit dict
chain = diagnose_prompt | llm | parse_diagnosis
result = chain.invoke({"alert": alert})  # State is hidden in dict
```

### Our Solution with LangGraph
```python
# src/workflow/state.py:25-40
class IncidentState(State):
    fingerprint: str
    severity: str
    hypotheses: list[Hypothesis]
    plan: RemediationPlan | None
    status: WorkflowStatus

# src/workflow/nodes.py:45-52
def plan_node(state: IncidentState) -> IncidentState:
    if state.status != WorkflowStatus.DIAGNOSED:
        raise WorkflowValidationError(
            f"Invalid state transition: {state.status} -> PLANNING"
        )
```

**Result:** The agent cannot skip steps. You can't `execute` before `plan` is approved.

---

## 2. Why Not Direct LLM Calls?

### Decision: Tool-augmented Agent with Guardrails

**Alternative Considered:** Single LLM call: `llm.generate(fix_prompt)`

**Why Agent Architecture Wins:**

| Risk | Direct LLM Call | Agent Architecture |
|------|-----------------|-------------------|
| **Hallucination** | High - invents logs | Low - tool output required |
| **Safety** | No guardrails | Action allowlist enforced |
| **Observability** | Black box | Structured logs + trace IDs |
| **Reproducibility** | Varies by call | Deterministic with same state |

### The Danger of Direct Calls
```
User: "Fix the database"
LLM: "I'll run: DROP DATABASE production;"

# No validation, no safety, no trace
```

### Our Guardrails
```python
# src/execution/actions.py:15-22
class ActionType(str, Enum):
    RESTART_POD = "restart_pod"
    SCALE_DEPLOYMENT = "scale_deployment"
    DELETE_POD = "delete_pod"
    # No raw shell commands allowed

# src/execution/execution_manager.py:45-60
async def execute_action(self, action: Action) -> ActionResult:
    if action.type not in ActionType:
        raise SafetyViolationError(f"Unknown action type: {action.type}")

    if action.risk_level == "high" and not self.approval_received:
        raise ApprovalRequiredError(f"High-risk action requires approval")
```

---

## 3. Checkpoint Storage: Redis vs. Memory

### Decision: Redis Checkpointer for Production

**Alternative Considered:** In-memory `MemorySaver`

**Why Redis:**

| Requirement | MemorySaver | RedisCheckpointer |
|-------------|-------------|-------------------|
| **Persistence** | Lost on restart | Survives restart |
| **Distributed** | Single instance | Multi-instance |
| **Speed** | Faster | ~1ms overhead |
| **Recovery** | None | Resume from checkpoint |

### Our Implementation
```python
# src/workflow/checkpointer.py:20-35
from langgraph.checkpoint.redis import RedisSaver

checkpointer = RedisSaver(
    host=settings.redis_host,
    port=settings.redis_port,
    db=0
)

workflow = StateGraph(IncidentState, checkpoint=checkpointer)
```

**Result:** If the agent crashes mid-remediation, it resumes from the last checkpoint.

---

## 4. Local LLM: Ollama + OpenAI SDK

### Decision: Ollama with OpenAI Compatibility Layer

**Alternative Considered:** OpenAI API, Anthropic API, or vLLM

**Why Ollama:**

| Factor | Cloud APIs | Ollama |
|--------|------------|--------|
| **Cost** | Per-token pricing | Free (local) |
| **Latency** | Network overhead | ~50ms local |
| **Privacy** | Data leaves cluster | Stays local |
| **Model Selection** | Provider's catalog | Any GGUF model |
| **Offline** | No | Yes |

### Our Integration
```python
# src/llm/ollama.py:47-51
self._client = AsyncOpenAI(
    base_url=f"{settings.ollama_base_url}/v1",
    api_key="ollama",  # Any string works
    timeout=settings.ollama_timeout,
)
```

**Result:** No code changes if we switch back to OpenAI later. Same API interface.

---

## 5. Database: PostgreSQL for Incidents

### Decision: PostgreSQL over SQLite, MongoDB, or Qdrant

**Why PostgreSQL:**

| Requirement | PostgreSQL | SQLite | MongoDB |
|-------------|------------|--------|---------|
| **ACID** | ✅ Full | ✅ File-level | ❌ Eventual |
| **Type Safety** | ✅ Pydantic maps | ❌ Dynamic | ❌ JSON only |
| **UUID Support** | ✅ Native | ✅ | ❌ String |
| **Connection Pool** | ✅ asyncpg | ❌ | ✅ Motor |
| **Vector Search** | ✅ pgvector | ❌ | ✅ Native |

### Our Schema
```sql
-- infra/db/schema.sql:15-30
CREATE TABLE incidents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(500) NOT NULL,
    severity VARCHAR(50) NOT NULL,
    fingerprint VARCHAR(255) UNIQUE,  -- Deduplication key
    risk_score DECIMAL(4,3),
    alert_labels JSONB,               -- Flexible metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

---

## 6. Why Not Kubernetes Operator?

### Decision: Standalone Agent, Not Operator

**Alternative Considered:** Custom Resource Definition + Controller

**Why Standalone Wins for Development:**

| Aspect | Operator | Standalone Agent |
|--------|----------|------------------|
| **Development Speed** | Slow (Go, kubebuilder) | Fast (Python, LangGraph) |
| **Testing** | Requires cluster | Unit tests + integration |
| **Deployment** | Helm + CRD install | Simple `uv run` |
| **Flexibility** | Fixed reconciliation loop | Dynamic workflow |

**Trade-off:** For production at scale, a Kubernetes Operator would be better.
This agent is designed for:
- Development/pre-production debugging
- One-off incident response
- Learning/portfolio purposes

---

## Summary: The "Why" Stack

```
LangGraph    → Deterministic state machine, not ad-hoc chains
Redis        → Checkpoint persistence, not lost state
Ollama       → Free local LLM, no API costs
PostgreSQL   → Type-safe incidents, not loose JSON
Pydantic     → Validation at every boundary
```

This architecture prioritizes **safety**, **observability**, and **type safety** over convenience.
