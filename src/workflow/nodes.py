"""Workflow nodes for LangGraph state machine.

Implements each stage of the incident response workflow.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from src.workflow.state import AgentState, WorkflowStatus
from src.workflow.policy import PolicyEngine, calculate_risk_score, requires_approval

logger = logging.getLogger(__name__)

# Dependency injection helpers
_repository = None
_k8s_tools = None
_prometheus_tools = None


def get_repository():
    """Get incident repository instance."""
    global _repository
    if _repository is None:
        from src.db.repository import IncidentRepository
        _repository = IncidentRepository()
    return _repository


def set_repository(repo):
    """Set repository for testing."""
    global _repository
    _repository = repo


def get_k8s_tools():
    """Get K8s tools instance."""
    global _k8s_tools
    if _k8s_tools is None:
        from src.tools.kubernetes import K8sTools
        _k8s_tools = K8sTools()
    return _k8s_tools


def set_k8s_tools(tools):
    """Set K8s tools for testing."""
    global _k8s_tools
    _k8s_tools = tools


def get_prometheus_tools():
    """Get Prometheus tools instance."""
    global _prometheus_tools
    if _prometheus_tools is None:
        from src.tools.prometheus import PrometheusTools
        _prometheus_tools = PrometheusTools()
    return _prometheus_tools


async def create_incident_node(state: AgentState) -> AgentState:
    """Create or find existing incident.

    Implements SOP-OPS-001: Incident Intake & Dedup.
    """
    logger.info(f"Creating incident for fingerprint: {state['fingerprint']}")

    repo = get_repository()

    from src.db.models import IncidentCreate, Severity

    # Map severity string to enum
    severity_map = {
        "low": Severity.LOW,
        "medium": Severity.MEDIUM,
        "high": Severity.HIGH,
        "critical": Severity.CRITICAL,
    }
    severity = severity_map.get(state["severity"].lower(), Severity.MEDIUM)

    # Parse namespace and service from fingerprint if not provided
    parts = state["fingerprint"].split(":")
    namespace = state.get("namespace") or (parts[1] if len(parts) > 1 else None)
    service = state.get("affected_service") or (parts[2] if len(parts) > 2 else None)

    incident_create = IncidentCreate(
        title=f"Alert: {parts[0] if parts else state['fingerprint']}",
        severity=severity,
        fingerprint=state["fingerprint"],
        namespace=namespace,
        affected_service=service,
        alert_labels=state.get("alert_labels", {}),
    )

    incident, created = await repo.find_or_create_incident(incident_create)

    if created:
        logger.info(f"Created new incident: {incident.id}")
    else:
        logger.info(f"Found existing incident: {incident.id}")

    return {
        **state,
        "incident_id": incident.id,
        "namespace": namespace,
        "affected_service": service,
        "status": WorkflowStatus.INVESTIGATING,
        "updated_at": datetime.now(timezone.utc),
    }


async def gather_context_node(state: AgentState) -> AgentState:
    """Gather context from Kubernetes and Prometheus.

    Collects pods, events, logs, and metrics for analysis.
    """
    logger.info(f"Gathering context for incident: {state['incident_id']}")

    k8s = get_k8s_tools()
    namespace = state.get("namespace", "default")
    observations = []

    # Get pods
    try:
        pods_result = await k8s.list_pods(
            namespace=namespace,
            label_selector=f"app={state.get('affected_service', '')}" if state.get("affected_service") else None,
        )
        if pods_result.success:
            observations.append({
                "type": "pods",
                "data": pods_result.output,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        logger.error(f"Failed to get pods: {e}")

    # Get events
    try:
        events_result = await k8s.get_events(namespace=namespace)
        if events_result.success:
            observations.append({
                "type": "events",
                "data": events_result.output,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        logger.error(f"Failed to get events: {e}")

    # Get logs from affected pods
    try:
        if pods_result.success and pods_result.output.get("items"):
            for pod in pods_result.output["items"][:3]:  # Limit to 3 pods
                pod_name = pod.get("metadata", {}).get("name")
                if pod_name:
                    logs_result = await k8s.get_logs(pod_name, namespace, tail_lines=50)
                    if logs_result.success:
                        observations.append({
                            "type": "logs",
                            "pod": pod_name,
                            "data": logs_result.output,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
    except Exception as e:
        logger.error(f"Failed to get logs: {e}")

    logger.info(f"Gathered {len(observations)} observations")

    return {
        **state,
        "observations": observations,
        "updated_at": datetime.now(timezone.utc),
    }


async def diagnose_node(state: AgentState) -> AgentState:
    """Analyze observations and generate hypotheses.

    Uses rule-based analysis to determine root cause candidates.
    """
    logger.info(f"Diagnosing incident: {state['incident_id']}")

    observations = state.get("observations", [])
    hypotheses = []

    # Analyze events for common issues
    for obs in observations:
        if obs["type"] == "events":
            events = obs.get("data", {}).get("items", [])
            for event in events:
                reason = event.get("reason", "")
                message = event.get("message", "")

                if reason == "OOMKilled":
                    hypotheses.append({
                        "id": str(uuid.uuid4()),
                        "cause": "Memory limit exceeded - container was OOMKilled",
                        "confidence": 0.9,
                        "evidence": [{"event": event}],
                        "suggested_actions": ["restart_pod", "scale_deployment"],
                    })

                elif reason == "CrashLoopBackOff":
                    hypotheses.append({
                        "id": str(uuid.uuid4()),
                        "cause": "Container repeatedly crashing - CrashLoopBackOff",
                        "confidence": 0.85,
                        "evidence": [{"event": event}],
                        "suggested_actions": ["restart_pod", "rollback_deployment"],
                    })

                elif reason == "BackOff":
                    hypotheses.append({
                        "id": str(uuid.uuid4()),
                        "cause": "Container start/restart backoff",
                        "confidence": 0.7,
                        "evidence": [{"event": event}],
                        "suggested_actions": ["restart_pod"],
                    })

    # Check pod statuses
    for obs in observations:
        if obs["type"] == "pods":
            pods = obs.get("data", {}).get("items", [])
            for pod in pods:
                status = pod.get("status", {})
                phase = status.get("phase", "")

                if phase not in ["Running", "Succeeded"]:
                    hypotheses.append({
                        "id": str(uuid.uuid4()),
                        "cause": f"Pod in unhealthy state: {phase}",
                        "confidence": 0.6,
                        "evidence": [{"pod_status": status}],
                        "suggested_actions": ["restart_pod"],
                    })

    # If no specific hypothesis, create a generic one
    if not hypotheses:
        hypotheses.append({
            "id": str(uuid.uuid4()),
            "cause": "Unable to determine specific root cause from available data",
            "confidence": 0.3,
            "evidence": [],
            "suggested_actions": ["escalate"],
        })

    # Calculate risk score
    risk_score = calculate_risk_score(
        severity=state["severity"],
        observations=observations,
        hypotheses=hypotheses,
        namespace=state.get("namespace"),
    )

    logger.info(f"Generated {len(hypotheses)} hypotheses, risk score: {risk_score}")

    return {
        **state,
        "hypotheses": hypotheses,
        "risk_score": risk_score,
        "status": WorkflowStatus.PLANNING,
        "updated_at": datetime.now(timezone.utc),
    }


async def plan_node(state: AgentState) -> AgentState:
    """Generate remediation plan from hypotheses.

    Only proposes allowlisted actions per SOP-OPS-002.
    """
    logger.info(f"Planning remediation for incident: {state['incident_id']}")

    hypotheses = state.get("hypotheses", [])
    actions = []

    # Get primary hypothesis (highest confidence)
    if hypotheses:
        primary = max(hypotheses, key=lambda h: h.get("confidence", 0))

        # Generate actions based on suggested actions
        for action_type in primary.get("suggested_actions", []):
            if action_type == "restart_pod":
                actions.append({
                    "id": str(uuid.uuid4()),
                    "type": "restart_pod",
                    "target": state.get("affected_service", "unknown"),
                    "parameters": {"namespace": state.get("namespace", "default")},
                    "risk_level": "low",
                    "requires_approval": False,
                })

            elif action_type == "scale_deployment":
                actions.append({
                    "id": str(uuid.uuid4()),
                    "type": "scale_deployment",
                    "target": state.get("affected_service", "unknown"),
                    "parameters": {
                        "namespace": state.get("namespace", "default"),
                        "replicas": 3,  # Default scale up
                    },
                    "risk_level": "medium",
                    "requires_approval": True,
                })

            elif action_type == "rollback_deployment":
                actions.append({
                    "id": str(uuid.uuid4()),
                    "type": "rollback_deployment",
                    "target": state.get("affected_service", "unknown"),
                    "parameters": {"namespace": state.get("namespace", "default")},
                    "risk_level": "high",
                    "requires_approval": True,
                })

            elif action_type == "escalate":
                actions.append({
                    "id": str(uuid.uuid4()),
                    "type": "escalate",
                    "target": "oncall",
                    "parameters": {},
                    "risk_level": "low",
                    "requires_approval": False,
                })

    plan = {
        "id": str(uuid.uuid4()),
        "incident_id": state["incident_id"],
        "hypothesis_id": hypotheses[0]["id"] if hypotheses else None,
        "actions": actions,
        "total_risk_score": state["risk_score"],
        "auto_approvable": state["risk_score"] < 0.4 and state.get("namespace") not in ["prod", "production"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(f"Created plan with {len(actions)} actions")

    return {
        **state,
        "plan": plan,
        "updated_at": datetime.now(timezone.utc),
    }


async def approval_node(state: AgentState) -> AgentState:
    """Determine if HITL approval is needed.

    Implements SOP-OPS-003: HITL Approval Policy.
    """
    logger.info(f"Checking approval for incident: {state['incident_id']}")

    plan = state.get("plan", {})
    risk_score = state.get("risk_score", 0)
    namespace = state.get("namespace")

    # Get highest confidence hypothesis
    hypotheses = state.get("hypotheses", [])
    rca_confidence = max((h.get("confidence", 0) for h in hypotheses), default=0)

    # Check if approval is required
    needs_approval = requires_approval(
        risk_score=risk_score,
        namespace=namespace,
        rca_confidence=rca_confidence,
    )

    if needs_approval:
        logger.info("HITL approval required")

        # In a real implementation, this would use LangGraph's interrupt()
        # For now, we set the status and mark for interrupt
        return {
            **state,
            "status": WorkflowStatus.PENDING_APPROVAL,
            "needs_interrupt": True,
            "updated_at": datetime.now(timezone.utc),
        }

    # Auto-approve
    logger.info("Auto-approving plan (low risk)")
    return {
        **state,
        "status": WorkflowStatus.EXECUTING,
        "approval_decision": {"approved": True, "auto": True},
        "next_node": "execute",
        "updated_at": datetime.now(timezone.utc),
    }


async def execute_node(state: AgentState) -> AgentState:
    """Execute approved remediation actions.

    Only executes allowlisted actions.
    """
    logger.info(f"Executing plan for incident: {state['incident_id']}")

    k8s = get_k8s_tools()
    plan = state.get("plan", {})
    actions = plan.get("actions", [])
    results = []

    for action in actions:
        action_type = action.get("type")
        target = action.get("target")
        params = action.get("parameters", {})
        namespace = params.get("namespace", "default")

        logger.info(f"Executing action: {action_type} on {target}")

        try:
            if action_type == "restart_pod":
                result = await k8s.restart_pod(target, namespace)
                results.append({
                    "action_id": action["id"],
                    "type": action_type,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                })

            elif action_type == "scale_deployment":
                replicas = params.get("replicas", 3)
                result = await k8s.scale_deployment(target, namespace, replicas)
                results.append({
                    "action_id": action["id"],
                    "type": action_type,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                })

            elif action_type == "rollback_deployment":
                result = await k8s.rollback_deployment(target, namespace)
                results.append({
                    "action_id": action["id"],
                    "type": action_type,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                })

            elif action_type == "escalate":
                # Mark for escalation
                results.append({
                    "action_id": action["id"],
                    "type": action_type,
                    "success": True,
                    "output": {"escalated": True},
                })

        except Exception as e:
            logger.error(f"Action {action_type} failed: {e}")
            results.append({
                "action_id": action["id"],
                "type": action_type,
                "success": False,
                "error": str(e),
            })

    logger.info(f"Executed {len(results)} actions")

    return {
        **state,
        "execution_results": results,
        "status": WorkflowStatus.VERIFYING,
        "updated_at": datetime.now(timezone.utc),
    }


async def verify_node(state: AgentState) -> AgentState:
    """Verify recovery after execution.

    Implements SOP-OPS-004: Verification & Closure.
    """
    logger.info(f"Verifying recovery for incident: {state['incident_id']}")

    k8s = get_k8s_tools()
    namespace = state.get("namespace", "default")
    verification_results = []
    all_passed = True

    # Check pod health
    try:
        pods_result = await k8s.list_pods(namespace=namespace)
        if pods_result.success:
            pods = pods_result.output.get("items", [])
            for pod in pods:
                status = pod.get("status", {})
                phase = status.get("phase", "")
                pod_name = pod.get("metadata", {}).get("name", "unknown")

                # Check if Running and Ready
                is_healthy = phase == "Running"
                conditions = status.get("conditions", [])
                is_ready = any(
                    c.get("type") == "Ready" and c.get("status") == "True"
                    for c in conditions
                )

                passed = is_healthy and is_ready
                if not passed:
                    all_passed = False

                verification_results.append({
                    "type": "pod_health",
                    "target": pod_name,
                    "passed": passed,
                    "details": {"phase": phase, "ready": is_ready},
                })
    except Exception as e:
        logger.error(f"Pod health check failed: {e}")
        all_passed = False

    # Determine final status
    if all_passed:
        final_status = WorkflowStatus.RESOLVED
    else:
        final_status = WorkflowStatus.ESCALATED

    logger.info(f"Verification complete: {final_status}")

    return {
        **state,
        "verification_results": verification_results,
        "status": final_status,
        "updated_at": datetime.now(timezone.utc),
    }


async def report_node(state: AgentState) -> AgentState:
    """Generate incident report.

    Creates Markdown report with timeline, actions, and lessons.
    """
    logger.info(f"Generating report for incident: {state['incident_id']}")

    # Build report
    report = {
        "id": str(uuid.uuid4()),
        "incident_id": state["incident_id"],
        "title": f"Incident Report: {state['fingerprint']}",
        "status": state["status"].value,
        "severity": state["severity"],
        "summary": _generate_summary(state),
        "timeline": _generate_timeline(state),
        "root_cause": _extract_root_cause(state),
        "actions_taken": state.get("execution_results", []),
        "verification": state.get("verification_results", []),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    logger.info("Report generated")

    return {
        **state,
        "report": report,
        "updated_at": datetime.now(timezone.utc),
    }


def _generate_summary(state: AgentState) -> str:
    """Generate incident summary."""
    hypotheses = state.get("hypotheses", [])
    primary_cause = hypotheses[0].get("cause", "Unknown") if hypotheses else "Unknown"

    results = state.get("execution_results", [])
    successful = sum(1 for r in results if r.get("success"))

    return f"""
Incident affecting {state.get('affected_service', 'unknown')} in {state.get('namespace', 'unknown')} namespace.
Root cause: {primary_cause}
Actions executed: {len(results)} ({successful} successful)
Final status: {state['status'].value}
"""


def _generate_timeline(state: AgentState) -> list[dict]:
    """Generate incident timeline."""
    timeline = [
        {"time": state["created_at"].isoformat() if hasattr(state["created_at"], "isoformat") else str(state["created_at"]), "event": "Incident detected"},
    ]

    # Add observation events
    for obs in state.get("observations", []):
        timeline.append({
            "time": obs.get("timestamp", ""),
            "event": f"Gathered {obs['type']} data",
        })

    # Add execution events
    for result in state.get("execution_results", []):
        timeline.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "event": f"Executed {result.get('type')}: {'success' if result.get('success') else 'failed'}",
        })

    return timeline


def _extract_root_cause(state: AgentState) -> str:
    """Extract root cause from hypotheses."""
    hypotheses = state.get("hypotheses", [])
    if hypotheses:
        primary = max(hypotheses, key=lambda h: h.get("confidence", 0))
        return primary.get("cause", "Unknown")
    return "Unable to determine root cause"
