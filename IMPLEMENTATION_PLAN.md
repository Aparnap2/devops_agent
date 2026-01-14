# DevOps/SRE Agent - Detailed Implementation Plan

Based on the revised PRD and research, this document outlines the step-by-step implementation plan.

---

## Phase 1: Core Infrastructure (Days 1-2)

### 1.1 Kind Cluster Setup

```bash
# Create Kind cluster
kind create cluster --name sre-agent --config kind-config.yaml

# Install Chaos Mesh via Helm
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm install chaos-mesh chaos-mesh/chaos-mesh --namespace chaos-mesh --create-namespace
```

**Artifacts:**
- `kind-config.yaml` - Kind cluster configuration with extra ports
- `Makefile` - One-command setup (`make setup`)

### 1.2 Demo Application

A simple web app with health endpoints for testing:

```python
# demo-app/app.py
from flask import Flask
import os

app = Flask(__name__)

@app.route("/health")
def health():
    return {"status": "healthy"}, 200

@app.route("/ready")
def ready():
    return {"status": "ready"}, 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
```

**Deployment:**
- `demo-app/deployment.yaml` - K8s deployment
- `demo-app/service.yaml` - K8s service
- `demo-app/namespace.yaml` - Namespace with "prod" label

### 1.3 Chaos Mesh Faults

```yaml
# chaos/pod-kill.yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: pod-kill
  namespace: chaos-mesh
spec:
  selector:
    namespaces:
      - prod
  mode: one
  action: pod-kill

# chaos/oom.yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: oom
  namespace: chaos-mesh
spec:
  selector:
    namespaces:
      - prod
  mode: one
  stressors:
    memory:
      size: "100MB"
```

---

## Phase 2: Incident Store (Postgres) (Days 2-3)

### 2.1 Database Schema

```sql
-- schema.sql

-- Incidents table
CREATE TABLE incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(500) NOT NULL,
    description TEXT,
    severity VARCHAR(20) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'open',
    fingerprint VARCHAR(255) NOT NULL,
    namespace VARCHAR(100),
    affected_service VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP,
    UNIQUE(fingerprint)
);

-- Timeline/events table
CREATE TABLE timeline (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    description TEXT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Tool calls audit log
CREATE TABLE tool_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
    tool_name VARCHAR(100) NOT NULL,
    input_params JSONB NOT NULL,
    output_summary TEXT,
    duration_ms INTEGER,
    success BOOLEAN,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Approvals table
CREATE TABLE approvals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
    plan_id UUID,
    action_type VARCHAR(50) NOT NULL,
    target VARCHAR(255) NOT NULL,
    risk_score DECIMAL(3,2),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    approver VARCHAR(100),
    reason TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    decided_at TIMESTAMP
);

-- Indexes
CREATE INDEX idx_incidents_status ON incidents(status);
CREATE INDEX idx_incidents_fingerprint ON incidents(fingerprint);
CREATE INDEX idx_incidents_namespace ON incidents(namespace);
CREATE INDEX idx_timeline_incident ON timeline(incident_id);
CREATE INDEX idx_tool_calls_incident ON tool_calls(incident_id);
CREATE INDEX idx_approvals_incident ON approvals(incident_id);
```

### 2.2 Pydantic Models

```python
# src/db/models.py
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from enum import Enum

class IncidentStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    PLANNING = "planning"
    PENDING_APPROVAL = "pending_approval"
    EXECUTING = "executing"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    ABORTED = "aborted"

class IncidentBase(BaseModel):
    title: str
    description: Optional[str] = None
    severity: str
    fingerprint: str
    namespace: Optional[str] = None
    affected_service: Optional[str] = None

class IncidentCreate(IncidentBase):
    pass

class Incident(IncidentBase):
    id: str
    status: IncidentStatus
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True
```

---

## Phase 3: Tooling Layer (Days 3-4)

### 3.1 Kubernetes Tools Interface

