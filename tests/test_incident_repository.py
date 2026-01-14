"""TDD: Tests for incident repository.

RED PHASE: Write tests first for async database operations.
"""

import pytest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.db.models import (
    IncidentStatus,
    Severity,
    IncidentCreate,
    Incident,
    TimelineEvent,
    TimelineEventType,
    ToolCall,
    Hypothesis,
    RemediationPlan,
    RemediationAction,
    ActionType,
    RiskLevel,
    Approval,
    ApprovalStatus,
)
from src.db.repository import IncidentRepository, RepositoryConfig


class MockPool:
    """Mock asyncpg pool with proper async context manager."""

    def __init__(self, conn: AsyncMock):
        self._conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self._conn


class TestIncidentRepository:
    """Tests for IncidentRepository CRUD operations."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock database connection pool."""
        conn = AsyncMock()
        pool = MockPool(conn)
        return pool, conn

    @pytest.fixture
    def repo(self, mock_pool):
        """Create repository with mocked pool."""
        pool, _ = mock_pool
        repo = IncidentRepository(RepositoryConfig())
        repo._pool = pool
        return repo

    @pytest.mark.asyncio
    async def test_create_incident(self, repo, mock_pool):
        """Test creating a new incident."""
        _, conn = mock_pool
        incident_id = "123e4567-e89b-12d3-a456-426614174000"
        now = datetime.now(timezone.utc)

        # Mock the database response
        conn.fetchrow.return_value = {
            "id": incident_id,
            "title": "Pod CrashLoopBackOff",
            "description": None,
            "severity": "high",
            "status": "open",
            "fingerprint": "CrashLoop:prod:demo-app",
            "namespace": "prod",
            "affected_service": "demo-app",
            "alert_labels": {},
            "risk_score": 0.0,
            "thread_id": None,
            "created_at": now,
            "updated_at": now,
            "resolved_at": None,
        }

        incident_create = IncidentCreate(
            title="Pod CrashLoopBackOff",
            severity=Severity.HIGH,
            fingerprint="CrashLoop:prod:demo-app",
            namespace="prod",
            affected_service="demo-app",
        )

        result = await repo.create_incident(incident_create)

        assert result.id == incident_id
        assert result.status == IncidentStatus.OPEN
        assert result.severity == Severity.HIGH
        conn.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_incident_by_id(self, repo, mock_pool):
        """Test getting incident by ID."""
        _, conn = mock_pool
        incident_id = "123e4567-e89b-12d3-a456-426614174000"
        now = datetime.now(timezone.utc)

        conn.fetchrow.return_value = {
            "id": incident_id,
            "title": "OOMKilled",
            "description": "Memory exhaustion",
            "severity": "critical",
            "status": "investigating",
            "fingerprint": "OOMKilled:prod:api",
            "namespace": "prod",
            "affected_service": "api",
            "alert_labels": {},
            "risk_score": 0.5,
            "thread_id": "thread-123",
            "created_at": now,
            "updated_at": now,
            "resolved_at": None,
        }

        result = await repo.get_incident(incident_id)

        assert result is not None
        assert result.id == incident_id
        assert result.status == IncidentStatus.INVESTIGATING

    @pytest.mark.asyncio
    async def test_get_incident_not_found(self, repo, mock_pool):
        """Test getting non-existent incident."""
        _, conn = mock_pool
        conn.fetchrow.return_value = None

        result = await repo.get_incident("nonexistent-id")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_incident_by_fingerprint(self, repo, mock_pool):
        """Test finding incident by fingerprint (dedup check)."""
        _, conn = mock_pool
        now = datetime.now(timezone.utc)
        fingerprint = "CrashLoop:prod:demo-app"

        conn.fetchrow.return_value = {
            "id": "123e4567-e89b-12d3-a456-426614174000",
            "title": "Pod CrashLoopBackOff",
            "description": None,
            "severity": "high",
            "status": "open",
            "fingerprint": fingerprint,
            "namespace": "prod",
            "affected_service": "demo-app",
            "alert_labels": {},
            "risk_score": 0.0,
            "thread_id": None,
            "created_at": now,
            "updated_at": now,
            "resolved_at": None,
        }

        result = await repo.get_incident_by_fingerprint(fingerprint)

        assert result is not None
        assert result.fingerprint == fingerprint

    @pytest.mark.asyncio
    async def test_update_incident_status(self, repo, mock_pool):
        """Test updating incident status."""
        _, conn = mock_pool
        incident_id = "123e4567-e89b-12d3-a456-426614174000"
        now = datetime.now(timezone.utc)

        conn.fetchrow.return_value = {
            "id": incident_id,
            "title": "Pod CrashLoopBackOff",
            "description": None,
            "severity": "high",
            "status": "investigating",
            "fingerprint": "CrashLoop:prod:demo-app",
            "namespace": "prod",
            "affected_service": "demo-app",
            "alert_labels": {},
            "risk_score": 0.0,
            "thread_id": None,
            "created_at": now,
            "updated_at": now,
            "resolved_at": None,
        }

        result = await repo.update_incident_status(
            incident_id, IncidentStatus.INVESTIGATING
        )

        assert result.status == IncidentStatus.INVESTIGATING

    @pytest.mark.asyncio
    async def test_list_active_incidents(self, repo, mock_pool):
        """Test listing active (non-resolved) incidents."""
        _, conn = mock_pool
        now = datetime.now(timezone.utc)

        conn.fetch.return_value = [
            {
                "id": "incident-1",
                "title": "Incident 1",
                "description": None,
                "severity": "high",
                "status": "open",
                "fingerprint": "fp-1",
                "namespace": "prod",
                "affected_service": "svc-1",
                "alert_labels": {},
                "risk_score": 0.0,
                "thread_id": None,
                "created_at": now,
                "updated_at": now,
                "resolved_at": None,
            },
            {
                "id": "incident-2",
                "title": "Incident 2",
                "description": None,
                "severity": "critical",
                "status": "investigating",
                "fingerprint": "fp-2",
                "namespace": "prod",
                "affected_service": "svc-2",
                "alert_labels": {},
                "risk_score": 0.5,
                "thread_id": None,
                "created_at": now,
                "updated_at": now,
                "resolved_at": None,
            },
        ]

        result = await repo.list_active_incidents()

        assert len(result) == 2
        assert result[0].status == IncidentStatus.OPEN
        assert result[1].status == IncidentStatus.INVESTIGATING


