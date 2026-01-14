"""LangGraph workflow graph construction.

Builds the incident response state machine.
"""

import logging
from typing import Any, Literal, Optional

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.base import BaseCheckpointSaver

from src.workflow.state import AgentState, WorkflowStatus
from src.workflow.nodes import (
    create_incident_node,
    gather_context_node,
    diagnose_node,
    plan_node,
    approval_node,
    execute_node,
    verify_node,
    report_node,
)

logger = logging.getLogger(__name__)


def _route_after_approval(state: AgentState) -> Literal["execute", "escalate", "wait"]:
    """Route after approval node based on state."""
    if state.get("needs_interrupt"):
        return "wait"

    next_node = state.get("next_node")
    if next_node == "execute":
        return "execute"

    if state["status"] == WorkflowStatus.PENDING_APPROVAL:
        return "wait"
    elif state["status"] == WorkflowStatus.ESCALATED:
        return "escalate"
    else:
        return "execute"


def _route_after_verify(state: AgentState) -> Literal["report", "escalate"]:
    """Route after verification based on result."""
    if state["status"] == WorkflowStatus.RESOLVED:
        return "report"
    else:
        return "escalate"


def build_workflow() -> StateGraph:
    """Build the incident response workflow graph.

    State machine:
    START -> create_incident -> gather_context -> diagnose -> plan -> approval
    approval -> execute (if approved) -> verify -> report -> END
    approval -> escalate (if rejected) -> END
    verify -> escalate (if failed) -> END

    Returns:
        StateGraph with all nodes and edges configured
    """
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("create_incident", create_incident_node)
    workflow.add_node("gather_context", gather_context_node)
    workflow.add_node("diagnose", diagnose_node)
    workflow.add_node("plan", plan_node)
    workflow.add_node("approval", approval_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("verify", verify_node)
    workflow.add_node("report", report_node)

    # Define edges - main flow
    workflow.add_edge(START, "create_incident")
    workflow.add_edge("create_incident", "gather_context")
    workflow.add_edge("gather_context", "diagnose")
    workflow.add_edge("diagnose", "plan")
    workflow.add_edge("plan", "approval")

    # Conditional routing after approval
    workflow.add_conditional_edges(
        "approval",
        _route_after_approval,
        {
            "execute": "execute",
            "escalate": END,
            "wait": END,  # Paused for approval
        },
    )

    # Execute -> verify
    workflow.add_edge("execute", "verify")

    # Conditional routing after verification
    workflow.add_conditional_edges(
        "verify",
        _route_after_verify,
        {
            "report": "report",
            "escalate": END,
        },
    )

    # Report -> END
    workflow.add_edge("report", END)

    return workflow


def compile_workflow(
    checkpointer: Optional[BaseCheckpointSaver] = None,
) -> Any:
    """Compile workflow with optional checkpointer.

    Args:
        checkpointer: Optional checkpoint saver for state persistence

    Returns:
        Compiled workflow ready for execution
    """
    workflow = build_workflow()

    if checkpointer:
        return workflow.compile(checkpointer=checkpointer)
    else:
        return workflow.compile()


async def run_workflow(
    initial_state: AgentState,
    config: Optional[dict[str, Any]] = None,
    checkpointer: Optional[BaseCheckpointSaver] = None,
) -> AgentState:
    """Run the workflow from initial state.

    Args:
        initial_state: Starting state with alert info
        config: Optional LangGraph config (thread_id, etc.)
        checkpointer: Optional checkpointer for persistence

    Returns:
        Final state after workflow completion
    """
    compiled = compile_workflow(checkpointer=checkpointer)

    config = config or {"configurable": {"thread_id": initial_state["thread_id"]}}

    result = await compiled.ainvoke(initial_state, config=config)

    return result


async def resume_workflow(
    thread_id: str,
    approval_decision: dict[str, Any],
    checkpointer: BaseCheckpointSaver,
) -> AgentState:
    """Resume workflow after HITL approval.

    Args:
        thread_id: Thread ID of paused workflow
        approval_decision: Decision from human (approved, reason)
        checkpointer: Checkpointer with saved state

    Returns:
        Final state after workflow completion
    """
    from langgraph.types import Command

    compiled = compile_workflow(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id}}

    # Resume with approval decision
    if approval_decision.get("approved"):
        result = await compiled.ainvoke(
            Command(resume={"approved": True, **approval_decision}),
            config=config,
        )
    else:
        # Rejected - will route to escalate
        result = await compiled.ainvoke(
            Command(resume={"approved": False, **approval_decision}),
            config=config,
        )

    return result
