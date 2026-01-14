"""Pydantic models for SRE Agent incident store.

Implements typed interfaces as specified in PRD Section 5.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class Severity(str, Enum):
    """Incident severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, Enum):
    """Incident lifecycle states per PRD workflow."""

    OPEN = "open"
    INVESTIGATING = "investigating"
    PLANNING = "planning"
    PENDING_APPROVAL = "pending_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    ABORTED = "aborted"


class TimelineEventType(str, Enum):
    """Timeline event types for audit trail."""

    CREATED = "created"
    STATUS_CHANGED = "status_changed"
    OBSERVATION = "observation"
    HYPOTHESIS = "hypothesis"
    PLAN_CREATED = "plan_created"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTION_STARTED = "action_started"
    ACTION_COMPLETED = "action_completed"
    ACTION_FAILED = "action_failed"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_PASSED = "verification_passed"
    VERIFICATION_FAILED = "verification_failed"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    ABORTED = "aborted"
    COMMENT = "comment"


class ActionType(str, Enum):
    """Allowlisted remediation action types per SOP-OPS-002."""

    RESTART_POD = "restart_pod"
    SCALE_DEPLOYMENT = "scale_deployment"
    ROLLBACK_DEPLOYMENT = "rollback_deployment"
    DELETE_POD = "delete_pod"
    DRAIN_NODE = "drain_node"
    CORDON_NODE = "cordon_node"
    PATCH_RESOURCE = "patch_resource"
    ESCALATE = "escalate"
    NOTIFY = "notify"


class RiskLevel(str, Enum):
    """Risk levels for remediation actions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalStatus(str, Enum):
    """Approval request statuses."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"
    EXPIRED = "expired"


class VerificationType(str, Enum):
    """Verification check types per SOP-OPS-004."""

    POD_HEALTH = "pod_health"
    DEPLOYMENT_STATUS = "deployment_status"
    ALERT_CLEARED = "alert_cleared"
    ENDPOINT_HEALTH = "endpoint_health"
    METRICS_NORMAL = "metrics_normal"
    LOGS_CLEAN = "logs_clean"


# =============================================================================
# INCIDENT MODELS
# =============================================================================


class IncidentCreate(BaseModel):
    """Model for creating a new incident."""

    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    severity: Severity
    fingerprint: str = Field(..., min_length=1, max_length=255)
    namespace: Optional[str] = None
    affected_service: Optional[str] = None
    alert_labels: dict[str, Any] = Field(default_factory=dict)


class Incident(BaseModel):
    """Full incident model with all fields."""

    id: str
    title: str
    description: Optional[str] = None
    severity: Severity
    status: IncidentStatus = IncidentStatus.OPEN
    fingerprint: str
    namespace: Optional[str] = None
    affected_service: Optional[str] = None
    alert_labels: dict[str, Any] = Field(default_factory=dict)
    risk_score: float = 0.0
    thread_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# =============================================================================
# TIMELINE MODELS
# =============================================================================


class TimelineEvent(BaseModel):
    """Timeline event for incident audit trail."""

    id: str
    incident_id: str
    event_type: TimelineEventType
    description: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    actor: str = "agent"
    created_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# TOOL CALL MODELS
# =============================================================================


class ToolCall(BaseModel):
    """Audit record for tool invocations."""

    id: str
    incident_id: Optional[str] = None
    tool_name: str
    input_params: dict[str, Any]
    output_summary: Optional[str] = None
    full_output: Optional[dict[str, Any]] = None
    duration_ms: int = 0
    success: bool = False
    error_message: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# HYPOTHESIS MODELS
# =============================================================================


class Hypothesis(BaseModel):
    """Root cause hypothesis model."""

    id: str
    incident_id: str
    probable_cause: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    affected_components: list[str] = Field(default_factory=list)
    is_primary: bool = False
    created_at: datetime

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Ensure confidence is between 0 and 1."""
        if v < 0 or v > 1:
            raise ValueError("Confidence must be between 0 and 1")
        return v

    model_config = {"from_attributes": True}


# =============================================================================
# REMEDIATION MODELS
# =============================================================================


class RemediationAction(BaseModel):
    """Individual remediation action."""

    id: str
    plan_id: str
    sequence_order: int
    action_type: ActionType
    target: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel
    estimated_impact: Optional[str] = None
    requires_approval: bool = True
    status: str = "pending"
    result: Optional[dict[str, Any]] = None
    executed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class RemediationPlan(BaseModel):
    """Remediation plan containing ordered actions."""

    id: str
    incident_id: str
    hypothesis_id: Optional[str] = None
    total_risk_score: float = Field(..., ge=0.0, le=1.0)
    estimated_duration_seconds: Optional[int] = None
    auto_approvable: bool = False
    status: str = "pending"
    created_at: datetime
    approved_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# =============================================================================
# APPROVAL MODELS
# =============================================================================


class Approval(BaseModel):
    """HITL approval request model."""

    id: str
    incident_id: str
    plan_id: str
    action_summary: str
    risk_score: float = Field(..., ge=0.0, le=1.0)
    status: ApprovalStatus = ApprovalStatus.PENDING
    approver: Optional[str] = None
    reason: Optional[str] = None
    auto_approve_eligible: bool = False
    expires_at: Optional[datetime] = None
    created_at: datetime
    decided_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# =============================================================================
# VERIFICATION MODELS
# =============================================================================


class Verification(BaseModel):
    """Post-execution verification check result."""

    id: str
    incident_id: str
    plan_id: Optional[str] = None
    check_type: VerificationType
    target: Optional[str] = None
    expected_state: Optional[str] = None
    actual_state: Optional[str] = None
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}
