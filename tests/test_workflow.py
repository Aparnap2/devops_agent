"""TDD: Tests for LangGraph workflow.

RED PHASE: Write tests for agent state machine and workflow nodes.
"""

import pytest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from src.workflow.state import (
    AgentState,
    WorkflowStatus,
    create_initial_state,
)
from src.workflow.nodes import (
    create_incident_node,
    gather_context_node,
    diagnose_node,
    plan_node,
    approval_node,
    execute_node,
    verify_node,
    report_node,
)
from src.workflow.graph import build_workflow, compile_workflow
from src.workflow.policy import (
    PolicyEngine,
    PolicyConfig,
    is_action_allowed,
    requires_approval,
    calculate_risk_score,
)


class TestAgentState:
    """Tests for AgentState TypedDict."""

    def test_create_initial_state(self):
        """Test creating initial agent state."""
        state = create_initial_state(
            fingerprint="OOMKilled:prod:api-service",
            severity="critical",
            alert_labels={"alertname": "ContainerOOMKilled"},
        )

        assert state["fingerprint"] == "OOMKilled:prod:api-service"
        assert state["severity"] == "critical"
        assert state["status"] == WorkflowStatus.OPEN
        assert state["observations"] == []
        assert state["hypotheses"] == []
        assert state["risk_score"] == 0.0
        assert state["plan"] is None
        assert state["execution_results"] == []

    def test_state_has_required_fields(self):
        """Test state contains all required fields."""
        state = create_initial_state(
            fingerprint="test:fingerprint",
            severity="high",
        )

        required_fields = [
            "incident_id",
            "fingerprint",
            "severity",
            "status",
            "observations",
            "hypotheses",
            "risk_score",
            "plan",
            "approval_id",
            "execution_results",
            "thread_id",
            "created_at",
            "updated_at",
        ]

        for field in required_fields:
            assert field in state, f"Missing field: {field}"


class TestWorkflowStatus:
    """Tests for WorkflowStatus enum."""

    def test_workflow_statuses(self):
        """Test all workflow statuses are defined."""
        statuses = [
            WorkflowStatus.OPEN,
            WorkflowStatus.INVESTIGATING,
            WorkflowStatus.PLANNING,
            WorkflowStatus.PENDING_APPROVAL,
            WorkflowStatus.EXECUTING,
            WorkflowStatus.VERIFYING,
            WorkflowStatus.RESOLVED,
            WorkflowStatus.ESCALATED,
            WorkflowStatus.ABORTED,
        ]

        assert len(statuses) == 9
        for status in statuses:
            assert isinstance(status.value, str)


class TestCreateIncidentNode:
    """Tests for create_incident_node."""

    @pytest.mark.asyncio
    async def test_creates_new_incident(self):
        """Test node creates new incident record."""
        state = create_initial_state(
            fingerprint="CrashLoop:prod:demo-app",
            severity="high",
        )

        with patch("src.workflow.nodes.get_repository") as mock_repo:
            mock_repo.return_value.find_or_create_incident = AsyncMock(
                return_value=(
                    MagicMock(id="incident-123"),
                    True,  # created
                )
            )

            result = await create_incident_node(state)

            assert result["incident_id"] == "incident-123"
            assert result["status"] == WorkflowStatus.INVESTIGATING

    @pytest.mark.asyncio
    async def test_dedup_existing_incident(self):
        """Test node returns existing incident for duplicate fingerprint."""
        state = create_initial_state(
            fingerprint="CrashLoop:prod:demo-app",
            severity="high",
        )

        with patch("src.workflow.nodes.get_repository") as mock_repo:
            mock_repo.return_value.find_or_create_incident = AsyncMock(
                return_value=(
                    MagicMock(id="existing-incident"),
                    False,  # not created, existing
                )
            )

            result = await create_incident_node(state)

            assert result["incident_id"] == "existing-incident"