```python
# src/tools/kubernetes.py
import subprocess
import json
import asyncio
from typing import Optional
from pydantic import BaseModel

class ToolResult(BaseModel):
    success: bool
    output: dict
    error: Optional[str] = None
    duration_ms: int = 0

class K8sTools:
    """kubectl wrappers for agent tools."""

    async def list_pods(
        self,
        namespace: str,
        label_selector: Optional[str] = None
    ) -> ToolResult:
        """List pods in namespace."""
        cmd = ["kubectl", "get", "pods", "-n", namespace, "-o", "json"]
        if label_selector:
            cmd.extend(["-l", label_selector])

        start = asyncio.get_event_loop().time()
        result = await self._run_cmd(cmd)
        duration_ms = int((asyncio.get_event_loop().time() - start) * 1000)

        return ToolResult(
            success=result.success,
            output=json.loads(result.output) if result.success else {},
            error=result.error,
            duration_ms=duration_ms
        )

    async def describe_pod(self, name: str, namespace: str) -> ToolResult:
        """Get pod details."""
        cmd = ["kubectl", "describe", "pod", name, "-n", namespace]
        result = await self._run_cmd(cmd)
        return ToolResult(
            success=result.success,
            output={"description": result.output},
            error=result.error
        )

    async def get_events(
        self,
        namespace: str,
        since_hours: int = 1
    ) -> ToolResult:
        """Get recent events."""
        cmd = [
            "kubectl", "get", "events",
            "-n", namespace,
            "--sort-by", ".lastTimestamp",
            "-o", "json"
        ]
        result = await self._run_cmd(cmd)
        return ToolResult(
            success=result.success,
            output=json.loads(result.output) if result.success else {},
            error=result.error
        )

    async def get_logs(
        self,
        name: str,
        namespace: str,
        tail_lines: int = 100
    ) -> ToolResult:
        """Get pod logs."""
        cmd = [
            "kubectl", "logs", name, "-n", namespace,
            f"--tail={tail_lines}"
        ]
        result = await self._run_cmd(cmd)
        return ToolResult(
            success=result.success,
            output={"logs": result.output},
            error=result.error
        )

    async def restart_pod(self, name: str, namespace: str) -> ToolResult:
        """Delete pod to trigger restart."""
        cmd = ["kubectl", "delete", "pod", name, "-n", namespace, "--wait=false"]
        result = await self._run_cmd(cmd)
        return ToolResult(
            success=result.success,
            output={"restarted": name},
            error=result.error
        )

    async def scale_deployment(
        self,
        name: str,
        namespace: str,
        replicas: int
    ) -> ToolResult:
        """Scale deployment."""
        cmd = [
            "kubectl", "scale", "deployment", name,
            "-n", namespace,
            f"--replicas={replicas}"
        ]
        result = await self._run_cmd(cmd)
        return ToolResult(
            success=result.success,
            output={"scaled": name, "replicas": replicas},
            error=result.error
        )

    async def rollout_status(self, name: str, namespace: str) -> ToolResult:
        """Check rollout status."""
        cmd = ["kubectl", "rollout", "status", "deployment", name, "-n", namespace]
        result = await self._run_cmd(cmd)
        return ToolResult(
            success=result.success,
            output={"status": "complete" if result.success else "pending"},
            error=result.error
        )

    async def _run_cmd(self, cmd: list[str]) -> ToolResult:
        """Run shell command asynchronously."""
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        return ToolResult(
            success=process.returncode == 0,
            output=stdout.decode(),
            error=stderr.decode() if process.returncode != 0 else None
        )
```

### 3.2 Prometheus Tools

```python
# src/tools/prometheus.py
import httpx
from typing import Optional
from pydantic import BaseModel

class PrometheusTools:
    def __init__(self, url: str = "http://localhost:9090"):
        self.url = url
        self.client = httpx.AsyncClient(timeout=30.0)

    async def query_instant(self, query: str) -> dict:
        """Execute instant query."""
        response = await self.client.get(
            f"{self.url}/api/v1/query",
            params={"query": query}
        )
        return response.json()

    async def query_range(
        self,
        query: str,
        start: int,
        end: int,
        step: str = "15s"
    ) -> dict:
        """Execute range query."""
        response = await self.client.get(
            f"{self.url}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step}
        )
        return response.json()

    async def get_active_alerts(self) -> list[dict]:
        """Get active alerts from Alertmanager."""
        response = await self.client.get(f"{self.url}/api/v1/alerts")
        return response.json().get("data", {}).get("alerts", [])
```

