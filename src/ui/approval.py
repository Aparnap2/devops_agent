"""Approval UI utilities for Control Tower.

Provides formatting and state conversion utilities for the Streamlit UI.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from src.workflow.state import AgentState, WorkflowStatus


def get_risk_color(risk_score: float) -> str:
    """Get color indicator for risk score.

    Args:
        risk_score: Risk score between 0.0 and 1.0

    Returns:
        Color string for UI display
    """
    if risk_score < 0.3:
        return "green"
    elif risk_score < 0.5:
        return "orange"
    elif risk_score < 0.7:
        return "red"
    return "darkred"


def format_timestamp(ts: Any) -> str:
    """Format timestamp for display.

    Args:
        ts: Datetime object or ISO format string

    Returns:
        Formatted timestamp string
    """
    if isinstance(ts, str):
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    elif isinstance(ts, datetime):
        dt = ts
    else:
        return str(ts)

    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def format_incident_card(state: AgentState) -> dict[str, Any]:
    """Format incident state for UI card display.

    Args:
        state: AgentState for the incident

    Returns:
        Dictionary with formatted incident card data
    """
    observations_summary = {"events": [], "pods": [], "logs": []}

    for obs in state.get("observations", []):
        obs_type = obs.get("type")
        if obs_type == "events":
            events = obs.get("data", {}).get("items", [])
            observations_summary["events"].extend([e.get("reason", "") for e in events])
        elif obs_type == "pods":
            pods = obs.get("data", {}).get("items", [])
            observations_summary["pods"].extend([p.get("status", {}).get("phase", "") for p in pods])
        elif obs_type == "logs":
            observations_summary["logs"].append(obs.get("pod", ""))

    # Get primary hypothesis
    hypotheses = state.get("hypotheses", [])
    primary_hypothesis = hypotheses[0] if hypotheses else None

    return {
        "id": state.get("incident_id", "N/A"),
        "fingerprint": state.get("fingerprint", "Unknown"),
        "severity": state.get("severity", "unknown").upper(),
        "namespace": state.get("namespace", "default"),
        "affected_service": state.get("affected_service", "unknown"),
        "risk_score": state.get("risk_score", 0.0),
        "risk_color": get_risk_color(state.get("risk_score", 0.0)),
        "status": state.get("status", WorkflowStatus.OPEN).value,
        "status_enum": state.get("status", WorkflowStatus.OPEN),
        "observations_summary": observations_summary,
        "hypothesis": primary_hypothesis,
        "created_at": format_timestamp(state.get("created_at", datetime.now(timezone.utc))),
        "updated_at": format_timestamp(state.get("updated_at", datetime.now(timezone.utc))),
    }


def format_plan_details(plan: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Format remediation plan for UI display.

    Args:
        plan: Plan dictionary from agent state

    Returns:
        Dictionary with formatted plan details
    """
    if not plan:
        return None

    actions = []
    for action in plan.get("actions", []):
        actions.append({
            "id": action.get("id", ""),
            "type": action.get("type", ""),
            "target": action.get("target", ""),
            "parameters": action.get("parameters", {}),
            "risk_level": action.get("risk_level", "unknown"),
            "risk_color": get_risk_color(
                {"low": 0.2, "medium": 0.5, "high": 0.8}.get(
                    action.get("risk_level", "unknown"), 0.5
                )
            ),
            "requires_approval": action.get("requires_approval", False),
        })

    return {
        "plan_id": plan.get("id", ""),
        "actions": actions,
        "action_count": len(actions),
        "total_risk_score": plan.get("total_risk_score", 0.0),
        "auto_approvable": plan.get("auto_approvable", False),
    }


def format_approval_decision(
    approved: bool,
    reason: str,
    approver: str = "human-operator",
) -> dict[str, Any]:
    """Format approval decision for workflow resume.

    Args:
        approved: Whether the plan was approved
        reason: Reason for the decision
        approver: Name/ID of approver

    Returns:
        Decision dictionary for workflow resume
    """
    return {
        "approved": approved,
        "reason": reason,
        "approver": approver,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def state_to_json_serializable(state: AgentState) -> dict[str, Any]:
    """Convert AgentState to JSON-serializable format.

    Args:
        state: AgentState dictionary

    Returns:
        JSON-serializable dictionary
    """
    def serialize_value(v: Any) -> Any:
        if isinstance(v, datetime):
            return v.isoformat()
        elif isinstance(v, WorkflowStatus):
            return v.value
        elif isinstance(v, list):
            return [serialize_value(item) for item in v]
        elif isinstance(v, dict):
            return {key: serialize_value(val) for key, val in v.items()}
        return v

    return serialize_value(state)