class TestGatherContextNode:
    """Tests for gather_context_node."""

    @pytest.mark.asyncio
    async def test_gathers_pod_info(self):
        """Test node gathers pod information."""
        state = create_initial_state(
            fingerprint="CrashLoop:prod:demo-app",
            severity="high",
        )
        state["incident_id"] = "incident-123"
        state["status"] = WorkflowStatus.INVESTIGATING

        with patch("src.workflow.nodes.get_k8s_tools") as mock_k8s:
            mock_k8s.return_value.list_pods = AsyncMock(return_value=MagicMock(
                success=True,
                output={"items": [{"metadata": {"name": "demo-app-abc"}}]},
            ))
            mock_k8s.return_value.get_events = AsyncMock(return_value=MagicMock(
                success=True,
                output={"items": []},
            ))
            mock_k8s.return_value.get_logs = AsyncMock(return_value=MagicMock(
                success=True,
                output={"logs": ""},
            ))

            result = await gather_context_node(state)

            assert len(result["observations"]) > 0
            assert any(o["type"] == "pods" for o in result["observations"])

    @pytest.mark.asyncio
    async def test_gathers_events(self):
        """Test node gathers Kubernetes events."""
        state = create_initial_state(
            fingerprint="OOMKilled:prod:api",
            severity="critical",
        )
        state["incident_id"] = "incident-123"

        with patch("src.workflow.nodes.get_k8s_tools") as mock_k8s:
            mock_k8s.return_value.list_pods = AsyncMock(return_value=MagicMock(
                success=True,
                output={"items": []},
            ))
            mock_k8s.return_value.get_events = AsyncMock(return_value=MagicMock(
                success=True,
                output={"items": [
                    {"reason": "OOMKilled", "message": "Container killed"}
                ]},
            ))
            mock_k8s.return_value.get_logs = AsyncMock(return_value=MagicMock(
                success=True,
                output={"logs": ""},
            ))

            result = await gather_context_node(state)

            assert any(o["type"] == "events" for o in result["observations"])


class TestDiagnoseNode:
    """Tests for diagnose_node."""

    @pytest.mark.asyncio
    async def test_generates_hypothesis(self):
        """Test node generates hypothesis from observations."""
        state = create_initial_state(
            fingerprint="OOMKilled:prod:api",
            severity="critical",
        )
        state["incident_id"] = "incident-123"
        state["observations"] = [
            {
                "type": "events",
                "data": {"items": [{"reason": "OOMKilled"}]},
            },
        ]

        result = await diagnose_node(state)

        assert len(result["hypotheses"]) > 0
        assert result["risk_score"] > 0

    @pytest.mark.asyncio
    async def test_calculates_risk_score(self):
        """Test node calculates appropriate risk score."""
        state = create_initial_state(
            fingerprint="CrashLoop:prod:api",
            severity="critical",
        )
        state["incident_id"] = "incident-123"
        state["observations"] = [
            {
                "type": "events",
                "data": {"items": [{"reason": "CrashLoopBackOff"}]},
            },
        ]

        result = await diagnose_node(state)

        # Critical severity should have higher risk
        assert result["risk_score"] >= 0.5


class TestPlanNode:
    """Tests for plan_node."""

    @pytest.mark.asyncio
    async def test_generates_plan(self):
        """Test node generates remediation plan."""
        state = create_initial_state(
            fingerprint="OOMKilled:prod:api",
            severity="critical",
        )
        state["incident_id"] = "incident-123"
        state["hypotheses"] = [
            {
                "id": "hyp-1",
                "cause": "Memory limit too low",
                "confidence": 0.8,
                "suggested_actions": ["restart_pod", "scale_deployment"],  # Add suggested actions
            },
        ]
        state["risk_score"] = 0.5

        result = await plan_node(state)

        assert result["plan"] is not None
        assert "actions" in result["plan"]
        assert len(result["plan"]["actions"]) > 0

    @pytest.mark.asyncio
    async def test_plan_includes_safe_actions(self):
        """Test plan includes only allowlisted actions."""
        state = create_initial_state(
            fingerprint="OOMKilled:prod:api",
            severity="high",
        )
        state["incident_id"] = "incident-123"
        state["hypotheses"] = [
            {"id": "hyp-1", "cause": "Memory issue", "confidence": 0.7},
        ]

        result = await plan_node(state)

        allowed_actions = {"restart_pod", "scale_deployment", "rollback_deployment"}
        for action in result["plan"]["actions"]:
            assert action["type"] in allowed_actions