---

## Phase 4: LangGraph Workflow (Days 4-6)

### 4.1 State Definition

```python
# src/agent/state.py
from typing import TypedDict, Optional, List
from datetime import datetime
from enum import Enum

class IncidentStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    PLANNING = "planning"
    PENDING_APPROVAL = "pending_approval"
    EXECUTING = "executing"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    ABORTED = "aborted"

class AgentState(TypedDict):
    # Incident data
    incident_id: Optional[str]
    fingerprint: Optional[str]
    severity: Optional[str]
    status: IncidentStatus

    # Investigation
    observations: List[dict]  # Tool call results
    hypotheses: List[dict]    # Root cause candidates
    risk_score: float

    # Remediation
    plan: Optional[dict]      # Proposed actions
    approval_id: Optional[str]

    # Execution
    execution_results: List[dict]

    # Metadata
    thread_id: str
    created_at: datetime
    updated_at: datetime
```

### 4.2 Workflow Nodes

```python
# src/agent/nodes.py
from langgraph.types import interrupt, Command
from typing import Literal, Optional

def create_incident_node(state: AgentState) -> AgentState:
    """Create new incident from alert."""
    # Check for duplicate fingerprint
    # Create incident record in DB
    return {
        **state,
        "status": "investigating",
        "incident_id": "new-uuid",
    }

def gather_context_node(state: AgentState) -> AgentState:
    """Gather pod status, events, logs, metrics."""
    # Call K8s tools
    # Call Prometheus tools
    return {
        **state,
        "observations": [...],
    }

def diagnose_node(state: AgentState) -> AgentState:
    """Generate hypotheses from observations."""
    # Use LLM or rules to analyze
    return {
        **state,
        "hypotheses": [...],
        "risk_score": 0.5,
    }

def plan_node(state: AgentState) -> AgentState:
    """Generate remediation plan."""
    # Create action plan
    # Calculate risk score
    return {
        **state,
        "plan": {...},
    }

def approval_node(state: AgentState) -> Command[Literal["execute", "escalate", "abort"]]:
    """Pause for human approval."""
    # Determine if auto-approval is allowed
    # If high risk or requires approval: interrupt
    if state["risk_score"] >= 0.4:
        decision = interrupt({
            "incident_id": state["incident_id"],
            "plan": state["plan"],
            "risk_score": state["risk_score"],
            "question": "Do you approve this remediation plan?"
        })

        if decision.get("approved"):
            return Command(goto="execute")
        else:
            return Command(goto="escalate")

    # Low risk - auto approve
    return Command(goto="execute")

def execute_node(state: AgentState) -> AgentState:
    """Execute remediation plan."""
    # Execute allowed actions
    return {
        **state,
        "status": "executing",
        "execution_results": [...],
    }

def verify_node(state: AgentState) -> AgentState:
    """Verify recovery."""
    # Check pod health
    # Check alert cleared
    # Check smoke test
    return {
        **state,
        "status": "resolved" if verified else "failed",
    }

def report_node(state: AgentState) -> AgentState:
    """Generate incident report."""
    # Write timeline
    # Update memory store
    return state
```

### 4.3 Graph Construction

