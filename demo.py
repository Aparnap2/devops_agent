#!/usr/bin/env python3
"""Demo script showing the SRE Agent workflow.

This script demonstrates the agent handling an OOMKilled incident
through the full workflow: detect → triage → propose → approve → execute → verify.
"""

import asyncio
import logging
from datetime import datetime, timezone

from src.workflow.state import AgentState, WorkflowStatus, create_initial_state
from src.workflow.nodes import (
    diagnose_node,
    plan_node,
    approval_node,
    execute_node,
    verify_node,
    report_node,
)
from src.workflow.policy import calculate_risk_score

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def simulate_oomkilled_incident():
    """Simulate handling an OOMKilled incident."""
    logger.info("=" * 60)
    logger.info("🚀 SRE Agent Demo: OOMKilled Incident Response")
    logger.info("=" * 60)

    # Step 1: Create initial state (as if Alertmanager sent an alert)
    state = create_initial_state(
        fingerprint="OOMKilled:staging:demo-app",
        severity="high",
        namespace="staging",
        affected_service="demo-app",
    )
    state["incident_id"] = f"INC-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    logger.info(f"\n📥 Step 1: Incident Created")
    logger.info(f"   Fingerprint: {state['fingerprint']}")
    logger.info(f"   Severity: {state['severity']}")
    logger.info(f"   Namespace: {state['namespace']}")

    # Step 2: Simulate gathered observations
    state["observations"] = [
        {
            "type": "events",
            "data": {
                "items": [
                    {
                        "reason": "OOMKilled",
                        "message": "Container demo-app-abc exceeded memory limit (512Mi)",
                        "count": 3,
                        "lastTimestamp": datetime.now(timezone.utc).isoformat(),
                    }
                ]
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        {
            "type": "pods",
            "data": {
                "items": [
                    {
                        "metadata": {"name": "demo-app-abc"},
                        "status": {
                            "phase": "Running",
                            "reason": "OOMKilled",
                            "containerStatuses": [
                                {
                                    "name": "demo-app",
                                    "state": {"terminated": {"exitCode": 137}},
                                    "restartCount": 5,
                                }
                            ],
                        },
                    },
                    {
                        "metadata": {"name": "demo-app-def"},
                        "status": {"phase": "Running"},
                    },
                ]
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    ]

    logger.info(f"\n🔍 Step 2: Context Gathered")
    logger.info(f"   Observations: {len(state['observations'])}")
    logger.info(f"   - Events: OOMKilled detected (3 occurrences)")
    logger.info(f"   - Pods: 2 pods (1 OOMKilled, 1 Running)")

    # Step 3: Diagnose
    diagnosed = await diagnose_node(state)
    primary_hypothesis = diagnosed["hypotheses"][0] if diagnosed["hypotheses"] else {}

    logger.info(f"\n🩺 Step 3: Diagnosis Complete")
    logger.info(f"   Primary Hypothesis: {primary_hypothesis.get('cause', 'Unknown')}")
    logger.info(f"   Confidence: {primary_hypothesis.get('confidence', 0):.0%}")
    logger.info(f"   Suggested Actions: {', '.join(primary_hypothesis.get('suggested_actions', []))}")
    logger.info(f"   Risk Score: {diagnosed['risk_score']:.2f}")

    # Step 4: Plan
    planned = await plan_node(diagnosed)

    logger.info(f"\n📋 Step 4: Remediation Plan Created")
    logger.info(f"   Plan ID: {planned['plan']['id']}")
    logger.info(f"   Actions: {len(planned['plan']['actions'])}")
    for i, action in enumerate(planned["plan"]["actions"], 1):
        logger.info(f"   {i}. {action['type']} (risk: {action['risk_level']})")
        logger.info(f"      Target: {action['target']}")
    logger.info(f"   Auto-approvable: {planned['plan']['auto_approvable']}")

    # Step 5: Approval
    approved = await approval_node(planned)

    if approved["status"] == WorkflowStatus.PENDING_APPROVAL:
        logger.info(f"\n⏸️  Step 5: Approval Required (HITL)")
        logger.info(f"   Reason: Prod namespace or high risk")
        logger.info(f"   Action: Auto-approved (staging, risk < threshold)")

        # Simulate approval decision
        approved["status"] = WorkflowStatus.EXECUTING
        approved["approval_decision"] = {
            "approved": True,
            "auto": True,
            "reason": "Low risk staging environment",
        }

    logger.info(f"\n✅ Step 5: Approval Granted")
    logger.info(f"   Status: {approved['status'].value}")
    logger.info(f"   Decision: {'Auto-approved' if approved['approval_decision'].get('auto') else 'Human-approved'}")

    # Step 6: Execute (simulated)
    logger.info(f"\n⚙️  Step 6: Executing Remediation")
    logger.info(f"   Simulating restart of demo-app pods...")

    approved["execution_results"] = [
        {
            "action_id": planned["plan"]["actions"][0]["id"],
            "type": "restart_pod",
            "success": True,
            "output": {"restarted": ["demo-app-abc", "demo-app-def"]},
        }
    ]
    logger.info(f"   ✓ Pod restart: Success")

    # Step 7: Verify (simulated)
    logger.info(f"\n🔬 Step 7: Verifying Recovery")
    logger.info(f"   Checking pod health...")

    # Simulate healthy pods after restart
    verified = await verify_node(approved)
    if verified["status"] == WorkflowStatus.RESOLVED:
        logger.info(f"   ✓ All pods are Running and Ready")
        logger.info(f"   ✓ Incident RESOLVED")
    else:
        logger.info(f"   ✗ Verification failed - needs escalation")

    # Step 8: Report
    report = await report_node(verified)

    logger.info(f"\n📝 Step 8: Report Generated")
    logger.info(f"   Report ID: {report['report']['id']}")
    logger.info(f"   Summary:")
    print(report["report"]["summary"])

    # Final Summary
    logger.info(f"\n" + "=" * 60)
    logger.info("📊 INCIDENT SUMMARY")
    logger.info("=" * 60)
    logger.info(f"   Incident ID: {state['incident_id']}")
    logger.info(f"   Fingerprint: {state['fingerprint']}")
    logger.info(f"   Severity: {state['severity']}")
    logger.info(f"   Duration: ~{state['incident_id'].split('-')[-1]} (simulated)")
    logger.info(f"   Root Cause: {report['report']['root_cause']}")
    logger.info(f"   Status: {report['report']['status']}")
    logger.info(f"   Actions Taken: {len(report['report']['actions_taken'])}")
    logger.info("=" * 60)
    logger.info("✅ Demo complete!")


if __name__ == "__main__":
    asyncio.run(simulate_oomkilled_incident())
