"""Execution manager for coordinating remediation actions."""

import asyncio
import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from src.execution.kubernetes_client import KubernetesExecutor, KubernetesConfig
from src.types.state import RemediationAction, ExecutionResult

logger = logging.getLogger(__name__)


class ExecutionManagerConfig(BaseModel):
    """Configuration for the execution manager."""

    kubernetes: KubernetesConfig | None = None
    auto_approve_low_risk: bool = True
    max_concurrent_actions: int = 3
    confirmation_timeout_seconds: int = 60


class ExecutionManager:
    """Manages execution of remediation actions."""

    def __init__(self, config: ExecutionManagerConfig | None = None) -> None:
        """Initialize the execution manager."""
        self.config = config or ExecutionManagerConfig()
        self._kubernetes: KubernetesExecutor | None = None
        self._running = False
        self._action_semaphore: asyncio.Semaphore | None = None

    async def initialize(self) -> None:
        """Initialize the execution manager."""
        self._running = True
        self._action_semaphore = asyncio.Semaphore(
            self.config.max_concurrent_actions
        )

        # Initialize Kubernetes executor
        k8s_config = self.config.kubernetes or KubernetesConfig()
        self._kubernetes = KubernetesExecutor(k8s_config)
        await self._kubernetes.connect()

        logger.info("Execution manager initialized")

    async def shutdown(self) -> None:
        """Shutdown the execution manager."""
        self._running = False

        if self._kubernetes:
            await self._kubernetes.disconnect()

        logger.info("Execution manager shut down")

    async def execute_action(
        self, action: RemediationAction, require_approval: bool = True
    ) -> ExecutionResult:
        """Execute a single remediation action."""
        start_time = datetime.utcnow()

        # Check if approval is required
        if require_approval and action.requires_approval:
            logger.info(
                "Action %s requires manual approval", action.id
            )
            return ExecutionResult(
                action_id=action.id,
                success=False,
                output={"requires_approval": True},
                error_message="Action requires manual approval",
                duration_seconds=0,
            )

        # Check auto-approve for low risk actions
        if self.config.auto_approve_low_risk and action.risk_level == "low":
            logger.info("Auto-approving low risk action: %s", action.id)
        elif require_approval:
            logger.info("Executing action requiring approval: %s", action.id)

        async with self._action_semaphore:
            try:
                result = await self._execute_on_target(action)
                duration = (datetime.utcnow() - start_time).total_seconds()

                return ExecutionResult(
                    action_id=action.id,
                    success=result.get("success", False),
                    output=result,
                    error_message=result.get("error"),
                    duration_seconds=duration,
                )

            except Exception as e:
                duration = (datetime.utcnow() - start_time).total_seconds()
                logger.error("Action %s failed: %s", action.id, e)

                return ExecutionResult(
                    action_id=action.id,
                    success=False,
                    error_message=str(e),
                    duration_seconds=duration,
                )

    async def execute_plan(
        self,
        actions: list[RemediationAction],
        require_approval: bool = True,
    ) -> list[ExecutionResult]:
        """Execute a remediation plan with multiple actions."""
        results = []

        for action in actions:
            if not self._running:
                logger.info("Execution cancelled")
                break

            result = await self.execute_action(action, require_approval)
            results.append(result)

            if not result.success:
                logger.warning(
                    "Action %s failed, continuing with plan",
                    action.id,
                )

        return results

    async def _execute_on_target(self, action: RemediationAction) -> dict[str, Any]:
        """Execute an action on its target system."""
        action_type = action.type.lower()

        executors = {
            "restart_pod": self._execute_restart_pod,
            "scale_deployment": self._execute_scale_deployment,
            "restart_deployment": self._execute_restart_deployment,
            "restart_service": self._execute_restart_service,
            "delete_pod": self._execute_delete_pod,
            "exec_command": self._execute_exec_command,
        }

        executor = executors.get(action_type)
        if not executor:
            raise ValueError(f"Unknown action type: {action_type}")

        return await executor(action)

    async def _execute_restart_pod(self, action: RemediationAction) -> dict[str, Any]:
        """Restart a pod."""
        if not self._kubernetes:
            raise RuntimeError("Kubernetes client not initialized")

        return await self._kubernetes.restart_pod(
            pod_name=action.target,
            namespace=action.parameters.get("namespace", "default"),
        )

    async def _execute_scale_deployment(self, action: RemediationAction) -> dict[str, Any]:
        """Scale a deployment."""
        if not self._kubernetes:
            raise RuntimeError("Kubernetes client not initialized")

        return await self._kubernetes.scale_deployment(
            deployment_name=action.target,
            replicas=action.parameters.get("replicas", 1),
            namespace=action.parameters.get("namespace", "default"),
        )

    async def _execute_restart_deployment(self, action: RemediationAction) -> dict[str, Any]:
        """Restart a deployment."""
        if not self._kubernetes:
            raise RuntimeError("Kubernetes client not initialized")

        return await self._kubernetes.restart_deployment(
            deployment_name=action.target,
            namespace=action.parameters.get("namespace", "default"),
        )

    async def _execute_restart_service(self, action: RemediationAction) -> dict[str, Any]:
        """Restart a service (scale to 0 then back up)."""
        if not self._kubernetes:
            raise RuntimeError("Kubernetes client not initialized")

        namespace = action.parameters.get("namespace", "default")

        # Scale down
        scale_down = await self._kubernetes.scale_deployment(
            deployment_name=action.target,
            replicas=0,
            namespace=namespace,
        )

        if not scale_down.get("success"):
            return scale_down

        # Wait
        await asyncio.sleep(5)

        # Scale up
        replicas = action.parameters.get("replicas", 1)
        scale_up = await self._kubernetes.scale_deployment(
            deployment_name=action.target,
            replicas=replicas,
            namespace=namespace,
        )

        return {
            "success": scale_up.get("success"),
            "action": "restart_service",
            "target": action.target,
            "scale_down": scale_down,
            "scale_up": scale_up,
        }

    async def _execute_delete_pod(self, action: RemediationAction) -> dict[str, Any]:
        """Delete a pod."""
        if not self._kubernetes:
            raise RuntimeError("Kubernetes client not initialized")

        return await self._kubernetes.restart_pod(
            pod_name=action.target,
            namespace=action.parameters.get("namespace", "default"),
        )

    async def _execute_exec_command(self, action: RemediationAction) -> dict[str, Any]:
        """Execute a command in a pod."""
        # This would use kubectl exec
        logger.info("Exec command not yet implemented: %s", action.parameters)
        return {
            "success": False,
            "action": "exec_command",
            "error": "Not yet implemented",
        }

    async def dry_run(self, action: RemediationAction) -> dict[str, Any]:
        """Perform a dry run of an action."""
        return {
            "dry_run": True,
            "action": action.type,
            "target": action.target,
            "parameters": action.parameters,
            "would_execute": True,
            "risk_level": action.risk_level,
            "estimated_impact": action.estimated_impact,
        }

    async def health_check(self) -> bool:
        """Check if the execution manager is healthy."""
        if self._kubernetes:
            return await self._kubernetes.health_check()
        return False
