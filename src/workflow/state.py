"""Agent state definition for LangGraph workflow.

Implements typed state per PRD Section 5.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, TypedDict
import uuid


class WorkflowStatus(str, Enum):
    """Workflow status states per PRD Section 2."""

    OPEN = "open"
    INVESTIGATING = "investigating"
    PLANNING = "planning"
    PENDING_APPROVAL = "pending_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    ABORTED = "aborted"


class AgentState(TypedDict, total=False):
    """Agent state for LangGraph workflow.

    Contains all data needed throughout the incident lifecycle.
    """

    # Incident identification
    incident_id: Optional[str]
    fingerprint: str
    severity: str
    namespace: Optional[str]
    affected_service: Optional[str]
    alert_labels: dict[str, Any]

    # Workflow status
    status: WorkflowStatus

    # Investigation phase
    observations: list[dict[str, Any]]  # Tool call results
    hypotheses: list[dict[str, Any]]  # Root cause candidates
    risk_score: float  # 0.0 - 1.0

    # Remediation phase
    plan: Optional[dict[str, Any]]  # Proposed actions
    approval_id: Optional[str]
    approval_decision: Optional[dict[str, Any]]

    # Execution phase
    execution_results: list[dict[str, Any]]

    # Verification phase
    verification_results: list[dict[str, Any]]

    # Reporting
    report: Optional[dict[str, Any]]

    # Metadata
    thread_id: str
    created_at: datetime
    updated_at: datetime

    # Routing hints (not using reserved names)
    next_node: Optional[str]
    needs_interrupt: Optional[bool]


def create_initial_state(
    fingerprint: str,
    severity: str,
    namespace: Optional[str] = None,
    affected_service: Optional[str] = None,
    alert_labels: Optional[dict[str, Any]] = None,
) -> AgentState:
    """Create initial agent state from alert.

    Args:
        fingerprint: Unique alert fingerprint for dedup
        severity: Alert severity (low, medium, high, critical)
        namespace: Kubernetes namespace (optional)
        affected_service: Affected service name (optional)
        alert_labels: Alert labels from Alertmanager (optional)

    Returns:
        Initial AgentState
    """
    now = datetime.now(timezone.utc)

    return AgentState(
        incident_id=None,
        fingerprint=fingerprint,
        severity=severity,
        namespace=namespace,
        affected_service=affected_service,
        alert_labels=alert_labels or {},
        status=WorkflowStatus.OPEN,
        observations=[],
        hypotheses=[],
        risk_score=0.0,
        plan=None,
        approval_id=None,
        approval_decision=None,
        execution_results=[],
        verification_results=[],
        report=None,
        thread_id=str(uuid.uuid4()),
        created_at=now,
        updated_at=now,
    )