class TestTimelineRepository:
    """Tests for timeline event operations."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock database connection pool."""
        conn = AsyncMock()
        pool = MockPool(conn)
        return pool, conn

    @pytest.fixture
    def repo(self, mock_pool):
        """Create repository with mocked pool."""
        pool, _ = mock_pool
        repo = IncidentRepository(RepositoryConfig())
        repo._pool = pool
        return repo

    @pytest.mark.asyncio
    async def test_add_timeline_event(self, repo, mock_pool):
        """Test adding a timeline event."""
        _, conn = mock_pool
        incident_id = "123e4567-e89b-12d3-a456-426614174000"
        now = datetime.now(timezone.utc)

        conn.fetchrow.return_value = {
            "id": "event-1",
            "incident_id": incident_id,
            "event_type": "status_changed",
            "description": "Status changed to investigating",
            "metadata": {"old": "open", "new": "investigating"},
            "actor": "agent",
            "created_at": now,
        }

        result = await repo.add_timeline_event(
            incident_id=incident_id,
            event_type=TimelineEventType.STATUS_CHANGED,
            description="Status changed to investigating",
            metadata={"old": "open", "new": "investigating"},
        )

        assert result.event_type == TimelineEventType.STATUS_CHANGED
        assert result.incident_id == incident_id

    @pytest.mark.asyncio
    async def test_get_incident_timeline(self, repo, mock_pool):
        """Test getting all timeline events for an incident."""
        _, conn = mock_pool
        incident_id = "123e4567-e89b-12d3-a456-426614174000"
        now = datetime.now(timezone.utc)

        conn.fetch.return_value = [
            {
                "id": "event-1",
                "incident_id": incident_id,
                "event_type": "created",
                "description": "Incident created",
                "metadata": {},
                "actor": "agent",
                "created_at": now,
            },
            {
                "id": "event-2",
                "incident_id": incident_id,
                "event_type": "status_changed",
                "description": "Status changed",
                "metadata": {},
                "actor": "agent",
                "created_at": now,
            },
        ]

        result = await repo.get_incident_timeline(incident_id)

        assert len(result) == 2
        assert result[0].event_type == TimelineEventType.CREATED


