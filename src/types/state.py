"""Core types and state definitions for the DevOps Agent."""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, Field


class SignalType(str, Enum):
    """Types of telemetry signals."""

    LOG = "log"
    METRIC = "metric"
    TRACE = "trace"
    CI_CD_EVENT = "ci_cd_event"
    ALERT = "alert"


class Severity(str, Enum):
    """Incident severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class IncidentStatus(str, Enum):
    """Incident resolution status."""

    DETECTED = "detected"
    DIAGNOSING = "diagnosing"
    REMEDIATING = "remediating"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class Signal(BaseModel):
    """Represents a telemetry signal from any source."""

    id: str = Field(..., description="Unique signal identifier")
    type: SignalType = Field(..., description="Type of signal")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: str = Field(..., description="Source system (e.g., 'prometheus', 'k8s')")
    service: str = Field(..., description="Affected service name")
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_content: dict[str, Any] = Field(..., description="Raw signal content")


class Anomaly(BaseModel):
    """Represents a detected anomaly."""

    id: str = Field(..., description="Unique anomaly identifier")
    signal_id: str = Field(..., description="Source signal ID")
    severity: Severity = Field(..., description="Anomaly severity")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Detection confidence")
    description: str = Field(..., description="Human-readable description")
    affected_metrics: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ServiceNode(BaseModel):
    """Represents a node in the service dependency graph."""

    id: str = Field(..., description="Service identifier")
    name: str = Field(..., description="Service name")
    namespace: str = Field(default="default")
    dependencies: list[str] = Field(default_factory=list, description="Service dependencies")
    health_endpoint: str | None = Field(None, description="Health check endpoint")


class RootCause(BaseModel):
    """Represents a root cause analysis result."""

    id: str = Field(..., description="Unique RCA identifier")
    anomaly_id: str = Field(..., description="Related anomaly ID")
    probable_cause: str = Field(..., description="Description of root cause")
    affected_services: list[str] = Field(default_factory=list)
    related_signals: list[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RemediationAction(BaseModel):
    """Represents a remediation action to be taken."""

    id: str = Field(..., description="Action identifier")
    type: str = Field(..., description="Action type (e.g., 'restart_pod', 'scale_deployment')")
    target: str = Field(..., description="Target resource")
    parameters: dict[str, Any] = Field(default_factory=dict)
    risk_level: str = Field(..., description="Risk level: low/medium/high")
    estimated_impact: str = Field(default="unknown", description="Expected impact description")
    requires_approval: bool = Field(default=False, description="Requires HITL approval")


class RemediationPlan(BaseModel):
    """Represents a remediation plan with multiple actions."""

    id: str = Field(..., description="Plan identifier")
    incident_id: str = Field(..., description="Related incident/anomaly ID")
    actions: list[RemediationAction] = Field(default_factory=list)
    total_risk_score: float = Field(default=0.0)
    estimated_duration_seconds: int = Field(default=0)
    auto_approvable: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Incident(BaseModel):
    """Represents an active incident."""

    id: str = Field(..., description="Unique incident identifier")
    status: IncidentStatus = Field(default=IncidentStatus.DETECTED)
    severity: Severity = Field(..., description="Incident severity")
    title: str = Field(..., description="Incident title")
    description: str = Field(..., description="Detailed description")
    affected_services: list[str] = Field(default_factory=list)
    anomaly_ids: list[str] = Field(default_factory=list)
    root_cause_id: str | None = Field(None, description="Related RCA ID")
    remediation_plan_id: str | None = Field(None, description="Related remediation plan ID")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: datetime | None = Field(None)


class ExecutionResult(BaseModel):
    """Result of an action execution."""

    action_id: str = Field(..., description="Related action ID")
    success: bool = Field(..., description="Execution success status")
    output: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = Field(None)
    duration_seconds: float = Field(default=0.0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Feedback(BaseModel):
    """Feedback for learning and improvement."""

    incident_id: str = Field(..., description="Related incident ID")
    agent_action: str = Field(..., description="What the agent did")
    engineer_feedback: str = Field(..., description="Engineer's feedback")
    was_correct: bool = Field(..., description="Whether action was correct")
    suggestions: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