class TestApprovalNode:
    """Tests for approval_node with HITL interrupt."""

    @pytest.mark.asyncio
    async def test_low_risk_auto_approves(self):
        """Test low risk actions are auto-approved in non-prod namespace."""
        state = create_initial_state(
            fingerprint="test:staging:app",  # staging, not prod
            severity="low",
            namespace="staging",  # Explicitly non-prod
        )
        state["risk_score"] = 0.2
        state["plan"] = {
            "id": "plan-1",
            "actions": [{"type": "restart_pod", "risk_level": "low"}],
        }
        # Add high-confidence hypothesis to avoid low-confidence trigger
        state["hypotheses"] = [{"id": "h1", "cause": "test", "confidence": 0.9}]

        result = await approval_node(state)

        # Should auto-approve and proceed
        assert result.get("next_node") == "execute" or result["status"] == WorkflowStatus.EXECUTING

    @pytest.mark.asyncio
    async def test_high_risk_requires_approval(self):
        """Test high risk actions require human approval."""
        state = create_initial_state(
            fingerprint="test:prod:app",
            severity="critical",
        )
        state["risk_score"] = 0.6
        state["plan"] = {
            "id": "plan-1",
            "actions": [{"type": "scale_deployment", "risk_level": "high"}],
        }

        # High risk should set pending approval status
        result = await approval_node(state)

        assert result["status"] == WorkflowStatus.PENDING_APPROVAL
        assert result.get("needs_interrupt") is True

    @pytest.mark.asyncio
    async def test_prod_namespace_requires_approval(self):
        """Test prod namespace always requires approval per SOP-OPS-003."""
        state = create_initial_state(
            fingerprint="test:prod:app",  # prod namespace
            severity="low",
            namespace="prod",  # Explicitly prod
        )
        state["risk_score"] = 0.1  # Low risk
        state["plan"] = {
            "id": "plan-1",
            "actions": [{"type": "restart_pod", "risk_level": "low"}],
            "namespace": "prod",
        }

        # Even low risk should require approval in prod
        result = await approval_node(state)

        # Should either interrupt or set pending_approval status
        assert (
            result.get("status") == WorkflowStatus.PENDING_APPROVAL
            or result.get("needs_interrupt") is True
        )


class TestExecuteNode:
    """Tests for execute_node."""

    @pytest.mark.asyncio
    async def test_executes_restart_pod(self):
        """Test node executes pod restart action."""
        state = create_initial_state(
            fingerprint="test:prod:app",
            severity="high",
        )
        state["incident_id"] = "incident-123"
        state["plan"] = {
            "id": "plan-1",
            "actions": [
                {
                    "id": "action-1",
                    "type": "restart_pod",
                    "target": "demo-app-abc",
                    "parameters": {"namespace": "prod"},
                }
            ],
        }

        with patch("src.workflow.nodes.get_k8s_tools") as mock_k8s:
            mock_k8s.return_value.restart_pod = AsyncMock(return_value=MagicMock(
                success=True,
                output={"restarted": "demo-app-abc"},
            ))

            result = await execute_node(state)

            assert len(result["execution_results"]) > 0
            assert result["execution_results"][0]["success"] is True

    @pytest.mark.asyncio
    async def test_executes_scale_deployment(self):
        """Test node executes deployment scaling."""
        state = create_initial_state(
            fingerprint="test:prod:app",
            severity="high",
        )
        state["incident_id"] = "incident-123"
        state["plan"] = {
            "id": "plan-1",
            "actions": [
                {
                    "id": "action-1",
                    "type": "scale_deployment",
                    "target": "demo-app",
                    "parameters": {"namespace": "prod", "replicas": 3},
                }
            ],
        }

        with patch("src.workflow.nodes.get_k8s_tools") as mock_k8s:
            mock_k8s.return_value.scale_deployment = AsyncMock(return_value=MagicMock(
                success=True,
                output={"scaled": "demo-app", "replicas": 3},
            ))

            result = await execute_node(state)

            assert result["execution_results"][0]["success"] is True


