"""Tests for core types."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.types.state import (
    Signal,
    SignalType,
    Severity,
    IncidentStatus,
    Anomaly,
    RootCause,
    RemediationAction,
    RemediationPlan,
    Incident,
    ExecutionResult,
    Feedback,
)


class TestSignal:
    """Tests for Signal model."""

    def test_create_signal(self, sample_signal):
        """Test creating a signal."""
        assert sample_signal.id == "test-signal-001"
        assert sample_signal.type == SignalType.LOG
        assert sample_signal.source == "test"
        assert sample_signal.service == "test-service"
        assert sample_signal.raw_content["message"] == "Connection failed"

    def test_signal_with_all_fields(self):
        """Test creating a signal with all fields."""
        signal = Signal(
            id="test-signal",
            type=SignalType.METRIC,
            timestamp=datetime.utcnow(),
            source="prometheus",
            service="api-service",
            metadata={"key": "value"},
            raw_content={"metric": "value"},
        )
        assert signal.metadata == {"key": "value"}
        assert signal.raw_content == {"metric": "value"}

    def test_signal_type_enum(self):
        """Test signal type enum values."""
        assert SignalType.LOG.value == "log"
        assert SignalType.METRIC.value == "metric"
        assert SignalType.TRACE.value == "trace"
        assert SignalType.CI_CD_EVENT.value == "ci_cd_event"
        assert SignalType.ALERT.value == "alert"


class TestAnomaly:
    """Tests for Anomaly model."""

    def test_create_anomaly(self, sample_anomaly):
        """Test creating an anomaly."""
        assert sample_anomaly.id == "test-anomaly-001"
        assert sample_anomaly.severity == Severity.HIGH
        assert sample_anomaly.confidence == 0.85

    def test_anomaly_confidence_range(self):
        """Test anomaly confidence must be between 0 and 1."""
        with pytest.raises(ValidationError):
            Anomaly(
                id="test",
                signal_id="signal-1",
                severity=Severity.LOW,
                confidence=1.5,  # Invalid
                description="Test",
            )

        with pytest.raises(ValidationError):
            Anomaly(
                id="test",
                signal_id="signal-1",
                severity=Severity.LOW,
                confidence=-0.1,  # Invalid
                description="Test",
            )

    def test_severity_enum(self):
        """Test severity enum values."""
        assert Severity.CRITICAL.value == "critical"
        assert Severity.HIGH.value == "high"
        assert Severity.MEDIUM.value == "medium"
        assert Severity.LOW.value == "low"
        assert Severity.INFO.value == "info"


class TestRootCause:
    """Tests for RootCause model."""

    def test_create_root_cause(self, sample_root_cause):
        """Test creating a root cause."""
        assert sample_root_cause.id == "test-rca-001"
        assert sample_root_cause.confidence == 0.9
        assert len(sample_root_cause.affected_services) == 2
        assert "api-service" in sample_root_cause.affected_services


class TestRemediationAction:
    """Tests for RemediationAction model."""

    def test_create_action(self, sample_remediation_action):
        """Test creating a remediation action."""
        assert sample_remediation_action.type == "restart_deployment"
        assert sample_remediation_action.risk_level == "medium"
        assert sample_remediation_action.requires_approval is True

    def test_action_defaults(self):
        """Test action default values."""
        action = RemediationAction(
            id="test",
            type="restart_pod",
            target="pod-1",
            risk_level="low",
        )
        assert action.parameters == {}
        assert action.estimated_impact == "unknown"


class TestRemediationPlan:
    """Tests for RemediationPlan model."""

    def test_create_plan(self, sample_remediation_plan):
        """Test creating a remediation plan."""
        assert sample_remediation_plan.id == "test-plan-001"
        assert len(sample_remediation_plan.actions) == 1
        assert sample_remediation_plan.auto_approvable is False

    def test_plan_with_no_actions(self):
        """Test plan with no actions."""
        plan = RemediationPlan(
            id="test",
            incident_id="incident-1",
        )
        assert plan.actions == []
        # Empty plans default to auto_approvable=False since no actions means
        # there's nothing to approve (the model defaults to False)


class TestIncident:
    """Tests for Incident model."""

    def test_create_incident(self, sample_incident):
        """Test creating an incident."""
        assert sample_incident.id == "test-incident-001"
        assert sample_incident.status == IncidentStatus.DETECTED
        assert sample_incident.severity == Severity.HIGH

    def test_incident_status_enum(self):
        """Test incident status enum values."""
        assert IncidentStatus.DETECTED.value == "detected"
        assert IncidentStatus.DIAGNOSING.value == "diagnosing"
        assert IncidentStatus.REMEDIATING.value == "remediating"
        assert IncidentStatus.RESOLVED.value == "resolved"
        assert IncidentStatus.ESCALATED.value == "escalated"


class TestExecutionResult:
    """Tests for ExecutionResult model."""

    def test_create_result_success(self):
        """Test creating a successful execution result."""
        result = ExecutionResult(
            action_id="action-1",
            success=True,
            output={"restarted": True},
        )
        assert result.success is True
        assert result.error_message is None

    def test_create_result_failure(self):
        """Test creating a failed execution result."""
        result = ExecutionResult(
            action_id="action-1",
            success=False,
            error_message="Pod not found",
        )
        assert result.success is False
        assert result.error_message == "Pod not found"
