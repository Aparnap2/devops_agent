"""LangGraph agent state definition for the DevOps Agent."""

from datetime import datetime
from typing import Annotated

from pydantic import Field
from typing_extensions import TypedDict

from src.types.state import (
    Anomaly,
    Feedback,
    Incident,
    RemediationPlan,
    RootCause,
    Signal,
)


class AgentState(TypedDict):
    """State for the DevOps Agent workflow.

    This is the central state object that flows through the LangGraph.
    All nodes read from and write to this state.
    """

    # Input signals queue
    signals: Annotated[list[Signal], lambda x, y: x + y]

    # Detected anomalies
    anomalies: Annotated[list[Anomaly], lambda x, y: x + y]

    # Current incident being processed
    current_incident: Incident | None

    # Root cause analysis results
    root_causes: list[RootCause]

    # Remediation plan
    remediation_plan: RemediationPlan | None

    # Execution results
    execution_results: list[dict]

    # Feedback for learning
    feedback: Annotated[list[Feedback], lambda x, y: x + y]

    # Workflow control
    current_step: str
    error_message: str | None

    # Timestamps
    started_at: datetime
    last_updated: datetime


def create_initial_state() -> AgentState:
    """Create the initial agent state."""
    return {
        "signals": [],
        "anomalies": [],
        "current_incident": None,
        "root_causes": [],
        "remediation_plan": None,
        "execution_results": [],
        "feedback": [],
        "current_step": "idle",
        "error_message": None,
        "started_at": datetime.utcnow(),
        "last_updated": datetime.utcnow(),
    }
