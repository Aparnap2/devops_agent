"""Pytest configuration and fixtures."""

import asyncio
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.types.state import (
    Signal,
    SignalType,
    Severity,
    Anomaly,
    Incident,
    IncidentStatus,
    RemediationAction,
    RemediationPlan,
    RootCause,
    ExecutionResult,
)


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_signal() -> Signal:
    """Create a sample signal for testing."""
    return Signal(
        id="test-signal-001",
        type=SignalType.LOG,
        timestamp=datetime.utcnow(),
        source="test",
        service="test-service",
        metadata={"level": "ERROR"},
        raw_content={
            "message": "Connection failed",
            "level": "ERROR",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


@pytest.fixture
def sample_error_signal() -> Signal:
    """Create an error signal for testing."""
    return Signal(
        id="test-error-signal-001",
        type=SignalType.LOG,
        timestamp=datetime.utcnow(),
        source="elasticsearch",
        service="api-service",
        metadata={"level": "ERROR"},
        raw_content={
            "message": "Unhandled exception in handler",
            "level": "ERROR",
            "exception_type": "RuntimeError",
        },
    )


@pytest.fixture
def sample_metric_signal() -> Signal:
    """Create a metric signal for testing."""
    return Signal(
        id="test-metric-signal-001",
        type=SignalType.METRIC,
        timestamp=datetime.utcnow(),
        source="prometheus",
        service="api-service",
        metadata={"metric_family": "http_requests_total"},
        raw_content={
            "metric_name": "http_requests_total",
            "value": 1000.0,
            "labels": {"handler": "/api/users", "method": "GET"},
            "is_anomaly": True,
            "anomaly_reason": "High request rate",
        },
    )


@pytest.fixture
def sample_anomaly() -> Anomaly:
    """Create a sample anomaly for testing."""
    return Anomaly(
        id="test-anomaly-001",
        signal_id="test-signal-001",
        severity=Severity.HIGH,
        confidence=0.85,
        description="High error rate detected",
        affected_metrics=["error_rate"],
    )


@pytest.fixture
def sample_root_cause() -> RootCause:
    """Create a sample root cause for testing."""
    return RootCause(
        id="test-rca-001",
        anomaly_id="test-anomaly-001",
        probable_cause="Database connection pool exhaustion",
        affected_services=["api-service", "user-service"],
        related_signals=["test-signal-001"],
        confidence=0.9,
        evidence=[{"type": "log", "data": {"error": "connection refused"}}],
    )


@pytest.fixture
def sample_remediation_action() -> RemediationAction:
    """Create a sample remediation action for testing."""
    return RemediationAction(
        id="test-action-001",
        type="restart_deployment",
        target="api-service",
        parameters={"namespace": "default"},
        risk_level="medium",
        estimated_impact="Brief service interruption",
        requires_approval=True,
    )


@pytest.fixture
def sample_remediation_plan() -> RemediationPlan:
    """Create a sample remediation plan for testing."""
    action = RemediationAction(
        id="test-action-001",
        type="restart_deployment",
        target="api-service",
        parameters={"namespace": "default"},
        risk_level="medium",
        estimated_impact="Brief service interruption",
        requires_approval=True,
    )
    return RemediationPlan(
        id="test-plan-001",
        incident_id="test-incident-001",
        actions=[action],
        total_risk_score=0.5,
        estimated_duration_seconds=60,
        auto_approvable=False,
    )


@pytest.fixture
def sample_incident() -> Incident:
    """Create a sample incident for testing."""
    return Incident(
        id="test-incident-001",
        status=IncidentStatus.DETECTED,
        severity=Severity.HIGH,
        title="High error rate detected",
        description="Multiple errors detected in api-service",
        affected_services=["api-service"],
        anomaly_ids=["test-anomaly-001"],
    )


@pytest.fixture
def mock_redis_store():
    """Create a mock Redis store."""
    store = MagicMock()
    store.get = AsyncMock(return_value=None)
    store.set = AsyncMock()
    store.delete = AsyncMock()
    store.cache_signal = AsyncMock()
    store.get_cached_signal = AsyncMock(return_value=None)
    store.set_incident_state = AsyncMock()
    store.get_incident_state = AsyncMock(return_value=None)
    store.health_check = AsyncMock(return_value=True)
    return store


@pytest.fixture
def mock_neo4j_store():
    """Create a mock Neo4j store."""
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=[])
    store.get_service_dependencies = AsyncMock(return_value=[])
    store.get_service_dependents = AsyncMock(return_value=[])
    store.get_impact_chain = AsyncMock(return_value={
        "service_id": "test-service",
        "dependencies": [],
        "dependents": [],
        "all_affected": [],
    })
    store.health_check = AsyncMock(return_value=True)
    return store


@pytest.fixture
def mock_vector_store():
    """Create a mock vector store."""
    store = MagicMock()
    store.store_embedding = AsyncMock()
    store.search_similar = AsyncMock(return_value=[])
    store.find_similar_incidents = AsyncMock(return_value=[])
    store.health_check = AsyncMock(return_value=True)
    return store


@pytest.fixture
def mock_execution_manager():
    """Create a mock execution manager."""
    manager = MagicMock()
    manager.execute_action = AsyncMock(return_value=ExecutionResult(
        action_id="test-action",
        success=True,
        output={"action": "test"},
        error_message=None,
        duration_seconds=1.0,
    ))
    manager.execute_plan = AsyncMock(return_value=[])
    manager.dry_run = AsyncMock(return_value={"dry_run": True})
    manager.health_check = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def mock_ingestion_manager():
    """Create a mock ingestion manager."""
    manager = MagicMock()
    manager.fetch_all_signals = AsyncMock(return_value=[])
    manager.health_check = AsyncMock(return_value=True)
    return manager
