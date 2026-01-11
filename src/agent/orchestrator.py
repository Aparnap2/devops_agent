"""Main agent orchestrator using LangGraph."""

import logging
import uuid
from datetime import datetime
from typing import Any

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command

from src.agent.state import AgentState, create_initial_state
from src.context_stores.redis_store import RedisContextStore
from src.context_stores.neo4j_store import Neo4jContextStore
from src.context_stores.vector_store import VectorContextStore
from src.execution.execution_manager import ExecutionManager
from src.ingestion.ingestion_manager import IngestionManager
from src.types.state import (
    Anomaly,
    Incident,
    IncidentStatus,
    RemediationAction,
    RemediationPlan,
    RootCause,
    Severity,
    Signal,
)

logger = logging.getLogger(__name__)


class DevOpsAgent:
    """Main DevOps/SRE Agent orchestrator using LangGraph."""

    def __init__(
        self,
        redis_store: RedisContextStore | None = None,
        neo4j_store: Neo4jContextStore | None = None,
        vector_store: VectorContextStore | None = None,
        execution_manager: ExecutionManager | None = None,
        ingestion_manager: IngestionManager | None = None,
    ) -> None:
        """Initialize the DevOps agent."""
        self.redis = redis_store or RedisContextStore()
        self.neo4j = neo4j_store or Neo4jContextStore()
        self.vector = vector_store or VectorContextStore()
        self.execution = execution_manager or ExecutionManager()
        self.ingestion = ingestion_manager or IngestionManager()

        self._graph: StateGraph | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize all components and build the graph."""
        if self._initialized:
            return

        # Connect to stores
        await self.redis.connect()
        await self.neo4j.connect()
        await self.vector.connect()

        # Initialize execution and ingestion
        await self.execution.initialize()
        self.ingestion.create_default_ingestors()
        await self.ingestion.start()

        # Build the LangGraph
        self._build_graph()

        self._initialized = True
        logger.info("DevOps Agent initialized")

    async def shutdown(self) -> None:
        """Shutdown all components."""
        await self.ingestion.stop()
        await self.execution.shutdown()
        await self.redis.disconnect()
        await self.neo4j.disconnect()
        await self.vector.disconnect()
        self._initialized = False
        logger.info("DevOps Agent shut down")

    def _build_graph(self) -> None:
        """Build the LangGraph workflow."""
        workflow = StateGraph(AgentState)

        # Add nodes
        workflow.add_node("ingest_signals", self._ingest_signals_node)
        workflow.add_node("detect_anomalies", self._detect_anomalies_node)
        workflow.add_node("analyze_root_cause", self._analyze_root_cause_node)
        workflow.add_node("plan_remediation", self._plan_remediation_node)
        workflow.add_node("execute_remediation", self._execute_remediation_node)
        workflow.add_node("record_feedback", self._record_feedback_node)
        workflow.add_node("escalate_incident", self._escalate_incident_node)

        # Define edges
        workflow.add_edge(START, "ingest_signals")
        workflow.add_edge("ingest_signals", "detect_anomalies")
        workflow.add_edge("detect_anomalies", "analyze_root_cause")

        # Conditional routing based on anomalies
        workflow.add_conditional_edges(
            "detect_anomalies",
            self._should_escalate,
            {
                "escalate": "escalate_incident",
                "continue": "analyze_root_cause",
            },
        )

        workflow.add_edge("analyze_root_cause", "plan_remediation")
        workflow.add_edge("plan_remediation", "execute_remediation")
        workflow.add_edge("execute_remediation", "record_feedback")
        workflow.add_edge("record_feedback", "ingest_signals")

        self._graph = workflow.compile()

    # Node implementations

    async def _ingest_signals_node(self, state: AgentState) -> AgentState:
        """Ingest signals from all sources."""
        logger.info("Ingesting signals...")

        signals = await self.ingestion.fetch_all_signals()

        return {
            **state,
            "signals": signals,
            "current_step": "ingest_signals",
            "last_updated": datetime.utcnow(),
        }

    async def _detect_anomalies_node(self, state: AgentState) -> AgentState:
        """Detect anomalies from signals."""
        logger.info("Detecting anomalies from %d signals...", len(state["signals"]))

        anomalies: list[Anomaly] = []

        for signal in state["signals"]:
            # Simple anomaly detection logic (in production, use ML models)
            anomaly = self._check_for_anomaly(signal)
            if anomaly:
                anomalies.append(anomaly)

                # Cache the signal
                await self.redis.cache_signal(signal.id, signal.model_dump())

        return {
            **state,
            "anomalies": anomalies,
            "current_step": "detect_anomalies",
            "last_updated": datetime.utcnow(),
        }

    def _check_for_anomaly(self, signal: Signal) -> Anomaly | None:
        """Check if a signal indicates an anomaly."""
        raw = signal.raw_content

        # Check for error logs
        if signal.type.value == "log":
            level = raw.get("level", "").upper()
            if level in ["ERROR", "CRITICAL"]:
                return Anomaly(
                    id=f"anomaly-{signal.id}",
                    signal_id=signal.id,
                    severity=Severity.HIGH if level == "ERROR" else Severity.CRITICAL,
                    confidence=0.85,
                    description=f"Error log detected in {signal.service}",
                    affected_metrics=["error_rate"],
                )

        # Check for anomalous metrics
        if signal.type.value == "metric":
            if raw.get("is_anomaly"):
                return Anomaly(
                    id=f"anomaly-{signal.id}",
                    signal_id=signal.id,
                    severity=Severity.MEDIUM,
                    confidence=raw.get("confidence", 0.7),
                    description=raw.get("anomaly_reason", "Anomalous metric value"),
                    affected_metrics=[raw.get("metric_name", "unknown")],
                )

        # Check for error traces
        if signal.type.value == "trace":
            if raw.get("trace_type") == "error":
                return Anomaly(
                    id=f"anomaly-{signal.id}",
                    signal_id=signal.id,
                    severity=Severity.HIGH,
                    confidence=0.9,
                    description=f"Error trace in {signal.service}: {raw.get('operation', 'unknown')}",
                    affected_metrics=["error_rate", "latency"],
                )

        return None

    async def _analyze_root_cause_node(self, state: AgentState) -> AgentState:
        """Analyze root causes for anomalies."""
        logger.info("Analyzing root causes for %d anomalies...", len(state["anomalies"]))

        root_causes: list[RootCause] = []

        for anomaly in state["anomalies"]:
            # Get signal and service context
            signal = await self.redis.get_cached_signal(anomaly.signal_id)

            # Query service dependency graph
            if signal:
                impact_chain = await self.neo4j.get_impact_chain(signal.service)

                root_cause = RootCause(
                    id=f"rca-{anomaly.id}",
                    anomaly_id=anomaly.id,
                    probable_cause=self._infer_root_cause(anomaly, signal),
                    affected_services=impact_chain.get("all_affected", [signal.service]),
                    related_signals=[anomaly.signal_id],
                    confidence=anomaly.confidence * 0.9,
                    evidence=[
                        {"type": "anomaly", "data": anomaly.model_dump()},
                        {"type": "impact_chain", "data": impact_chain},
                    ],
                )
                root_causes.append(root_cause)

        return {
            **state,
            "root_causes": root_causes,
            "current_step": "analyze_root_cause",
            "last_updated": datetime.utcnow(),
        }

    def _infer_root_cause(self, anomaly: Anomaly, signal: Signal) -> str:
        """Infer root cause based on anomaly and signal data."""
        signal_type = signal.type.value

        if signal_type == "log":
            level = signal.raw_content.get("level", "").upper()
            if level == "CRITICAL":
                return "Critical system failure - immediate attention required"
            return "Application error - likely code or configuration issue"

        if signal_type == "metric":
            metric = signal.raw_content.get("metric_name", "unknown")
            if "restarts" in metric:
                return "Container instability - frequent restarts detected"
            if "memory" in metric:
                return "Resource exhaustion - memory pressure"
            if "cpu" in metric:
                return "Resource exhaustion - high CPU usage"

        if signal_type == "trace":
            if signal.raw_content.get("trace_type") == "error":
                return "Application error trace - investigation needed"

        return "Unknown cause - requires manual investigation"

    async def _plan_remediation_node(self, state: AgentState) -> AgentState:
        """Create remediation plans for detected issues."""
        logger.info("Planning remediation...")

        if not state["root_causes"]:
            return {**state, "remediation_plan": None}

        # Get the most severe root cause
        root_cause = max(
            state["root_causes"],
            key=lambda rc: (rc.confidence, len(rc.affected_services)),
        )

        # Generate remediation actions
        actions = self._generate_remediation_actions(root_cause)

        # Calculate risk score
        total_risk = sum(
            {"low": 0.2, "medium": 0.5, "high": 0.8}.get(a.risk_level, 0.5)
            for a in actions
        )
        auto_approvable = all(a.risk_level == "low" for a in actions)

        remediation_plan = RemediationPlan(
            id=f"plan-{uuid.uuid4().hex[:8]}",
            incident_id=state["current_incident"].id if state["current_incident"] else "",
            actions=actions,
            total_risk_score=total_risk,
            auto_approvable=auto_approvable,
        )

        return {
            **state,
            "remediation_plan": remediation_plan,
            "current_step": "plan_remediation",
            "last_updated": datetime.utcnow(),
        }

    def _generate_remediation_actions(self, root_cause: RootCause) -> list[RemediationAction]:
        """Generate remediation actions for a root cause."""
        actions: list[RemediationAction] = []
        service = root_cause.affected_services[0] if root_cause.affected_services else "unknown"

        # Generate actions based on probable cause keywords
        cause = root_cause.probable_cause.lower()

        if "restart" in cause or "instability" in cause:
            actions.append(
                RemediationAction(
                    id=f"action-{uuid.uuid4().hex[:8]}",
                    type="restart_deployment",
                    target=service,
                    parameters={"namespace": "default"},
                    risk_level="medium",
                    estimated_impact="Brief service interruption",
                    requires_approval=True,
                )
            )

        if "memory" in cause or "resource" in cause:
            actions.append(
                RemediationAction(
                    id=f"action-{uuid.uuid4().hex[:8]}",
                    type="scale_deployment",
                    target=service,
                    parameters={"replicas": 2},
                    risk_level="low",
                    estimated_impact="Increased resource usage",
                    requires_approval=False,
                )
            )

        if "error" in cause:
            actions.append(
                RemediationAction(
                    id=f"action-{uuid.uuid4().hex[:8]}",
                    type="restart_pod",
                    target=f"{service}-pod-*",  # Pattern for random pod restart
                    parameters={"namespace": "default"},
                    risk_level="low",
                    estimated_impact="Minimal - single pod restart",
                    requires_approval=False,
                )
            )

        return actions

    async def _execute_remediation_node(self, state: AgentState) -> AgentState:
        """Execute the remediation plan."""
        logger.info("Executing remediation...")

        plan = state["remediation_plan"]
        if not plan:
            return {**state, "execution_results": []}

        require_approval = not plan.auto_approvable
        results = await self.execution.execute_plan(plan.actions, require_approval)

        # Update incident status based on results
        incident = state["current_incident"]
        if incident:
            if all(r.success for r in results):
                incident.status = IncidentStatus.RESOLVED
            else:
                incident.status = IncidentStatus.REMEDIATING

        return {
            **state,
            "execution_results": [r.model_dump() for r in results],
            "current_incident": incident,
            "current_step": "execute_remediation",
            "last_updated": datetime.utcnow(),
        }

    async def _record_feedback_node(self, state: AgentState) -> AgentState:
        """Record feedback for learning."""
        logger.info("Recording feedback...")

        # In production, this would store feedback for ML training
        return {
            **state,
            "current_step": "record_feedback",
            "last_updated": datetime.utcnow(),
        }

    async def _escalate_incident_node(self, state: AgentState) -> AgentState:
        """Escalate an incident to humans."""
        logger.info("Escalating incident...")

        # Create or update incident
        if state["anomalies"]:
            most_severe = max(state["anomalies"], key=lambda a: a.severity.value)

            incident = Incident(
                id=f"incident-{uuid.uuid4().hex[:8]}",
                status=IncidentStatus.ESCALATED,
                severity=most_severe.severity,
                title=f"Auto-escalated: {most_severe.description}",
                description=most_severe.description,
                affected_services=[a.signal_id for a in state["anomalies"]],
                anomaly_ids=[a.id for a in state["anomalies"]],
            )

            # Cache incident state
            await self.redis.set_incident_state(incident.id, incident.model_dump())

            return {
                **state,
                "current_incident": incident,
                "current_step": "escalate_incident",
                "last_updated": datetime.utcnow(),
            }

        return {**state, "current_step": "escalate_incident"}

    def _should_escalate(self, state: AgentState) -> str:
        """Determine if escalation is needed."""
        if not state["anomalies"]:
            return "continue"

        # Escalate if any anomaly is critical or high severity
        for anomaly in state["anomalies"]:
            if anomaly.severity in [Severity.CRITICAL, Severity.HIGH]:
                return "escalate"

        return "continue"

    async def run_once(self) -> dict[str, Any]:
        """Run the agent workflow once."""
        if not self._initialized:
            await self.initialize()

        initial_state = create_initial_state()

        final_state = await self._graph.ainvoke(initial_state)

        return final_state

    async def run_continuously(self, interval_seconds: int = 60) -> None:
        """Run the agent workflow continuously."""
        if not self._initialized:
            await self.initialize()

        logger.info("Starting continuous mode with %d second interval", interval_seconds)

        while True:
            try:
                await self.run_once()
            except Exception as e:
                logger.error("Error in agent loop: %s", e)

            await asyncio.sleep(interval_seconds)

    def get_graph_diagram(self) -> str:
        """Get the graph diagram."""
        if self._graph:
            return self._graph.get_graph().draw_mermaid()
        return "Graph not initialized"

    async def health_check(self) -> dict[str, Any]:
        """Check health of all components."""
        return {
            "redis": await self.redis.health_check(),
            "neo4j": await self.neo4j.health_check(),
            "vector": await self.vector.health_check(),
            "execution": await self.execution.health_check(),
            "ingestion": await self.ingestion.health_check(),
        }