```python
# src/agent/graph.py
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from src.agent.state import AgentState
from src.agent.nodes import (
    create_incident_node,
    gather_context_node,
    diagnose_node,
    plan_node,
    approval_node,
    execute_node,
    verify_node,
    report_node,
)

def build_workflow() -> StateGraph:
    """Build the agent workflow graph."""
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("create_incident", create_incident_node)
    workflow.add_node("gather_context", gather_context_node)
    workflow.add_node("diagnose", diagnose_node)
    workflow.add_node("plan", plan_node)
    workflow.add_node("approval", approval_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("verify", verify_node)
    workflow.add_node("report", report_node)

    # Define edges
    workflow.add_edge(START, "create_incident")
    workflow.add_edge("create_incident", "gather_context")
    workflow.add_edge("gather_context", "diagnose")
    workflow.add_edge("diagnose", "plan")
    workflow.add_edge("plan", "approval")

    # Approval routing
    workflow.add_conditional_edges(
        "approval",
        lambda x: x,
        {
            "execute": "execute",
            "escalate": END,
            "abort": END,
        }
    )

    workflow.add_edge("execute", "verify")
    workflow.add_edge("verify", "report")
    workflow.add_edge("report", END)

    return workflow

def compile_workflow(checkpointer=None) -> StateGraph:
    """Compile workflow with checkpointer."""
    workflow = build_workflow()
    return workflow.compile(checkpointer=checkpointer)
```

---

## Phase 5: Streamlit Approval UI (Days 6-7)

### 5.1 UI Components

```python
# src/ui/app.py
import streamlit as st
import httpx
from datetime import datetime

st.set_page_config(page_title="SRE Agent Control Tower", layout="wide")

# Session state for incidents
if "incidents" not in st.session_state:
    st.session_state.incidents = []

def main():
    st.title("SRE Agent Control Tower")

    # Sidebar - Navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Go to", ["Dashboard", "Incidents", "Approvals", "Settings"])

    if page == "Dashboard":
        show_dashboard()
    elif page == "Incidents":
        show_incidents()
    elif page == "Approvals":
        show_approvals()
    elif page == "Settings":
        show_settings()

def show_dashboard():
    """Dashboard overview."""
    col1, col2, col3 = st.columns(3)
    col1.metric("Open Incidents", len([i for i in st.session_state.incidents if i["status"] != "resolved"]))
    col2.metric("Pending Approvals", len([i for i in st.session_state.incidents if i["status"] == "pending_approval"]))
    col3.metric("Resolved Today", 0)

    # Recent incidents
    st.subheader("Recent Incidents")
    for incident in st.session_state.incidents[-5:]:
        with st.expander(f"{incident['severity'].upper()} - {incident['title']}"):
            st.write(incident["description"])
            st.write(f"Status: {incident['status']}")

def show_incidents():
    """Incident list with details."""
    st.title("Incidents")

    # Filters
    status_filter = st.multiselect(
        "Filter by status",
        ["open", "investigating", "pending_approval", "resolved", "escalated"],
        default=["open", "investigating", "pending_approval"]
    )

    filtered = [i for i in st.session_state.incidents if i["status"] in status_filter]

    for incident in filtered:
        with st.expander(f"[{incident['status']}] {incident['title']}"):
            st.write(incident["description"])
            if st.button("View Details", key=incident["id"]):
                st.session_state.selected_incident = incident

def show_approvals():
    """Pending approvals."""
    st.title("Pending Approvals")

    pending = [i for i in st.session_state.incidents if i["status"] == "pending_approval"]

    for incident in pending:
        with st.container():
            st.subheader(incident["title"])
            st.write(incident["description"])

            # Plan details
            if incident.get("plan"):
                st.write("Proposed Actions:")
                for action in incident["plan"].get("actions", []):
                    st.write(f"- {action['type']}: {action['target']}")

                st.write(f"Risk Score: {incident['risk_score']}")

            # Approval buttons
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Approve", key=f"approve_{incident['id']}"):
                    # Call agent API to approve
                    st.success("Approved!")
            with col2:
                if st.button("Reject", key=f"reject_{incident['id']}"):
                    # Call agent API to reject
                    st.error("Rejected")

def show_settings():
    """Settings page."""
    st.title("Settings")

    st.text_input("Agent API URL", value="http://localhost:8000")
    st.text_input("Prometheus URL", value="http://localhost:9090")
    st.text_input("Kubernetes Config Path", value="~/.kube/config")

    st.subheader("Policy Settings")
    st.slider("Auto-approve risk threshold", 0.0, 1.0, 0.3)
    st.checkbox("Enable auto-approval for restart actions", value=True)
    st.checkbox("Enable auto-approval for scale actions", value=False)

if __name__ == "__main__":
    main()
```

