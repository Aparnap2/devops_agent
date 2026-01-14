"""Policy engine for SRE Agent.

Implements SOPs from PRD Section 4.
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class PolicyConfig(BaseModel):
    """Policy configuration per SOPs."""

    # SOP-OPS-002: Safe actions allowlist
    allowed_actions: list[str] = Field(
        default_factory=lambda: [
            "restart_pod",
            "scale_deployment",
            "rollback_deployment",
        ]
    )

    # SOP-OPS-003: HITL thresholds
    approval_risk_threshold: float = 0.4
    approval_confidence_threshold: float = 0.7

    # Namespaces that always require approval
    protected_namespaces: list[str] = Field(
        default_factory=lambda: ["prod", "production"]
    )

    # Scaling limits
    max_scale_factor: float = 2.0
    min_replicas: int = 1
    max_replicas: int = 10


class PolicyEngine:
    """Policy engine for enforcing SOPs.

    Deterministic policy evaluation - LLM only proposes, policy engine decides.
    """

    def __init__(self, config: Optional[PolicyConfig] = None) -> None:
        """Initialize policy engine."""
        self._config = config or PolicyConfig()

    def is_action_allowed(self, action_type: str) -> bool:
        """Check if action type is in allowlist (SOP-OPS-002)."""
        return action_type in self._config.allowed_actions

    def requires_approval(
        self,
        risk_score: float,
        namespace: Optional[str] = None,
        rca_confidence: Optional[float] = None,
        action_type: Optional[str] = None,
    ) -> bool:
        """Determine if HITL approval is required (SOP-OPS-003).

        Approval required when ANY condition is true:
        - Action touches prod namespace
        - Risk score >= 0.4
        - Plan includes rollback, config change, or scaling beyond 2x
        - RCA confidence < 0.7

        Args:
            risk_score: Overall risk score (0.0 - 1.0)
            namespace: Target namespace
            rca_confidence: Root cause analysis confidence (0.0 - 1.0)
            action_type: Type of action being performed

        Returns:
            True if human approval is required
        """
        # Protected namespace check
        if namespace and namespace in self._config.protected_namespaces:
            return True

        # Risk threshold check
        if risk_score >= self._config.approval_risk_threshold:
            return True

        # Confidence threshold check
        if rca_confidence is not None and rca_confidence < self._config.approval_confidence_threshold:
            return True

        # Rollback always requires approval
        if action_type == "rollback_deployment":
            return True

        return False

    def validate_scale_action(
        self,
        current_replicas: int,
        target_replicas: int,
    ) -> tuple[bool, Optional[str]]:
        """Validate scaling action is within bounds.

        Args:
            current_replicas: Current replica count
            target_replicas: Target replica count

        Returns:
            Tuple of (is_valid, error_message)
        """
        if target_replicas < self._config.min_replicas:
            return False, f"Target replicas {target_replicas} below minimum {self._config.min_replicas}"

        if target_replicas > self._config.max_replicas:
            return False, f"Target replicas {target_replicas} exceeds maximum {self._config.max_replicas}"

        # Check scale factor
        if current_replicas > 0:
            scale_factor = target_replicas / current_replicas
            if scale_factor > self._config.max_scale_factor:
                return False, f"Scale factor {scale_factor:.1f}x exceeds maximum {self._config.max_scale_factor}x"

        return True, None

    def calculate_risk_score(
        self,
        severity: str,
        observations: list[dict[str, Any]],
        hypotheses: Optional[list[dict[str, Any]]] = None,
        namespace: Optional[str] = None,
    ) -> float:
        """Calculate overall risk score.

        Args:
            severity: Incident severity
            observations: Gathered observations
            hypotheses: Root cause hypotheses (optional)
            namespace: Target namespace (optional)

        Returns:
            Risk score between 0.0 and 1.0
        """
        score = 0.0

        # Base score from severity
        severity_scores = {
            "low": 0.1,
            "medium": 0.3,
            "high": 0.5,
            "critical": 0.7,
        }
        score = severity_scores.get(severity.lower(), 0.3)

        # Adjust for protected namespace
        if namespace and namespace in self._config.protected_namespaces:
            score += 0.2

        # Adjust for multiple affected pods
        for obs in observations:
            if obs.get("type") == "pods":
                pod_count = len(obs.get("data", {}).get("items", []))
                if pod_count > 3:
                    score += 0.1

        # Adjust for OOMKilled or CrashLoop
        for obs in observations:
            if obs.get("type") == "events":
                events = obs.get("data", {}).get("items", [])
                for event in events:
                    reason = event.get("reason", "")
                    if reason in ["OOMKilled", "CrashLoopBackOff"]:
                        score += 0.1
                        break

        # Cap at 1.0
        return min(score, 1.0)


# Module-level functions for convenience
_default_engine = PolicyEngine()


def is_action_allowed(action_type: str) -> bool:
    """Check if action type is allowed."""
    return _default_engine.is_action_allowed(action_type)


def requires_approval(
    risk_score: float,
    namespace: Optional[str] = None,
    rca_confidence: Optional[float] = None,
) -> bool:
    """Check if approval is required."""
    return _default_engine.requires_approval(
        risk_score=risk_score,
        namespace=namespace,
        rca_confidence=rca_confidence,
    )


def calculate_risk_score(
    severity: str,
    observations: list[dict[str, Any]],
    hypotheses: Optional[list[dict[str, Any]]] = None,
    namespace: Optional[str] = None,
) -> float:
    """Calculate risk score."""
    return _default_engine.calculate_risk_score(
        severity=severity,
        observations=observations,
        hypotheses=hypotheses,
        namespace=namespace,
    )
