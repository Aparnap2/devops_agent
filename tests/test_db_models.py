"""TDD: Tests for database models and incident store.

RED PHASE: Write tests first, then implement to make them pass.
"""

import pytest
from datetime import datetime, timezone
from uuid import UUID

from src.db.models import (
    IncidentStatus,
    Severity,
    IncidentCreate,
    Incident,
    TimelineEvent,
    TimelineEventType,
    ToolCall,
    Hypothesis,
    RemediationPlan,
    RemediationAction,
    ActionType,
    RiskLevel,
    Approval,
    ApprovalStatus,
    Verification,
    VerificationType,
)


class TestIncidentModels:
    """Tests for Incident Pydantic models."""

    def test_incident_create_minimal(self):
        """Test creating an incident with minimal fields."""
        incident = IncidentCreate(
            title="Pod CrashLoopBackOff",
            severity=Severity.HIGH,
            fingerprint="CrashLoop:prod:demo-app",
        )

        assert incident.title == "Pod CrashLoopBackOff"
        assert incident.severity == Severity.HIGH
        assert incident.fingerprint == "CrashLoop:prod:demo-app"
        assert incident.description is None
        assert incident.namespace is None

    def test_incident_create_full(self):
        """Test creating an incident with all fields."""
        incident = IncidentCreate(
            title="OOMKilled in api-service",
            description="Container was killed due to memory exhaustion",
            severity=Severity.CRITICAL,
            fingerprint="OOMKilled:prod:api-service",
            namespace="prod",
            affected_service="api-service",
            alert_labels={"alertname": "ContainerOOMKilled", "pod": "api-service-abc123"},
        )

        assert incident.title == "OOMKilled in api-service"
        assert incident.description == "Container was killed due to memory exhaustion"
        assert incident.namespace == "prod"
        assert incident.affected_service == "api-service"
        assert incident.alert_labels["alertname"] == "ContainerOOMKilled"

    def test_incident_status_enum(self):
        """Test all incident statuses are valid."""
        statuses = [
            IncidentStatus.OPEN,
            IncidentStatus.INVESTIGATING,
            IncidentStatus.PLANNING,
            IncidentStatus.PENDING_APPROVAL,
            IncidentStatus.EXECUTING,
            IncidentStatus.VERIFYING,
            IncidentStatus.RESOLVED,
            IncidentStatus.ESCALATED,
            IncidentStatus.ABORTED,
        ]

        for status in statuses:
            assert isinstance(status.value, str)

    def test_severity_ordering(self):
        """Test severity levels have correct ordering."""
        assert Severity.LOW.value == "low"
        assert Severity.MEDIUM.value == "medium"
        assert Severity.HIGH.value == "high"
        assert Severity.CRITICAL.value == "critical"

    def test_incident_with_defaults(self):
        """Test Incident model has correct defaults."""
        incident = Incident(
            id="123e4567-e89b-12d3-a456-426614174000",
            title="Test Incident",
            severity=Severity.MEDIUM,
            fingerprint="test:fingerprint",
            status=IncidentStatus.OPEN,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        assert incident.status == IncidentStatus.OPEN
        assert incident.risk_score == 0.0
        assert incident.resolved_at is None


class TestTimelineModels:
    """Tests for Timeline event models."""

    def test_timeline_event_types(self):
        """Test all timeline event types are defined."""
        event_types = [
            TimelineEventType.CREATED,
            TimelineEventType.STATUS_CHANGED,
            TimelineEventType.OBSERVATION,
            TimelineEventType.HYPOTHESIS,
            TimelineEventType.PLAN_CREATED,
            TimelineEventType.APPROVAL_REQUESTED,
            TimelineEventType.APPROVED,
            TimelineEventType.REJECTED,
            TimelineEventType.ACTION_STARTED,
            TimelineEventType.ACTION_COMPLETED,
            TimelineEventType.ACTION_FAILED,
            TimelineEventType.RESOLVED,
            TimelineEventType.ESCALATED,
        ]

        assert len(event_types) >= 10

    def test_timeline_event_creation(self):
        """Test creating a timeline event."""
        event = TimelineEvent(
            id="123e4567-e89b-12d3-a456-426614174001",
            incident_id="123e4567-e89b-12d3-a456-426614174000",
            event_type=TimelineEventType.STATUS_CHANGED,
            description="Status changed from open to investigating",
            metadata={"old_status": "open", "new_status": "investigating"},
            actor="agent",
            created_at=datetime.now(timezone.utc),
        )

        assert event.event_type == TimelineEventType.STATUS_CHANGED
        assert event.actor == "agent"
        assert event.metadata["old_status"] == "open"


class TestToolCallModels:
    """Tests for ToolCall audit models."""

    def test_tool_call_creation(self):
        """Test creating a tool call record."""
        tool_call = ToolCall(
            id="123e4567-e89b-12d3-a456-426614174002",
            incident_id="123e4567-e89b-12d3-a456-426614174000",
            tool_name="kubectl_get_pods",
            input_params={"namespace": "prod", "label_selector": "app=demo-app"},
            output_summary="Found 2 pods: demo-app-abc, demo-app-xyz",
            duration_ms=150,
            success=True,
            created_at=datetime.now(timezone.utc),
        )

        assert tool_call.tool_name == "kubectl_get_pods"
        assert tool_call.success is True
        assert tool_call.duration_ms == 150

    def test_tool_call_failure(self):
        """Test tool call with failure."""
        tool_call = ToolCall(
            id="123e4567-e89b-12d3-a456-426614174003",
            incident_id="123e4567-e89b-12d3-a456-426614174000",
            tool_name="kubectl_delete_pod",
            input_params={"name": "nonexistent-pod", "namespace": "prod"},
            success=False,
            error_message="Pod not found",
            duration_ms=50,
            created_at=datetime.now(timezone.utc),
        )

        assert tool_call.success is False
        assert tool_call.error_message == "Pod not found"


class TestHypothesisModels:
    """Tests for Hypothesis (root cause) models."""

    def test_hypothesis_creation(self):
        """Test creating a hypothesis."""
        hypothesis = Hypothesis(
            id="123e4567-e89b-12d3-a456-426614174004",
            incident_id="123e4567-e89b-12d3-a456-426614174000",
            probable_cause="Memory limit too low for workload",
            confidence=0.85,
            evidence=[
                {"type": "event", "data": "OOMKilled detected"},
                {"type": "metric", "data": "Memory usage at 98%"},
            ],
            affected_components=["api-service", "database-connection-pool"],
            is_primary=True,
            created_at=datetime.now(timezone.utc),
        )

        assert hypothesis.probable_cause == "Memory limit too low for workload"
        assert hypothesis.confidence == 0.85
        assert hypothesis.is_primary is True
        assert len(hypothesis.evidence) == 2

    def test_hypothesis_confidence_validation(self):
        """Test hypothesis confidence must be between 0 and 1."""
        with pytest.raises(ValueError):
            Hypothesis(
                id="123e4567-e89b-12d3-a456-426614174005",
                incident_id="123e4567-e89b-12d3-a456-426614174000",
                probable_cause="Invalid hypothesis",
                confidence=1.5,  # Invalid: > 1
                created_at=datetime.now(timezone.utc),
            )


class TestRemediationModels:
    """Tests for Remediation plan and action models."""

    def test_action_types(self):
        """Test all action types are defined."""
        action_types = [
            ActionType.RESTART_POD,
            ActionType.SCALE_DEPLOYMENT,
            ActionType.ROLLBACK_DEPLOYMENT,
            ActionType.DELETE_POD,
            ActionType.ESCALATE,
        ]

        for action_type in action_types:
            assert isinstance(action_type.value, str)

    def test_risk_levels(self):
        """Test risk levels are defined correctly."""
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.CRITICAL.value == "critical"

    def test_remediation_action_creation(self):
        """Test creating a remediation action."""
        action = RemediationAction(
            id="123e4567-e89b-12d3-a456-426614174006",
            plan_id="123e4567-e89b-12d3-a456-426614174010",
            sequence_order=1,
            action_type=ActionType.RESTART_POD,
            target="demo-app-abc123",
            parameters={"namespace": "prod"},
            risk_level=RiskLevel.LOW,
            estimated_impact="Brief pod restart, handled by ReplicaSet",
            requires_approval=False,
        )

        assert action.action_type == ActionType.RESTART_POD
        assert action.risk_level == RiskLevel.LOW
        assert action.requires_approval is False

    def test_remediation_plan_creation(self):
        """Test creating a remediation plan."""
        plan = RemediationPlan(
            id="123e4567-e89b-12d3-a456-426614174010",
            incident_id="123e4567-e89b-12d3-a456-426614174000",
            total_risk_score=0.3,
            estimated_duration_seconds=60,
            auto_approvable=True,
            status="pending",
            created_at=datetime.now(timezone.utc),
        )

        assert plan.total_risk_score == 0.3
        assert plan.auto_approvable is True
        assert plan.status == "pending"

    def test_high_risk_action_requires_approval(self):
        """Test that high risk actions require approval by default."""
        action = RemediationAction(
            id="123e4567-e89b-12d3-a456-426614174007",
            plan_id="123e4567-e89b-12d3-a456-426614174010",
            sequence_order=1,
            action_type=ActionType.SCALE_DEPLOYMENT,
            target="api-service",
            parameters={"namespace": "prod", "replicas": 10},
            risk_level=RiskLevel.HIGH,
            requires_approval=True,  # Required for high risk
        )

        assert action.requires_approval is True


class TestApprovalModels:
    """Tests for Approval (HITL) models."""

    def test_approval_statuses(self):
        """Test approval status enum."""
        statuses = [
            ApprovalStatus.PENDING,
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.AUTO_APPROVED,
            ApprovalStatus.EXPIRED,
        ]

        for status in statuses:
            assert isinstance(status.value, str)

    def test_approval_creation(self):
        """Test creating an approval request."""
        approval = Approval(
            id="123e4567-e89b-12d3-a456-426614174011",
            incident_id="123e4567-e89b-12d3-a456-426614174000",
            plan_id="123e4567-e89b-12d3-a456-426614174010",
            action_summary="Restart pod demo-app-abc123 in prod namespace",
            risk_score=0.3,
            status=ApprovalStatus.PENDING,
            auto_approve_eligible=True,
            created_at=datetime.now(timezone.utc),
        )

        assert approval.status == ApprovalStatus.PENDING
        assert approval.auto_approve_eligible is True
        assert approval.approver is None
        assert approval.decided_at is None

    def test_approval_decision(self):
        """Test approval with decision recorded."""
        now = datetime.now(timezone.utc)
        approval = Approval(
            id="123e4567-e89b-12d3-a456-426614174012",
            incident_id="123e4567-e89b-12d3-a456-426614174000",
            plan_id="123e4567-e89b-12d3-a456-426614174010",
            action_summary="Scale deployment to 5 replicas",
            risk_score=0.5,
            status=ApprovalStatus.APPROVED,
            approver="john.doe@example.com",
            reason="Approved based on high CPU usage",
            decided_at=now,
            created_at=now,
        )

        assert approval.status == ApprovalStatus.APPROVED
        assert approval.approver == "john.doe@example.com"
        assert approval.decided_at is not None


class TestVerificationModels:
    """Tests for Verification models."""

    def test_verification_types(self):
        """Test verification check types."""
        types = [
            VerificationType.POD_HEALTH,
            VerificationType.DEPLOYMENT_STATUS,
            VerificationType.ALERT_CLEARED,
            VerificationType.ENDPOINT_HEALTH,
            VerificationType.METRICS_NORMAL,
        ]

        for vtype in types:
            assert isinstance(vtype.value, str)

    def test_verification_passed(self):
        """Test successful verification."""
        verification = Verification(
            id="123e4567-e89b-12d3-a456-426614174013",
            incident_id="123e4567-e89b-12d3-a456-426614174000",
            check_type=VerificationType.POD_HEALTH,
            target="demo-app",
            expected_state="Running",
            actual_state="Running",
            passed=True,
            details={"ready_replicas": 2, "total_replicas": 2},
            created_at=datetime.now(timezone.utc),
        )

        assert verification.passed is True
        assert verification.actual_state == "Running"

    def test_verification_failed(self):
        """Test failed verification."""
        verification = Verification(
            id="123e4567-e89b-12d3-a456-426614174014",
            incident_id="123e4567-e89b-12d3-a456-426614174000",
            check_type=VerificationType.ALERT_CLEARED,
            target="PodCrashLooping",
            expected_state="inactive",
            actual_state="firing",
            passed=False,
            details={"alert_count": 1},
            created_at=datetime.now(timezone.utc),
        )

        assert verification.passed is False
        assert verification.actual_state == "firing"
