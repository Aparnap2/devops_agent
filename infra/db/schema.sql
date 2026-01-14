-- SRE Agent Database Schema
-- PostgreSQL 16+

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- CORE TABLES
-- =============================================================================

-- Incidents table - stores all detected incidents
CREATE TABLE incidents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(500) NOT NULL,
    description TEXT,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    status VARCHAR(30) NOT NULL DEFAULT 'open' CHECK (status IN (
        'open', 'investigating', 'planning', 'pending_approval',
        'executing', 'verifying', 'resolved', 'escalated', 'aborted'
    )),
    fingerprint VARCHAR(255) NOT NULL,
    namespace VARCHAR(100),
    affected_service VARCHAR(100),
    alert_labels JSONB DEFAULT '{}',
    risk_score DECIMAL(3,2) DEFAULT 0.00,
    thread_id VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT unique_active_fingerprint UNIQUE (fingerprint)
        DEFERRABLE INITIALLY DEFERRED
);

-- Timeline/events table - incident lifecycle events
CREATE TABLE timeline (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL CHECK (event_type IN (
        'created', 'status_changed', 'observation', 'hypothesis',
        'plan_created', 'approval_requested', 'approved', 'rejected',
        'action_started', 'action_completed', 'action_failed',
        'verification_started', 'verification_passed', 'verification_failed',
        'resolved', 'escalated', 'aborted', 'comment'
    )),
    description TEXT,
    metadata JSONB DEFAULT '{}',
    actor VARCHAR(100) DEFAULT 'agent',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Tool calls audit log - every tool invocation is recorded
CREATE TABLE tool_calls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID REFERENCES incidents(id) ON DELETE CASCADE,
    tool_name VARCHAR(100) NOT NULL,
    input_params JSONB NOT NULL,
    output_summary TEXT,
    full_output JSONB,
    duration_ms INTEGER,
    success BOOLEAN NOT NULL DEFAULT false,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Hypotheses - root cause candidates
CREATE TABLE hypotheses (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    probable_cause TEXT NOT NULL,
    confidence DECIMAL(3,2) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    evidence JSONB DEFAULT '[]',
    affected_components JSONB DEFAULT '[]',
    is_primary BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Remediation plans - proposed action sets
CREATE TABLE remediation_plans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    hypothesis_id UUID REFERENCES hypotheses(id),
    total_risk_score DECIMAL(3,2) NOT NULL,
    estimated_duration_seconds INTEGER,
    auto_approvable BOOLEAN DEFAULT false,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'approved', 'rejected', 'executing', 'completed', 'failed'
    )),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    approved_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE
);

-- Remediation actions - individual steps within a plan
CREATE TABLE remediation_actions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    plan_id UUID NOT NULL REFERENCES remediation_plans(id) ON DELETE CASCADE,
    sequence_order INTEGER NOT NULL,
    action_type VARCHAR(50) NOT NULL CHECK (action_type IN (
        'restart_pod', 'scale_deployment', 'rollback_deployment',
        'drain_node', 'cordon_node', 'delete_pod', 'patch_resource',
        'escalate', 'notify'
    )),
    target VARCHAR(255) NOT NULL,
    parameters JSONB DEFAULT '{}',
    risk_level VARCHAR(20) NOT NULL CHECK (risk_level IN ('low', 'medium', 'high', 'critical')),
    estimated_impact TEXT,
    requires_approval BOOLEAN DEFAULT true,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'executing', 'completed', 'failed', 'skipped'
    )),
    result JSONB,
    executed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Approvals - HITL decision records
CREATE TABLE approvals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    plan_id UUID NOT NULL REFERENCES remediation_plans(id) ON DELETE CASCADE,
    action_summary TEXT NOT NULL,
    risk_score DECIMAL(3,2) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'approved', 'rejected', 'auto_approved', 'expired'
    )),
    approver VARCHAR(100),
    reason TEXT,
    auto_approve_eligible BOOLEAN DEFAULT false,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    decided_at TIMESTAMP WITH TIME ZONE
);

-- Verification results - post-execution health checks
CREATE TABLE verifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    plan_id UUID REFERENCES remediation_plans(id),
    check_type VARCHAR(50) NOT NULL CHECK (check_type IN (
        'pod_health', 'deployment_status', 'alert_cleared',
        'endpoint_health', 'metrics_normal', 'logs_clean'
    )),
    target VARCHAR(255),
    expected_state TEXT,
    actual_state TEXT,
    passed BOOLEAN NOT NULL,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Incident reports - generated postmortems