class TestToolCallRepository:
    """Tests for tool call audit operations."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock database connection pool."""
        conn = AsyncMock()
        pool = MockPool(conn)
        return pool, conn

    @pytest.fixture
    def repo(self, mock_pool):
        """Create repository with mocked pool."""
        pool, _ = mock_pool
        repo = IncidentRepository(RepositoryConfig())
        repo._pool = pool
        return repo

    @pytest.mark.asyncio
    async def test_log_tool_call(self, repo, mock_pool):
        """Test logging a tool call."""
        _, conn = mock_pool
        incident_id = "123e4567-e89b-12d3-a456-426614174000"
        now = datetime.now(timezone.utc)

        conn.fetchrow.return_value = {
            "id": "tool-call-1",
            "incident_id": incident_id,
            "tool_name": "kubectl_get_pods",
            "input_params": {"namespace": "prod"},
            "output_summary": "Found 2 pods",
            "full_output": None,
            "duration_ms": 150,
            "success": True,
            "error_message": None,
            "created_at": now,
        }

        result = await repo.log_tool_call(
            incident_id=incident_id,
            tool_name="kubectl_get_pods",
            input_params={"namespace": "prod"},
            output_summary="Found 2 pods",
            duration_ms=150,
            success=True,
        )

        assert result.tool_name == "kubectl_get_pods"
        assert result.success is True
        assert result.duration_ms == 150


class TestApprovalRepository:
    """Tests for approval operations."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock database connection pool."""
        conn = AsyncMock()
        pool = MockPool(conn)
        return pool, conn

    @pytest.fixture
    def repo(self, mock_pool):
        """Create repository with mocked pool."""
        pool, _ = mock_pool
        repo = IncidentRepository(RepositoryConfig())
        repo._pool = pool
        return repo

    @pytest.mark.asyncio
    async def test_create_approval_request(self, repo, mock_pool):
        """Test creating an approval request."""
        _, conn = mock_pool
        incident_id = "123e4567-e89b-12d3-a456-426614174000"
        plan_id = "plan-1"
        now = datetime.now(timezone.utc)

        conn.fetchrow.return_value = {
            "id": "approval-1",
            "incident_id": incident_id,
            "plan_id": plan_id,
            "action_summary": "Restart pod demo-app",
            "risk_score": 0.3,
            "status": "pending",
            "approver": None,
            "reason": None,
            "auto_approve_eligible": True,
            "expires_at": None,
            "created_at": now,
            "decided_at": None,
        }

        result = await repo.create_approval(
            incident_id=incident_id,
            plan_id=plan_id,
            action_summary="Restart pod demo-app",
            risk_score=0.3,
            auto_approve_eligible=True,
        )

        assert result.status == ApprovalStatus.PENDING
        assert result.auto_approve_eligible is True

    @pytest.mark.asyncio
    async def test_approve_request(self, repo, mock_pool):
        """Test approving a request."""
        _, conn = mock_pool
        approval_id = "approval-1"
        now = datetime.now(timezone.utc)

        conn.fetchrow.return_value = {
            "id": approval_id,
            "incident_id": "incident-1",
            "plan_id": "plan-1",
            "action_summary": "Restart pod demo-app",
            "risk_score": 0.3,
            "status": "approved",
            "approver": "john@example.com",
            "reason": "Approved based on analysis",
            "auto_approve_eligible": False,
            "expires_at": None,
            "created_at": now,
            "decided_at": now,
        }

        result = await repo.update_approval(
            approval_id=approval_id,
            status=ApprovalStatus.APPROVED,
            approver="john@example.com",
            reason="Approved based on analysis",
        )

        assert result.status == ApprovalStatus.APPROVED
        assert result.approver == "john@example.com"

    @pytest.mark.asyncio
    async def test_get_pending_approvals(self, repo, mock_pool):
        """Test getting all pending approvals."""
        _, conn = mock_pool
        now = datetime.now(timezone.utc)

        conn.fetch.return_value = [
            {
                "id": "approval-1",
                "incident_id": "incident-1",
                "plan_id": "plan-1",
                "action_summary": "Restart pod",
                "risk_score": 0.3,
                "status": "pending",
                "approver": None,
                "reason": None,
                "auto_approve_eligible": True,
                "expires_at": None,
                "created_at": now,
                "decided_at": None,
            },
        ]

        result = await repo.get_pending_approvals()

        assert len(result) == 1
        assert result[0].status == ApprovalStatus.PENDING


