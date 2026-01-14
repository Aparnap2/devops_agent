"""Async repository for incident store operations.

Implements data access patterns with asyncpg for Postgres.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from src.db.models import (
    ApprovalStatus,
    Incident,
    IncidentCreate,
    IncidentStatus,
    Severity,
    TimelineEvent,
    TimelineEventType,
    ToolCall,
    Approval,
)

logger = logging.getLogger(__name__)


class RepositoryConfig(BaseModel):
    """Configuration for database repository."""

    database_url: str = Field(
        default="postgresql://sre_agent:sre_agent@localhost:5432/sre_agent"
    )
    min_pool_size: int = 2
    max_pool_size: int = 10


class IncidentRepository:
    """Async repository for incident CRUD operations."""

    def __init__(self, config: Optional[RepositoryConfig] = None) -> None:
        """Initialize repository with config."""
        self._config = config or RepositoryConfig()
        self._pool = None

    async def initialize(self) -> None:
        """Initialize database connection pool."""
        try:
            import asyncpg

            self._pool = await asyncpg.create_pool(
                self._config.database_url,
                min_size=self._config.min_pool_size,
                max_size=self._config.max_pool_size,
            )
            logger.info("Database connection pool initialized")
        except Exception as e:
            logger.error(f"Failed to initialize database pool: {e}")
            raise

    async def close(self) -> None:
        """Close database connection pool."""
        if self._pool:
            await self._pool.close()
            logger.info("Database connection pool closed")

    # =========================================================================
    # INCIDENT OPERATIONS
    # =========================================================================

    async def create_incident(self, incident: IncidentCreate) -> Incident:
        """Create a new incident record."""
        query = """
            INSERT INTO incidents (
                title, description, severity, fingerprint,
                namespace, affected_service, alert_labels
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                incident.title,
                incident.description,
                incident.severity.value,
                incident.fingerprint,
                incident.namespace,
                incident.affected_service,
                json.dumps(incident.alert_labels),
            )
            return self._row_to_incident(row)

    async def get_incident(self, incident_id: str) -> Optional[Incident]:
        """Get incident by ID."""
        query = "SELECT * FROM incidents WHERE id = $1"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, incident_id)
            return self._row_to_incident(row) if row else None

    async def get_incident_by_fingerprint(
        self, fingerprint: str
    ) -> Optional[Incident]:
        """Get incident by fingerprint for dedup check."""
        query = """
            SELECT * FROM incidents
            WHERE fingerprint = $1
            AND status NOT IN ('resolved', 'aborted')
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, fingerprint)
            return self._row_to_incident(row) if row else None

    async def find_or_create_incident(
        self, incident: IncidentCreate
    ) -> tuple[Incident, bool]:
        """Find existing incident by fingerprint or create new one.

        Returns:
            Tuple of (incident, created) where created is True if new.
        """
        # Check for existing
        existing = await self.get_incident_by_fingerprint(incident.fingerprint)
        if existing:
            return existing, False

        # Create new
        new_incident = await self.create_incident(incident)
        return new_incident, True

    async def update_incident_status(
        self, incident_id: str, status: IncidentStatus
    ) -> Incident:
        """Update incident status."""
        query = """
            UPDATE incidents
            SET status = $2, updated_at = NOW()
            WHERE id = $1
            RETURNING *
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, incident_id, status.value)
            return self._row_to_incident(row)

    async def update_incident_risk_score(
        self, incident_id: str, risk_score: float
    ) -> Incident:
        """Update incident risk score."""
        query = """
            UPDATE incidents
            SET risk_score = $2, updated_at = NOW()
            WHERE id = $1
            RETURNING *
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, incident_id, risk_score)
            return self._row_to_incident(row)

    async def resolve_incident(self, incident_id: str) -> Incident:
        """Mark incident as resolved."""
        query = """
            UPDATE incidents
            SET status = 'resolved', resolved_at = NOW(), updated_at = NOW()
            WHERE id = $1
            RETURNING *
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, incident_id)
            return self._row_to_incident(row)

    async def list_active_incidents(self) -> list[Incident]:
        """List all active (non-resolved) incidents."""
        query = """
            SELECT * FROM incidents
            WHERE status NOT IN ('resolved', 'aborted')
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    ELSE 4
                END,
                created_at DESC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [self._row_to_incident(row) for row in rows]

    def _row_to_incident(self, row: dict) -> Incident:
        """Convert database row to Incident model."""
        return Incident(
            id=str(row["id"]),
            title=row["title"],
            description=row["description"],
            severity=Severity(row["severity"]),
            status=IncidentStatus(row["status"]),
            fingerprint=row["fingerprint"],
            namespace=row["namespace"],
            affected_service=row["affected_service"],
            alert_labels=row["alert_labels"] if isinstance(row["alert_labels"], dict) else {},
            risk_score=float(row["risk_score"]) if row["risk_score"] else 0.0,
            thread_id=row["thread_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            resolved_at=row["resolved_at"],
        )

    # =========================================================================
    # TIMELINE OPERATIONS
    # =========================================================================

    async def add_timeline_event(
        self,
        incident_id: str,
        event_type: TimelineEventType,
        description: Optional[str] = None,
        metadata: Optional[dict] = None,
        actor: str = "agent",
    ) -> TimelineEvent:
        """Add a timeline event to an incident."""
        query = """
            INSERT INTO timeline (
                incident_id, event_type, description, metadata, actor
            ) VALUES ($1, $2, $3, $4, $5)
            RETURNING *
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                incident_id,
                event_type.value,
                description,
                json.dumps(metadata or {}),
                actor,
            )
            return self._row_to_timeline_event(row)

    async def get_incident_timeline(
        self, incident_id: str
    ) -> list[TimelineEvent]:
        """Get all timeline events for an incident."""
        query = """
            SELECT * FROM timeline
            WHERE incident_id = $1
            ORDER BY created_at ASC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, incident_id)
            return [self._row_to_timeline_event(row) for row in rows]

    def _row_to_timeline_event(self, row: dict) -> TimelineEvent:
        """Convert database row to TimelineEvent model."""
        return TimelineEvent(
            id=str(row["id"]),
            incident_id=str(row["incident_id"]),
            event_type=TimelineEventType(row["event_type"]),
            description=row["description"],
            metadata=row["metadata"] if isinstance(row["metadata"], dict) else {},
            actor=row["actor"],
            created_at=row["created_at"],
        )

    # =========================================================================
    # TOOL CALL OPERATIONS
    # =========================================================================

    async def log_tool_call(
        self,
        tool_name: str,
        input_params: dict,
        incident_id: Optional[str] = None,
        output_summary: Optional[str] = None,
        full_output: Optional[dict] = None,
        duration_ms: int = 0,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> ToolCall:
        """Log a tool call for audit."""
        query = """
            INSERT INTO tool_calls (
                incident_id, tool_name, input_params, output_summary,
                full_output, duration_ms, success, error_message
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING *
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                incident_id,
                tool_name,
                json.dumps(input_params),
                output_summary,
                json.dumps(full_output) if full_output else None,
                duration_ms,
                success,
                error_message,
            )
            return self._row_to_tool_call(row)

    async def get_incident_tool_calls(
        self, incident_id: str
    ) -> list[ToolCall]:
        """Get all tool calls for an incident."""
        query = """
            SELECT * FROM tool_calls
            WHERE incident_id = $1
            ORDER BY created_at ASC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, incident_id)
            return [self._row_to_tool_call(row) for row in rows]

    def _row_to_tool_call(self, row: dict) -> ToolCall:
        """Convert database row to ToolCall model."""
        return ToolCall(
            id=str(row["id"]),
            incident_id=str(row["incident_id"]) if row["incident_id"] else None,
            tool_name=row["tool_name"],
            input_params=row["input_params"] if isinstance(row["input_params"], dict) else {},
            output_summary=row["output_summary"],
            full_output=row["full_output"] if isinstance(row["full_output"], dict) else None,
            duration_ms=row["duration_ms"] or 0,
            success=row["success"],
            error_message=row["error_message"],
            created_at=row["created_at"],
        )

    # =========================================================================
    # APPROVAL OPERATIONS
    # =========================================================================

    async def create_approval(
        self,
        incident_id: str,
        plan_id: str,
        action_summary: str,
        risk_score: float,
        auto_approve_eligible: bool = False,
        expires_at: Optional[datetime] = None,
    ) -> Approval:
        """Create an approval request."""
        query = """
            INSERT INTO approvals (
                incident_id, plan_id, action_summary, risk_score,
                auto_approve_eligible, expires_at
            ) VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                query,
                incident_id,
                plan_id,
                action_summary,
                risk_score,
                auto_approve_eligible,
                expires_at,
            )
            return self._row_to_approval(row)

    async def get_approval(self, approval_id: str) -> Optional[Approval]:
        """Get approval by ID."""
        query = "SELECT * FROM approvals WHERE id = $1"
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, approval_id)
            return self._row_to_approval(row) if row else None

    async def update_approval(
        self,
        approval_id: str,
        status: ApprovalStatus,
        approver: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Approval:
        """Update approval status."""
        query = """
            UPDATE approvals
            SET status = $2, approver = $3, reason = $4, decided_at = NOW()
            WHERE id = $1
            RETURNING *
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                query, approval_id, status.value, approver, reason
            )
            return self._row_to_approval(row)

    async def get_pending_approvals(self) -> list[Approval]:
        """Get all pending approval requests."""
        query = """
            SELECT * FROM approvals
            WHERE status = 'pending'
            ORDER BY created_at ASC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [self._row_to_approval(row) for row in rows]

    async def get_incident_approvals(self, incident_id: str) -> list[Approval]:
        """Get all approvals for an incident."""
        query = """
            SELECT * FROM approvals
            WHERE incident_id = $1
            ORDER BY created_at ASC
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, incident_id)
            return [self._row_to_approval(row) for row in rows]

    def _row_to_approval(self, row: dict) -> Approval:
        """Convert database row to Approval model."""
        return Approval(
            id=str(row["id"]),
            incident_id=str(row["incident_id"]),
            plan_id=str(row["plan_id"]),
            action_summary=row["action_summary"],
            risk_score=float(row["risk_score"]),
            status=ApprovalStatus(row["status"]),
            approver=row["approver"],
            reason=row["reason"],
            auto_approve_eligible=row["auto_approve_eligible"],
            expires_at=row["expires_at"],
            created_at=row["created_at"],
            decided_at=row["decided_at"],
        )

    # =========================================================================
    # HEALTH CHECK
    # =========================================================================

    async def health_check(self) -> bool:
        """Check database connectivity."""
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False
