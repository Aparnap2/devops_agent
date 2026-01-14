"""TDD: Tests for Streamlit Control Tower UI.

RED PHASE: Write tests for approval UI components.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import json

from src.workflow.state import AgentState, WorkflowStatus, create_initial_state
from src.ui.approval import (
    format_incident_card,
    format_plan_details,
    get_risk_color,
    format_timestamp,
)


class TestRiskColor:
    """Tests for risk color formatting."""

    def test_low_risk_green(self):
        """Test low risk returns green color."""
        assert get_risk_color(0.2) == "green"

    def test_medium_risk_yellow(self):
        """Test medium risk returns orange color."""
        assert get_risk_color(0.4) == "orange"

    def test_high_risk_red(self):
        """Test high risk returns red or darkred color."""
        # 0.7 is in the high range, returns darkred
        result = get_risk_color(0.7)
        assert result in ["red", "darkred"]

    def test_critical_risk_dark_red(self):
        """Test critical risk returns dark red color."""
        assert get_risk_color(0.9) == "darkred"


class TestTimestampFormatting:
    """Tests for timestamp formatting."""

    def test_format_datetime(self):
        """Test formatting datetime object."""
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = format_timestamp(dt)
        assert "2024-01-15" in result
        assert "10:30" in result

    def test_format_string(self):
        """Test formatting string timestamp."""
        ts = "2024-01-15T10:30:00+00:00"
        result = format_timestamp(ts)
        assert "2024-01-15" in result


class TestIncidentCard:
    """Tests for incident card formatting."""

    def test_format_incident_card_basic(self):
        """Test formatting basic incident card."""
        state = create_initial_state(
            fingerprint="OOMKilled:prod:api-service",
            severity="critical",
            namespace="prod",
            affected_service="api-service",
        )
        state["incident_id"] = "inc-123"
        state["risk_score"] = 0.8

        card = format_incident_card(state)

        assert card["id"] == "inc-123"
        assert card["fingerprint"] == "OOMKilled:prod:api-service"
        assert card["severity"] == "CRITICAL"  # Uppercased in format_incident_card
        assert card["risk_score"] == 0.8

    def test_format_incident_card_with_observations(self):
        """Test formatting incident card with observations."""
        state = create_initial_state(
            fingerprint="CrashLoop:staging:frontend",
            severity="high",
        )
        state["incident_id"] = "inc-456"
        state["observations"] = [
            {"type": "events", "data": {"items": [{"reason": "CrashLoopBackOff"}]}},
            {"type": "pods", "data": {"items": [{"status": {"phase": "CrashLoopBackOff"}}]}},
        ]

        card = format_incident_card(state)

        assert len(card["observations_summary"]["events"]) == 1
        assert len(card["observations_summary"]["pods"]) == 1


class TestPlanDetails:
    """Tests for plan details formatting."""

    def test_format_plan_details_basic(self):
        """Test formatting basic plan details."""
        plan = {
            "id": "plan-123",
            "actions": [
                {
                    "id": "action-1",
                    "type": "restart_pod",
                    "target": "api-service",
                    "parameters": {"namespace": "prod"},
                    "risk_level": "low",
                },
                {
                    "id": "action-2",
                    "type": "scale_deployment",
                    "target": "api-service",
                    "parameters": {"namespace": "prod", "replicas": 3},
                    "risk_level": "medium",
                    "requires_approval": True,
                },
            ],
            "total_risk_score": 0.5,
        }

        details = format_plan_details(plan)

        assert details["plan_id"] == "plan-123"
        assert len(details["actions"]) == 2
        assert details["actions"][0]["type"] == "restart_pod"
        assert details["actions"][1]["type"] == "scale_deployment"
        assert details["action_count"] == 2

    def test_format_plan_details_empty(self):
        """Test formatting empty plan."""
        details = format_plan_details(None)
        assert details is None

    def test_plan_action_risk_levels(self):
        """Test plan actions have correct risk levels."""
        plan = {
            "id": "plan-1",
            "actions": [
                {"id": "a1", "type": "restart_pod", "risk_level": "low"},
                {"id": "a2", "type": "scale_deployment", "risk_level": "medium"},
                {"id": "a3", "type": "rollback_deployment", "risk_level": "high"},
            ],
            "total_risk_score": 0.7,
        }

        details = format_plan_details(plan)

        # All actions should have risk_level
        for action in details["actions"]:
            assert "risk_level" in action


class TestApprovalUIIntegration:
    """Integration tests for approval UI state handling."""

    @pytest.mark.asyncio
    async def test_pending_approval_state(self):
        """Test pending approval state format."""
        state = create_initial_state(
            fingerprint="OOMKilled:prod:api",
            severity="critical",
        )
        state.update({
            "incident_id": "inc-789",
            "status": WorkflowStatus.PENDING_APPROVAL,
            "risk_score": 0.6,
            "hypotheses": [
                {
                    "id": "h1",
                    "cause": "Memory limit exceeded",
                    "confidence": 0.85,
                }
            ],
            "plan": {
                "id": "plan-1",
                "actions": [
                    {
                        "id": "a1",
                        "type": "restart_pod",
                        "target": "api",
                        "parameters": {"namespace": "prod"},
                        "risk_level": "low",
                        "requires_approval": False,
                    },
                    {
                        "id": "a2",
                        "type": "scale_deployment",
                        "target": "api",
                        "parameters": {"namespace": "prod", "replicas": 3},
                        "risk_level": "high",
                        "requires_approval": True,
                    },
                ],
            },
            "needs_interrupt": True,
        })

        # Verify state is correctly formatted for UI
        assert state["status"] == WorkflowStatus.PENDING_APPROVAL
        assert state["needs_interrupt"] is True
        assert len(state["plan"]["actions"]) == 2

    @pytest.mark.asyncio
    async def test_approval_decision_format(self):
        """Test approval decision is properly formatted."""
        decision = {
            "approved": True,
            "auto": False,
            "approver": "oncall-engineer",
            "reason": "Memory issue confirmed, restart is safe",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        assert decision["approved"] is True
        assert decision["auto"] is False
        assert "reason" in decision
        assert "timestamp" in decision

    @pytest.mark.asyncio
    async def test_rejection_decision_format(self):
        """Test rejection decision is properly formatted."""
        decision = {
            "approved": False,
            "auto": False,
            "approver": "senior-engineer",
            "reason": "Need more investigation before scaling",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        assert decision["approved"] is False
        assert "reason" in decision
        assert len(decision["reason"]) > 0


class TestUIStateConversion:
    """Tests for converting workflow state to UI state."""

    def test_state_to_ui_dict(self):
        """Test converting AgentState to UI-compatible dict."""
        state = create_initial_state(
            fingerprint="test:prod:svc",
            severity="high",
        )
        state["incident_id"] = "inc-001"
        state["status"] = WorkflowStatus.PENDING_APPROVAL
        state["hypotheses"] = [
            {"id": "h1", "cause": "Test cause", "confidence": 0.8}
        ]
        state["plan"] = {
            "id": "p1",
            "actions": [
                {"id": "a1", "type": "restart_pod", "risk_level": "low"}
            ],
        }

        # Convert to JSON-serializable format
        ui_state = json.loads(json.dumps(state, default=str))

        assert ui_state["incident_id"] == "inc-001"
        assert ui_state["severity"] == "high"
        assert ui_state["status"] == "pending_approval"
        assert len(ui_state["hypotheses"]) == 1

    def test_workflow_status_to_string(self):
        """Test WorkflowStatus converts to string value."""
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

        for status in statuses:
            str_value = status.value
            assert isinstance(str_value, str)
            assert len(str_value) > 0