---

## Phase 6: Integration Tests (Days 7-8)

### 6.1 Test Scenarios

```python
# tests/integration/test_oom_scenario.py
import pytest
import asyncio
from src.agent.graph import compile_workflow
from src.tools.kubernetes import K8sTools
from src.tools.prometheus import PrometheusTools

@pytest.fixture
def graph():
    from langgraph.checkpoint.memory import MemorySaver
    checkpointer = MemorySaver()
    return compile_workflow(checkpointer=checkpointer)

@pytest.fixture
def k8s_tools():
    return K8sTools()

@pytest.fixture
def prometheus_tools():
    return PrometheusTools()

@pytest.mark.asyncio
async def test_oom_scenario(graph, k8s_tools, prometheus_tools):
    """Test OOMKilled detection and remediation."""

    # 1. Simulate OOM event
    initial_state = {
        "incident_id": None,
        "fingerprint": "OOMKilled:prod-demo-app",
        "severity": "high",
        "status": "open",
        "observations": [],
        "hypotheses": [],
        "risk_score": 0.0,
        "plan": None,
        "approval_id": None,
        "execution_results": [],
        "thread_id": "test-oom-001",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    # 2. Run workflow
    config = {"configurable": {"thread_id": "test-oom-001"}}
    result = await graph.ainvoke(initial_state, config=config)

    # 3. Verify detection
    assert "OOM" in str(result.get("hypotheses", []))
    assert result["risk_score"] > 0.3

    # 4. Verify plan includes restart
    if result.get("plan"):
        assert any(a.get("type") == "restart_pod" for a in result["plan"].get("actions", []))

    # 5. Verify execution
    if result.get("execution_results"):
        assert result["execution_results"][0].get("success")

@pytest.mark.asyncio
async def test_network_delay_scenario(graph, k8s_tools, prometheus_tools):
    """Test network delay detection and escalation."""

    initial_state = {
        "incident_id": None,
        "fingerprint": "HighLatency:prod-demo-app",
        "severity": "medium",
        "status": "open",
        "observations": [],
        "hypotheses": [],
        "risk_score": 0.0,
        "plan": None,
        "approval_id": None,
        "execution_results": [],
        "thread_id": "test-latency-001",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    config = {"configurable": {"thread_id": "test-latency-001"}}
    result = await graph.ainvoke(initial_state, config=config)

    # Network issues should be ambiguous - may escalate
    assert result["status"] in ["resolved", "escalated"]
```

---

## Phase 7: Demo Assets (Day 8)

### 7.1 Demo Script

```bash
#!/bin/bash
# demo.sh - One-command demo setup and execution

set -e

echo "=== SRE Agent Demo ==="
echo "Setting up environment..."

# Setup Kind cluster
make setup-kind

# Install dependencies
make install

# Start Streamlit UI in background
make run-ui &

# Run the demo scenario
make demo-oom-scenario

echo "Demo complete! Open http://localhost:8501 to view the Control Tower."
```

### 7.2 Documentation

- `docs/ARCHITECTURE.md` - Component diagram and data flow
- `docs/SOP.md` - Policy documentation
- `docs/THREAT_MODEL.md` - Security considerations

---

## Running the Implementation

```bash
# Setup
make setup

# Run tests
make test

# Run demo
make demo

# Start UI
make run-ui
```

---

## Key Design Decisions

1. **LangGraph for State Machine**: Using `interrupt()` for HITL, `Command` for routing
2. **kubectl Subprocess**: Simpler than K8s client, easier to audit
3. **Postgres for Persistence**: Checkpoint + audit log in same DB
4. **Streamlit for UI**: Fast development, good for portfolio demos
5. **Chaos Mesh for Testing**: Reproducible, documented faults
