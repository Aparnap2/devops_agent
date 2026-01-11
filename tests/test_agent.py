"""Tests for the agent orchestrator."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from src.agent.orchestrator import DevOpsAgent
from src.agent.state import AgentState, create_initial_state
from src.types.state import (
    Signal,
    SignalType,
    Severity,
    IncidentStatus,
)


class TestAgentState:
    """Tests for agent state."""

    def test_create_initial_state(self):
        """Test creating initial state."""
        state = create_initial_state()

        assert state["signals"] == []
        assert state["anomalies"] == []
        assert state["current_incident"] is None
        assert state["root_causes"] == []
        assert state["remediation_plan"] is None
        assert state["execution_results"] == []
        assert state["current_step"] == "idle"
        assert state["error_message"] is None
        assert "started_at" in state
        assert "last_updated" in state


class TestDevOpsAgent:
    """Tests for the DevOps agent."""

    @pytest.fixture
    def agent(self, mock_redis_store, mock_neo4j_store, mock_vector_store, mock_execution_manager, mock_ingestion_manager):
        """Create an agent with mocked dependencies."""
        agent = DevOpsAgent(
            redis_store=mock_redis_store,
            neo4j_store=mock_neo4j_store,
            vector_store=mock_vector_store,
            execution_manager=mock_execution_manager,
            ingestion_manager=mock_ingestion_manager,
        )
        return agent

    @pytest.mark.asyncio
    async def test_anomaly_detection_from_error_log(self, agent, sample_error_signal):
        """Test detecting anomaly from error log."""
        # The agent should detect an anomaly from an error log
        result = agent._check_for_anomaly(sample_error_signal)

        assert result is not None
        assert result.severity == Severity.HIGH
        assert "error" in result.description.lower()

    @pytest.mark.asyncio
    async def test_no_anomaly_for_info_log(self, agent, sample_signal):
        """Test that info level logs don't trigger anomaly."""
        sample_signal.raw_content["level"] = "INFO"
        result = agent._check_for_anomaly(sample_signal)

        # INFO logs should not trigger anomaly
        assert result is None

    @pytest.mark.asyncio
    async def test_infer_root_cause(self, agent, sample_error_signal):
        """Test root cause inference."""
        root_cause = agent._infer_root_cause(
            anomaly=MagicMock(),
            signal=sample_error_signal,
        )

        assert root_cause is not None
        assert len(root_cause) > 0

    @pytest.mark.asyncio
    async def test_generate_remediation_actions_restart(self, agent):
        """Test generating restart action for instability."""
        root_cause = MagicMock()
        root_cause.id = "rca-1"
        root_cause.probable_cause = "Container instability - frequent restarts detected"
        root_cause.affected_services = ["api-service"]

        actions = agent._generate_remediation_actions(root_cause)

        assert len(actions) > 0
        action_types = [a.type for a in actions]
        assert "restart_deployment" in action_types

    @pytest.mark.asyncio
    async def test_generate_remediation_actions_memory(self, agent):
        """Test generating scale action for memory issues."""
        root_cause = MagicMock()
        root_cause.id = "rca-1"
        root_cause.probable_cause = "Resource exhaustion - memory pressure"
        root_cause.affected_services = ["api-service"]

        actions = agent._generate_remediation_actions(root_cause)

        action_types = [a.type for a in actions]
        assert "scale_deployment" in action_types

    @pytest.mark.asyncio
    async def test_should_escalate_critical(self, agent):
        """Test escalation for critical anomalies."""
        state = AgentState(
            signals=[],
            anomalies=[
                MagicMock(severity=Severity.CRITICAL),
            ],
            current_incident=None,
            root_causes=[],
            remediation_plan=None,
            execution_results=[],
            feedback=[],
            current_step="detect_anomalies",
            error_message=None,
            started_at=datetime.utcnow(),
            last_updated=datetime.utcnow(),
        )

        result = agent._should_escalate(state)
        assert result == "escalate"

    @pytest.mark.asyncio
    async def test_should_continue_low_severity(self, agent):
        """Test continuing for low severity anomalies."""
        state = AgentState(
            signals=[],
            anomalies=[
                MagicMock(severity=Severity.LOW),
            ],
            current_incident=None,
            root_causes=[],
            remediation_plan=None,
            execution_results=[],
            feedback=[],
            current_step="detect_anomalies",
            error_message=None,
            started_at=datetime.utcnow(),
            last_updated=datetime.utcnow(),
        )

        result = agent._should_escalate(state)
        assert result == "continue"

    @pytest.mark.asyncio
    async def test_should_continue_no_anomalies(self, agent):
        """Test continuing when no anomalies."""
        state = AgentState(
            signals=[],
            anomalies=[],
            current_incident=None,
            root_causes=[],
            remediation_plan=None,
            execution_results=[],
            feedback=[],
            current_step="detect_anomalies",
            error_message=None,
            started_at=datetime.utcnow(),
            last_updated=datetime.utcnow(),
        )

        result = agent._should_escalate(state)
        assert result == "continue"


class TestIngestSignalsNode:
    """Tests for the ingest signals node."""

    @pytest.mark.asyncio
    async def test_ingest_signals_node(self, mock_ingestion_manager):
        """Test the ingest signals node."""
        mock_ingestion_manager.fetch_all_signals = AsyncMock(return_value=[])

        agent = DevOpsAgent(ingestion_manager=mock_ingestion_manager)
        agent._initialized = True

        initial_state = create_initial_state()
        result = await agent._ingest_signals_node(initial_state)

        assert result["signals"] == []
        assert result["current_step"] == "ingest_signals"
        mock_ingestion_manager.fetch_all_signals.assert_called_once()