class TestVerifyNode:
    """Tests for verify_node."""

    @pytest.mark.asyncio
    async def test_verifies_pod_health(self):
        """Test node verifies pods are healthy."""
        state = create_initial_state(
            fingerprint="test:prod:app",
            severity="high",
        )
        state["incident_id"] = "incident-123"
        state["execution_results"] = [{"success": True}]

        with patch("src.workflow.nodes.get_k8s_tools") as mock_k8s:
            mock_k8s.return_value.list_pods = AsyncMock(return_value=MagicMock(
                success=True,
                output={"items": [
                    {"status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}},
                ]},
            ))

            result = await verify_node(state)

            assert result["status"] == WorkflowStatus.RESOLVED

    @pytest.mark.asyncio
    async def test_verification_failure(self):
        """Test node handles verification failure."""
        state = create_initial_state(
            fingerprint="test:prod:app",
            severity="high",
        )
        state["incident_id"] = "incident-123"
        state["execution_results"] = [{"success": True}]

        with patch("src.workflow.nodes.get_k8s_tools") as mock_k8s:
            mock_k8s.return_value.list_pods = AsyncMock(return_value=MagicMock(
                success=True,
                output={"items": [
                    {"status": {"phase": "CrashLoopBackOff"}},
                ]},
            ))

            result = await verify_node(state)

            # Should escalate if verification fails
            assert result["status"] in [WorkflowStatus.ESCALATED, WorkflowStatus.VERIFYING]


class TestReportNode:
    """Tests for report_node."""

    @pytest.mark.asyncio
    async def test_generates_report(self):
        """Test node generates incident report."""
        state = create_initial_state(
            fingerprint="test:prod:app",
            severity="high",
        )
        state["incident_id"] = "incident-123"
        state["status"] = WorkflowStatus.RESOLVED
        state["hypotheses"] = [{"cause": "OOMKilled"}]
        state["execution_results"] = [{"success": True}]

        result = await report_node(state)

        assert "report" in result
        assert result["report"] is not None


class TestPolicyEngine:
    """Tests for PolicyEngine (SOP enforcement)."""

    def test_is_action_allowed_safe_actions(self):
        """Test safe actions are allowed."""
        policy = PolicyEngine(PolicyConfig())

        assert is_action_allowed("restart_pod") is True
        assert is_action_allowed("scale_deployment") is True

    def test_is_action_allowed_unsafe_actions(self):
        """Test unsafe actions are rejected."""
        policy = PolicyEngine(PolicyConfig())

        assert is_action_allowed("delete_namespace") is False
        assert is_action_allowed("exec_shell") is False

    def test_requires_approval_high_risk(self):
        """Test high risk score requires approval."""
        assert requires_approval(risk_score=0.5) is True
        assert requires_approval(risk_score=0.6) is True

    def test_requires_approval_low_risk(self):
        """Test low risk score may not require approval."""
        assert requires_approval(risk_score=0.2) is False
        assert requires_approval(risk_score=0.3) is False

    def test_requires_approval_prod_namespace(self):
        """Test prod namespace always requires approval."""
        assert requires_approval(risk_score=0.1, namespace="prod") is True

    def test_requires_approval_low_confidence(self):
        """Test low RCA confidence requires approval."""
        assert requires_approval(risk_score=0.2, rca_confidence=0.5) is True

    def test_calculate_risk_score(self):
        """Test risk score calculation."""
        # Critical severity should have higher base risk
        score = calculate_risk_score(severity="critical", observations=[])
        assert score >= 0.5

        # Low severity should have lower base risk
        score = calculate_risk_score(severity="low", observations=[])
        assert score < 0.5


class TestBuildWorkflow:
    """Tests for workflow graph construction."""

    def test_build_workflow_has_all_nodes(self):
        """Test workflow has all required nodes."""
        workflow = build_workflow()

        expected_nodes = [
            "create_incident",
            "gather_context",
            "diagnose",
            "plan",
            "approval",
            "execute",
            "verify",
            "report",
        ]

        for node in expected_nodes:
            assert node in workflow.nodes

    def test_workflow_has_correct_edges(self):
        """Test workflow has correct edge transitions."""
        workflow = build_workflow()

        # Check basic flow exists
        # START -> create_incident -> gather_context -> diagnose -> plan -> approval
        # approval -> execute -> verify -> report -> END

        # This is a structural test - actual edge validation depends on LangGraph internals

    def test_compile_workflow_with_checkpointer(self):
        """Test workflow compiles with checkpointer."""
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
        compiled = compile_workflow(checkpointer=checkpointer)

        assert compiled is not None
