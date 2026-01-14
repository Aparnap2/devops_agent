"""Integration tests for Chaos Mesh fault injection scenarios.

These tests verify the agent can handle incidents caused by Chaos Mesh faults.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.workflow.state import AgentState, WorkflowStatus, create_initial_state
from src.workflow.nodes import (
    gather_context_node,
    diagnose_node,
    plan_node,
)
from src.workflow.policy import calculate_risk_score


class TestChaosMeshOOMScenario:
    """Test handling of OOMKilled incidents (simulating Chaos Mesh pod-kill)."""

    @pytest.mark.asyncio
    async def test_diagnose_oomkilled_from_events(self):
        """Test that OOMKilled events are properly diagnosed."""
        state = create_initial_state(
            fingerprint="OOMKilled:prod:demo-app",
            severity="critical",
            namespace="prod",
            affected_service="demo-app",
        )
        state["incident_id"] = "inc-001"
        state["observations"] = [
            {
                "type": "events",
                "data": {
                    "items": [
                        {
                            "reason": "OOMKilled",
                            "message": "Container demo-app-abc exceeded memory limit",
                            "count": 5,
                        }
                    ]
                },
            },
            {
                "type": "pods",
                "data": {
                    "items": [
                        {
                            "metadata": {"name": "demo-app-abc"},
                            "status": {"phase": "Running", "reason": "OOMKilled"},
                        }
                    ]
                },
            },
        ]

        result = await diagnose_node(state)

        # Should generate OOM hypothesis
        oom_hypotheses = [h for h in result["hypotheses"] if "memory" in h["cause"].lower()]
        assert len(oom_hypotheses) > 0
        assert oom_hypotheses[0]["confidence"] >= 0.9

        # Should suggest restart and scale
        suggested = oom_hypotheses[0]["suggested_actions"]
        assert "restart_pod" in suggested
        assert "scale_deployment" in suggested

    @pytest.mark.asyncio
    async def test_plan_for_oom_recovery(self):
        """Test plan generation for OOM recovery."""
        state = create_initial_state(
            fingerprint="OOMKilled:prod:demo-app",
            severity="critical",
            namespace="prod",
            affected_service="demo-app",
        )
        state["incident_id"] = "inc-001"
        state["risk_score"] = 0.75
        state["hypotheses"] = [
            {
                "id": "h1",
                "cause": "Memory limit exceeded - container was OOMKilled",
                "confidence": 0.9,
                "suggested_actions": ["restart_pod", "scale_deployment"],
            }
        ]

        result = await plan_node(state)

        assert result["plan"] is not None
        assert len(result["plan"]["actions"]) >= 1

        # Should have restart action
        restart_actions = [a for a in result["plan"]["actions"] if a["type"] == "restart_pod"]
        assert len(restart_actions) == 1

        # Should have scale action
        scale_actions = [a for a in result["plan"]["actions"] if a["type"] == "scale_deployment"]
        assert len(scale_actions) == 1


class TestChaosMeshNetworkScenario:
    """Test handling of network delay/fault incidents."""

    @pytest.mark.asyncio
    async def test_diagnose_network_delay(self):
        """Test diagnosis of network delay symptoms."""
        state = create_initial_state(
            fingerprint="HighLatency:prod:api-gateway",
            severity="high",
            namespace="prod",
            affected_service="api-gateway",
        )
        state["incident_id"] = "inc-002"
        state["observations"] = [
            {
                "type": "events",
                "data": {
                    "items": [
                        {
                            "reason": "Unhealthy",
                            "message": "Health check failed 3 times",
                        }
                    ]
                },
            },
            {
                "type": "pods",
                "data": {
                    "items": [
                        {
                            "metadata": {"name": "api-gateway-xyz"},
                            "status": {"phase": "Running"},
                        }
                    ]
                },
            },
        ]

        result = await diagnose_node(state)

        # Should generate at least one hypothesis
        assert len(result["hypotheses"]) > 0
        assert result["risk_score"] >= 0.5


class TestChaosMeshPodKillScenario:
    """Test handling of pod killed incidents."""

    @pytest.mark.asyncio
    async def test_diagnose_pod_killed(self):
        """Test diagnosis of pod killed by Chaos Mesh."""
        state = create_initial_state(
            fingerprint="PodKilled:staging:frontend",
            severity="high",
            namespace="staging",
            affected_service="frontend",
        )
        state["incident_id"] = "inc-003"
        state["observations"] = [
            {
                "type": "events",
                "data": {
                    "items": [
                        {
                            "reason": "Killing",
                            "message": "Pod killed by Chaos Mesh stress-chaos",
                            "count": 2,
                        }
                    ]
                },
            },
            {
                "type": "pods",
                "data": {
                    "items": [
                        {
                            "metadata": {"name": "frontend-abc"},
                            "status": {"phase": "Pending", "reason": "Unscheduled"},
                        }
                    ]
                },
            },
        ]

        result = await diagnose_node(state)

        # Should generate hypothesis for unhealthy pod
        pod_hypotheses = [
            h for h in result["hypotheses"]
            if "unhealthy" in h["cause"].lower() or "killed" in h["cause"].lower()
        ]
        assert len(pod_hypotheses) > 0


class TestRiskCalculationChaosScenarios:
    """Test risk calculation for various chaos scenarios."""

    def test_oomkilled_high_risk(self):
        """Test OOMKilled in prod gets high risk score."""
        score = calculate_risk_score(
            severity="critical",
            observations=[
                {"type": "events", "data": {"items": [{"reason": "OOMKilled"}]}},
                {"type": "pods", "data": {"items": [{}, {}, {}, {}]}},  # 4 pods
            ],
            namespace="prod",
        )
        assert score >= 0.7

    def test_crashloop_medium_risk(self):
        """Test CrashLoopBackOff gets medium risk."""
        score = calculate_risk_score(
            severity="high",
            observations=[
                {"type": "events", "data": {"items": [{"reason": "CrashLoopBackOff"}]}},
            ],
            namespace="staging",
        )
        assert score >= 0.5
        assert score < 0.8

    def test_multiple_pods_increase_risk(self):
        """Test multiple affected pods increase risk."""
        score_single = calculate_risk_score(
            severity="high",
            observations=[
                {"type": "pods", "data": {"items": [{"status": "Running"}]}},
            ],
        )

        score_multiple = calculate_risk_score(
            severity="high",
            observations=[
                {"type": "pods", "data": {"items": [{}, {}, {}, {}, {}]}},  # 5 pods
            ],
        )

        assert score_multiple > score_single


class TestChaosRecoveryVerification:
    """Test verification of recovery after chaos remediation."""

    @pytest.mark.asyncio
    async def test_verify_pods_restarted(self):
        """Test verification detects pods are back to Running."""
        state = create_initial_state(
            fingerprint="OOMKilled:prod:demo-app",
            severity="critical",
            namespace="prod",
            affected_service="demo-app",
        )
        state["incident_id"] = "inc-001"
        state["execution_results"] = [{"success": True, "type": "restart_pod"}]

        # Mock K8s tools to return healthy pods
        with patch("src.workflow.nodes.get_k8s_tools") as mock_k8s:
            mock_k8s.return_value.list_pods = AsyncMock(return_value=MagicMock(
                success=True,
                output={
                    "items": [
                        {
                            "metadata": {"name": "demo-app-new-1"},
                            "status": {
                                "phase": "Running",
                                "conditions": [{"type": "Ready", "status": "True"}],
                            },
                        },
                        {
                            "metadata": {"name": "demo-app-new-2"},
                            "status": {
                                "phase": "Running",
                                "conditions": [{"type": "Ready", "status": "True"}],
                            },
                        },
                    ]
                },
            ))

            from src.workflow.nodes import verify_node
            result = await verify_node(state)

            # Should resolve when pods are healthy
            assert result["status"] == WorkflowStatus.RESOLVED

    @pytest.mark.asyncio
    async def test_verify_pods_still_unhealthy(self):
        """Test verification handles continued unhealthiness."""
        state = create_initial_state(
            fingerprint="OOMKilled:prod:demo-app",
            severity="critical",
            namespace="prod",
            affected_service="demo-app",
        )
        state["incident_id"] = "inc-001"
        state["execution_results"] = [{"success": True, "type": "restart_pod"}]

        # Mock K8s tools to return unhealthy pods
        with patch("src.workflow.nodes.get_k8s_tools") as mock_k8s:
            mock_k8s.return_value.list_pods = AsyncMock(return_value=MagicMock(
                success=True,
                output={
                    "items": [
                        {
                            "metadata": {"name": "demo-app-failing"},
                            "status": {
                                "phase": "CrashLoopBackOff",
                                "conditions": [],
                            },
                        },
                    ]
                },
            ))

            from src.workflow.nodes import verify_node
            result = await verify_node(state)

            # Should not resolve when pods are unhealthy
            assert result["status"] != WorkflowStatus.RESOLVED


class TestChaosMeshIntegrationWorkflow:
    """End-to-end workflow tests for Chaos Mesh scenarios."""

    @pytest.mark.asyncio
    async def test_full_oom_recovery_workflow(self):
        """Test complete workflow for OOM recovery."""
        # Initial state
        state = create_initial_state(
            fingerprint="OOMKilled:staging:demo-app",
            severity="high",
            namespace="staging",
            affected_service="demo-app",
        )

        # Step 1: Diagnose
        state["incident_id"] = "inc-001"
        state["observations"] = [
            {
                "type": "events",
                "data": {"items": [{"reason": "OOMKilled"}]},
            },
            {
                "type": "pods",
                "data": {"items": [{"status": {"phase": "Running"}}]},
            },
        ]

        diagnosed = await diagnose_node(state)
        assert len(diagnosed["hypotheses"]) > 0
        assert diagnosed["risk_score"] >= 0.5

        # Step 2: Plan
        planned = await plan_node(diagnosed)
        assert planned["plan"] is not None
        assert len(planned["plan"]["actions"]) > 0

        # Verify plan was created (approval depends on risk score)
        assert planned["plan"]["actions"] is not None
        assert len(planned["plan"]["actions"]) > 0

        # Note: auto_approvable depends on risk score (OOMKilled = high risk)
        # Check the logic in nodes.py: auto_approvable = risk_score < 0.4 AND namespace not prod

    @pytest.mark.asyncio
    async def test_prod_oom_requires_approval(self):
        """Test OOM in prod requires human approval."""
        state = create_initial_state(
            fingerprint="OOMKilled:prod:demo-app",
            severity="critical",
            namespace="prod",
            affected_service="demo-app",
        )
        state["incident_id"] = "inc-002"
        state["observations"] = [
            {
                "type": "events",
                "data": {"items": [{"reason": "OOMKilled"}]},
            },
        ]
        state["risk_score"] = 0.7  # High risk

        from src.workflow.nodes import diagnose_node, plan_node, approval_node

        diagnosed = await diagnose_node(state)
        planned = await plan_node(diagnosed)

        # Approval check
        approved = await approval_node(planned)

        # Prod + high risk = requires approval
        assert approved["status"] == WorkflowStatus.PENDING_APPROVAL
        assert approved["needs_interrupt"] is True