class TestIncidentDedup:
    """Tests for incident deduplication logic."""

    @pytest.fixture
    def mock_pool(self):
        """Create a mock database connection pool."""
        conn = AsyncMock()
        pool = MockPool(conn)
        return pool, conn

    @pytest.fixture
    def repo(self, mock_pool):
        """Create repository with mocked pool."""
        pool, _ = mock_pool
        repo = IncidentRepository(RepositoryConfig())
        repo._pool = pool
        return repo

    @pytest.mark.asyncio
    async def test_find_or_create_returns_existing(self, repo, mock_pool):
        """Test find_or_create returns existing incident for same fingerprint."""
        _, conn = mock_pool
        fingerprint = "CrashLoop:prod:demo-app"
        existing_id = "existing-incident-id"
        now = datetime.now(timezone.utc)

        # First call returns existing incident
        conn.fetchrow.return_value = {
            "id": existing_id,
            "title": "Existing Incident",
            "description": None,
            "severity": "high",
            "status": "investigating",
            "fingerprint": fingerprint,
            "namespace": "prod",
            "affected_service": "demo-app",
            "alert_labels": {},
            "risk_score": 0.0,
            "thread_id": None,
            "created_at": now,
            "updated_at": now,
            "resolved_at": None,
        }

        incident_create = IncidentCreate(
            title="New Incident",
            severity=Severity.HIGH,
            fingerprint=fingerprint,
        )

        result, created = await repo.find_or_create_incident(incident_create)

        assert result.id == existing_id
        assert created is False  # Not created, returned existing

    @pytest.mark.asyncio
    async def test_find_or_create_creates_new(self, repo, mock_pool):
        """Test find_or_create creates new incident when none exists."""
        _, conn = mock_pool
        fingerprint = "NewFingerprint:prod:app"
        new_id = "new-incident-id"
        now = datetime.now(timezone.utc)

        # First call for lookup returns None
        conn.fetchrow.side_effect = [
            None,  # No existing incident
            {  # Newly created incident
                "id": new_id,
                "title": "New Incident",
                "description": None,
                "severity": "high",
                "status": "open",
                "fingerprint": fingerprint,
                "namespace": "prod",
                "affected_service": "app",
                "alert_labels": {},
                "risk_score": 0.0,
                "thread_id": None,
                "created_at": now,
                "updated_at": now,
                "resolved_at": None,
            },
        ]

        incident_create = IncidentCreate(
            title="New Incident",
            severity=Severity.HIGH,
            fingerprint=fingerprint,
            namespace="prod",
            affected_service="app",
        )

        result, created = await repo.find_or_create_incident(incident_create)

        assert result.id == new_id
        assert created is True  # New incident created
