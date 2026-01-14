"""Streamlit Control Tower UI.

Provides human-in-the-loop approval interface for the SRE Agent.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import streamlit as st
from streamlit import column_config

from src.workflow.state import AgentState, WorkflowStatus, create_initial_state
from src.ui.approval import (
    format_incident_card,
    format_plan_details,
    format_approval_decision,
    state_to_json_serializable,
)

logger = logging.getLogger(__name__)


def render_header() -> None:
    """Render the page header."""
    st.set_page_config(
        page_title="SRE Agent Control Tower",
        page_icon="🚨",
        layout="wide",
    )
    st.title("🚨 SRE Agent Control Tower")
    st.markdown("Human-in-the-loop approval interface for autonomous incident response")


def render_incident_card(card_data: dict[str, Any]) -> None:
    """Render an incident card with details and actions.

    Args:
        card_data: Formatted incident card data
    """
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)

        with col1:
            st.subheader(f"Incident: {card_data['id']}")
            st.markdown(f"**Fingerprint:** `{card_data['fingerprint']}`")
            st.markdown(f"**Service:** {card_data['affected_service']}")
            st.markdown(f"**Namespace:** `{card_data['namespace']}`")

        with col2:
            severity_colors = {
                "CRITICAL": "🔴",
                "HIGH": "🟠",
                "MEDIUM": "🟡",
                "LOW": "🟢",
            }
            severity_icon = severity_colors.get(card_data["severity"], "⚪")
            st.markdown(f"**Severity:** {severity_icon} {card_data['severity']}")

            risk_color = card_data.get("risk_color", "gray")
            st.markdown(
                f"**Risk Score:** :{risk_color}[{card_data['risk_score']:.2f}]"
            )

            status_icon = {
                WorkflowStatus.PENDING_APPROVAL: "⏳",
                WorkflowStatus.INVESTIGATING: "🔍",
                WorkflowStatus.EXECUTING: "⚙️",
                WorkflowStatus.RESOLVED: "✅",
                WorkflowStatus.ESCALATED: "🚨",
            }.get(card_data.get("status_enum"), "📋")
            st.markdown(f"**Status:** {status_icon} {card_data['status'].replace('_', ' ').title()}")

        with col3:
            st.markdown(f"**Created:** {card_data['created_at']}")
            st.markdown(f"**Updated:** {card_data['updated_at']}")

        # Observations summary
        obs = card_data.get("observations_summary", {})
        if obs.get("events") or obs.get("pods"):
            with st.expander("📊 Observations Summary", expanded=False):
                if obs.get("events"):
                    st.markdown("**Events:**")
                    st.code(", ".join(set(obs["events"])))
                if obs.get("pods"):
                    st.markdown("**Pod Statuses:**")
                    st.code(", ".join(set(obs["pods"])))

        # Hypothesis
        hypothesis = card_data.get("hypothesis")
        if hypothesis:
            with st.expander("🔍 Root Cause Hypothesis", expanded=True):
                st.markdown(f"**Cause:** {hypothesis.get('cause', 'Unknown')}")
                confidence = hypothesis.get("confidence", 0)
                st.progress(confidence)
                st.caption(f"Confidence: {confidence:.0%}")


def render_plan_details(plan_data: dict[str, Any]) -> None:
    """Render remediation plan details.

    Args:
        plan_data: Formatted plan details
    """
    st.markdown("### 📋 Proposed Remediation Plan")

    if not plan_data:
        st.warning("No plan available")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Plan ID:** `{plan_data['plan_id']}`")
        st.markdown(f"**Actions:** {plan_data['action_count']}")
    with col2:
        risk = plan_data.get("total_risk_score", 0)
        risk_color = plan_data.get("risk_color", "gray") if hasattr(plan_data, "risk_color") else "orange"
        st.markdown(f"**Total Risk:** :{risk_color}[{risk:.2f}]")
        if plan_data.get("auto_approvable"):
            st.success("✅ Auto-approvable (low risk, non-prod)")

    # Action list
    st.markdown("#### Actions")
    for i, action in enumerate(plan_data["actions"], 1):
        risk_level = action.get("risk_level", "unknown")
        risk_colors = {"low": "green", "medium": "orange", "high": "red", "unknown": "gray"}
        color = risk_colors.get(risk_level, "gray")

        with st.container(border=True):
            c1, c2, c3 = st.columns([1, 2, 1])
            with c1:
                st.markdown(f"**{i}.** `{action['type']}`")
            with c2:
                st.markdown(f"Target: `{action.get('target', 'N/A')}`")
                params = action.get("parameters", {})
                if params:
                    st.caption(f"Params: {params}")
            with c3:
                st.markdown(f"Risk: :{color}[{risk_level}]")
                if action.get("requires_approval"):
                    st.caption("⚠️ Requires approval")


def render_approval_form(
    incident_id: str,
    on_approve: callable,
    on_reject: callable,
) -> None:
    """Render approval/rejection form.

    Args:
        incident_id: ID of the incident
        on_approve: Callback for approve action
        on_reject: Callback for reject action
    """
    st.markdown("### ✅ Approval Decision")

    col1, col2 = st.columns(2)

    with col1:
        approve_reason = st.text_area(
            "Reason for approval (optional)",
            placeholder="e.g., Confirmed memory issue, safe to restart",
            height=100,
        )

    with col2:
        reject_reason = st.text_area(
            "Reason for rejection (required)",
            placeholder="e.g., Need more investigation before proceeding",
            height=100,
        )

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        if st.button("✅ Approve & Execute", type="primary", use_container_width=True):
            if True:  # Approval always allowed
                on_approve(approve_reason)

    with c2:
        disabled = not reject_reason
        if st.button("❌ Reject", disabled=disabled, type="secondary", use_container_width=True):
            if reject_reason:
                on_reject(reject_reason)

    with c3:
        st.info("💡 Rejection requires a reason. Approval is optional but recommended.")


def render_workflow_status(state: AgentState) -> None:
    """Render current workflow status.

    Args:
        state: Current agent state
    """
    st.markdown("### 📊 Workflow Status")

    status_flow = [
        WorkflowStatus.OPEN,
        WorkflowStatus.INVESTIGATING,
        WorkflowStatus.PLANNING,
        WorkflowStatus.PENDING_APPROVAL,
        WorkflowStatus.EXECUTING,
        WorkflowStatus.VERIFYING,
    ]

    current_status = state.get("status", WorkflowStatus.OPEN)

    # Create status indicator
    cols = st.columns(len(status_flow))
    for i, status in enumerate(status_flow):
        is_active = status == current_status
        is_past = status_flow.index(current_status) > i

        with cols[i]:
            if is_active:
                st.markdown(f"🔵 **{status.value.replace('_', ' ').title()}**")
            elif is_past:
                st.markdown(f"✅ {status.value.replace('_', ' ').title()}")
            else:
                st.markdown(f"⚪ {status.value.replace('_', ' ').title()}")


def render_dashboard(
    pending_incidents: list[dict[str, Any]],
    on_approve: callable,
    on_reject: callable,
) -> None:
    """Render the main dashboard.

    Args:
        pending_incidents: List of pending incident states
        on_approve: Callback for approve action
        on_reject: Callback for reject action
    """
    if not pending_incidents:
        st.info("✅ No pending approvals. All clear!")
        return

    st.markdown(f"### ⏳ Pending Approvals ({len(pending_incidents)})")

    for i, incident in enumerate(pending_incidents):
        card = format_incident_card(incident)
        plan = format_plan_details(incident.get("plan"))

        st.markdown(f"#### Incident {i + 1}")
        render_incident_card(card)

        if plan:
            render_plan_details(plan)

        render_approval_form(
            card["id"],
            lambda reason: on_approve(incident, reason),
            lambda reason: on_reject(incident, reason),
        )

        st.divider()


async def main():
    """Main entry point for the Streamlit UI."""
    render_header()

    # TODO: Replace with actual API client
    # For demo, create sample pending incidents
    sample_incidents = []

    # Check for pending incidents from workflow
    # This would be replaced with actual API call:
    # async with httpx.AsyncClient() as client:
    #     response = await client.get("http://localhost:8000/api/pending-approvals")
    #     sample_incidents = response.json()

    # Demo: Show empty state if no incidents
    if not sample_incidents:
        st.info("📭 No pending approval requests")
        st.markdown("""
        ### How it works:

        1. **Alert Detection** → Agent detects incident from Alertmanager
        2. **Context Gathering** → Agent gathers pod, event, and log data
        3. **Diagnosis** → Agent proposes root cause hypotheses
        4. **Planning** → Agent creates remediation plan with risk assessment
        5. **Approval** → Human reviews and approves/rejects
        6. **Execution** → Agent executes approved actions
        7. **Verification** → Agent verifies recovery
        8. **Report** → Agent generates incident report
        """)

        # Demo: Show sample incident
        with st.expander("👀 Preview: Sample Approval Request", expanded=False):
            sample_state = create_initial_state(
                fingerprint="OOMKilled:prod:api-service",
                severity="critical",
                namespace="prod",
                affected_service="api-service",
            )
            sample_state.update({
                "incident_id": "INC-001-DEMO",
                "status": WorkflowStatus.PENDING_APPROVAL,
                "risk_score": 0.75,
                "hypotheses": [
                    {
                        "id": "h1",
                        "cause": "Memory limit exceeded - container hit OOM limit",
                        "confidence": 0.9,
                    }
                ],
                "plan": {
                    "id": "PLAN-001",
                    "actions": [
                        {
                            "id": "a1",
                            "type": "restart_pod",
                            "target": "api-service",
                            "parameters": {"namespace": "prod"},
                            "risk_level": "low",
                            "requires_approval": False,
                        },
                        {
                            "id": "a2",
                            "type": "scale_deployment",
                            "target": "api-service",
                            "parameters": {"namespace": "prod", "replicas": 3},
                            "risk_level": "high",
                            "requires_approval": True,
                        },
                    ],
                    "total_risk_score": 0.75,
                },
                "needs_interrupt": True,
            })

            card = format_incident_card(sample_state)
            plan = format_plan_details(sample_state.get("plan"))

            render_incident_card(card)
            if plan:
                render_plan_details(plan)

    # Sidebar
    with st.sidebar:
        st.header("Settings")
        auto_refresh = st.checkbox("Auto-refresh", value=False)
        refresh_interval = st.slider("Refresh interval (s)", 5, 60, 10)

        st.header("Statistics")
        st.metric("Pending", len(sample_incidents))
        st.metric("Resolved Today", 5)
        st.metric("Avg Resolution Time", "12m")

        st.header("Navigation")
        st.page_link("app.py", label="Dashboard", icon="📊")
        st.page_link("pages/incidents.py", label="Incidents", icon="📋")
        st.page_link("pages/reports.py", label="Reports", icon="📝")


if __name__ == "__main__":
    asyncio.run(main())