CREATE TABLE incident_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL UNIQUE REFERENCES incidents(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    summary TEXT NOT NULL,
    root_cause TEXT,
    timeline_summary TEXT,
    actions_taken JSONB DEFAULT '[]',
    lessons_learned JSONB DEFAULT '[]',
    recommendations JSONB DEFAULT '[]',
    report_markdown TEXT,
    generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================================================
-- MEMORY STORE (for runbook retrieval)
-- =============================================================================

-- Runbook entries - operational knowledge base
CREATE TABLE runbooks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    tags JSONB DEFAULT '[]',
    content TEXT NOT NULL,
    embedding_vector VECTOR(1536),  -- For pgvector similarity search
    version INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Past incident summaries for pattern matching
CREATE TABLE incident_patterns (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    incident_id UUID NOT NULL REFERENCES incidents(id),
    fingerprint_pattern VARCHAR(255) NOT NULL,
    root_cause_category VARCHAR(100),
    successful_remediation JSONB DEFAULT '{}',
    embedding_vector VECTOR(1536),
    occurrence_count INTEGER DEFAULT 1,
    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================================================
-- INDEXES
-- =============================================================================

-- Incidents
CREATE INDEX idx_incidents_status ON incidents(status);
CREATE INDEX idx_incidents_fingerprint ON incidents(fingerprint);
CREATE INDEX idx_incidents_namespace ON incidents(namespace);
CREATE INDEX idx_incidents_severity ON incidents(severity);
CREATE INDEX idx_incidents_created_at ON incidents(created_at DESC);
CREATE INDEX idx_incidents_thread_id ON incidents(thread_id);

-- Timeline
CREATE INDEX idx_timeline_incident ON timeline(incident_id);
CREATE INDEX idx_timeline_type ON timeline(event_type);
CREATE INDEX idx_timeline_created ON timeline(created_at DESC);

-- Tool calls
CREATE INDEX idx_tool_calls_incident ON tool_calls(incident_id);
CREATE INDEX idx_tool_calls_tool ON tool_calls(tool_name);
CREATE INDEX idx_tool_calls_created ON tool_calls(created_at DESC);

-- Hypotheses
CREATE INDEX idx_hypotheses_incident ON hypotheses(incident_id);
CREATE INDEX idx_hypotheses_confidence ON hypotheses(confidence DESC);

-- Plans and actions
CREATE INDEX idx_plans_incident ON remediation_plans(incident_id);
CREATE INDEX idx_plans_status ON remediation_plans(status);
CREATE INDEX idx_actions_plan ON remediation_actions(plan_id);
CREATE INDEX idx_actions_status ON remediation_actions(status);

-- Approvals
CREATE INDEX idx_approvals_incident ON approvals(incident_id);
CREATE INDEX idx_approvals_status ON approvals(status);
CREATE INDEX idx_approvals_pending ON approvals(status) WHERE status = 'pending';

-- Verifications
CREATE INDEX idx_verifications_incident ON verifications(incident_id);

-- Runbooks (pgvector index)
CREATE INDEX idx_runbooks_embedding ON runbooks
    USING ivfflat (embedding_vector vector_cosine_ops) WITH (lists = 100);

CREATE INDEX idx_patterns_embedding ON incident_patterns
    USING ivfflat (embedding_vector vector_cosine_ops) WITH (lists = 100);

-- =============================================================================
-- FUNCTIONS & TRIGGERS
-- =============================================================================

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_incidents_updated_at
    BEFORE UPDATE ON incidents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trigger_runbooks_updated_at
    BEFORE UPDATE ON runbooks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

-- Auto-add timeline entry on incident status change
CREATE OR REPLACE FUNCTION log_incident_status_change()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        INSERT INTO timeline (incident_id, event_type, description, metadata)
        VALUES (
            NEW.id,
            'status_changed',
            format('Status changed from %s to %s', OLD.status, NEW.status),
            jsonb_build_object('old_status', OLD.status, 'new_status', NEW.status)
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_incident_status_log
    AFTER UPDATE ON incidents
    FOR EACH ROW
    EXECUTE FUNCTION log_incident_status_change();

-- =============================================================================
-- VIEWS
-- =============================================================================

-- Active incidents view
CREATE OR REPLACE VIEW active_incidents AS
SELECT
    i.*,
    (SELECT COUNT(*) FROM timeline t WHERE t.incident_id = i.id) as event_count,
    (SELECT COUNT(*) FROM approvals a WHERE a.incident_id = i.id AND a.status = 'pending') as pending_approvals
FROM incidents i
WHERE i.status NOT IN ('resolved', 'aborted')
ORDER BY
    CASE i.severity
        WHEN 'critical' THEN 1
        WHEN 'high' THEN 2
        WHEN 'medium' THEN 3
        ELSE 4
    END,
    i.created_at DESC;

-- Incident summary view with latest events
CREATE OR REPLACE VIEW incident_summary AS
SELECT
    i.id,
    i.title,
    i.severity,
    i.status,
    i.fingerprint,
    i.namespace,
    i.affected_service,
    i.risk_score,
    i.created_at,
    i.resolved_at,
    EXTRACT(EPOCH FROM (COALESCE(i.resolved_at, NOW()) - i.created_at)) / 60 as duration_minutes,
    (SELECT json_agg(json_build_object(
        'event_type', t.event_type,
        'description', t.description,
        'created_at', t.created_at
    ) ORDER BY t.created_at DESC)
    FROM timeline t WHERE t.incident_id = i.id LIMIT 5) as recent_events
FROM incidents i;
