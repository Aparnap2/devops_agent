"""Tests for the execution layer."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.execution.kubernetes_client import KubernetesExecutor, KubernetesConfig
from src.execution.execution_manager import ExecutionManager, ExecutionManagerConfig
from src.types.state import RemediationAction, ExecutionResult


class TestKubernetesExecutor:
    """Tests for Kubernetes executor."""

    @pytest.fixture
    def k8s_executor(self):
        """Create a Kubernetes executor with mocked client."""
        executor = KubernetesExecutor(KubernetesConfig())
        executor._core_v1 = AsyncMock()
        executor._apps_v1 = AsyncMock()
        return executor

    @pytest.mark.asyncio
    async def test_restart_pod_success(self, k8s_executor):
        """Test successful pod restart."""
        # Mock the pod lookup
        mock_pod = MagicMock()
        mock_pod.metadata.name = "test-pod"
        mock_pod.metadata.namespace = "default"

        k8s_executor._get_pod = AsyncMock(return_value=mock_pod)
        k8s_executor._execute_async = AsyncMock()

        result = await k8s_executor.restart_pod("test-pod", "default")

        assert result["success"] is True
        assert result["action"] == "restart_pod"

    @pytest.mark.asyncio
    async def test_restart_pod_not_found(self, k8s_executor):
        """Test pod restart when pod doesn't exist."""
        k8s_executor._get_pod = AsyncMock(return_value=None)

        result = await k8s_executor.restart_pod("nonexistent-pod", "default")

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_scale_deployment(self, k8s_executor):
        """Test scaling a deployment."""
        mock_deployment = MagicMock()
        mock_deployment.metadata.name = "test-deploy"
        mock_deployment.spec.replicas = 3

        k8s_executor._execute_async = AsyncMock(return_value=mock_deployment)

        result = await k8s_executor.scale_deployment("test-deploy", 5, "default")

        assert result["success"] is True
        assert result["action"] == "scale_deployment"
        assert result["replicas"] == 5

    @pytest.mark.asyncio
    async def test_list_pods(self, k8s_executor):
        """Test listing pods."""
        mock_pod1 = MagicMock()
        mock_pod1.metadata.name = "pod-1"
        mock_pod1.status.phase = "Running"
        mock_pod1.status.pod_ip = "10.0.0.1"
        mock_pod1.spec.node_name = "node-1"
        mock_pod1.status.container_statuses = []

        mock_pod2 = MagicMock()
        mock_pod2.metadata.name = "pod-2"
        mock_pod2.status.phase = "Running"
        mock_pod2.status.pod_ip = "10.0.0.2"
        mock_pod2.spec.node_name = "node-1"
        mock_pod2.status.container_statuses = []

        mock_list = MagicMock()
        mock_list.items = [mock_pod1, mock_pod2]

        k8s_executor._execute_async = AsyncMock(return_value=mock_list)

        pods = await k8s_executor.list_pods("default")

        assert len(pods) == 2
        assert pods[0]["name"] == "pod-1"
        assert pods[1]["name"] == "pod-2"

    @pytest.mark.asyncio
    async def test_health_check(self, k8s_executor):
        """Test health check."""
        k8s_executor._execute_async = AsyncMock()

        result = await k8s_executor.health_check()
        assert result is True


class TestExecutionManager:
    """Tests for the execution manager."""

    @pytest.fixture
    def exec_manager(self, mock_execution_manager):
        """Create an execution manager with mocked dependencies."""
        manager = ExecutionManager(ExecutionManagerConfig())
        manager._kubernetes = mock_execution_manager
        manager._action_semaphore = None
        return manager

    @pytest.mark.asyncio
    async def test_execute_action_low_risk_auto_approved(self, exec_manager, mock_execution_manager):
        """Test that low risk actions are auto-approved."""
        import asyncio
        exec_manager._action_semaphore = asyncio.Semaphore(3)

        action = RemediationAction(
            id="action-1",
            type="restart_pod",
            target="pod-1",
            risk_level="low",
            requires_approval=False,
        )

        # Set up the kubernetes mock to return a proper result
        mock_execution_manager.restart_pod = AsyncMock(return_value={
            "success": True,
            "action": "restart_pod",
            "pod_name": "pod-1",
        })

        result = await exec_manager.execute_action(action, require_approval=True)

        assert result.success is True
        # Auto-approve should still execute
        assert mock_execution_manager.restart_pod.called

    @pytest.mark.asyncio
    async def test_execute_action_requires_approval(self, exec_manager, mock_execution_manager):
        """Test that actions requiring approval are not executed."""
        action = RemediationAction(
            id="action-1",
            type="restart_deployment",
            target="deploy-1",
            risk_level="medium",
            requires_approval=True,
        )

        result = await exec_manager.execute_action(action, require_approval=True)

        assert result.success is False
        assert result.output.get("requires_approval") is True
        mock_execution_manager.execute_action.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_plan(self, exec_manager, mock_execution_manager, sample_remediation_plan):
        """Test executing a remediation plan."""
        import asyncio
        exec_manager._action_semaphore = asyncio.Semaphore(3)

        # Set up the kubernetes mock to return a proper result for the action
        mock_execution_manager.restart_deployment = AsyncMock(return_value={
            "success": True,
            "action": "restart_deployment",
            "deployment_name": "api-service",
        })

        # The sample_remediation_plan action has requires_approval=True,
        # so we need to bypass the check by setting require_approval=False
        # which only works if the action's risk_level is low
        results = await exec_manager.execute_plan(
            sample_remediation_plan.actions,
            require_approval=False,
        )

        # Action requires approval so no results returned
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_dry_run(self, exec_manager):
        """Test dry run functionality."""
        action = RemediationAction(
            id="action-1",
            type="restart_pod",
            target="pod-1",
            risk_level="low",
        )

        result = await exec_manager.dry_run(action)

        assert result["dry_run"] is True
        assert result["action"] == "restart_pod"
        assert result["risk_level"] == "low"


class TestRemediationActions:
    """Tests for specific remediation actions."""

    @pytest.mark.asyncio
    async def test_restart_deployment_action(self, mock_execution_manager):
        """Test restart deployment execution."""
        manager = ExecutionManager()
        manager._kubernetes = mock_execution_manager

        action = RemediationAction(
            id="action-1",
            type="restart_deployment",
            target="api-service",
            risk_level="medium",
            parameters={"namespace": "default"},
        )

        mock_execution_manager.restart_deployment = AsyncMock(return_value={
            "success": True,
            "action": "restart_deployment",
        })

        result = await manager._execute_restart_deployment(action)

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_scale_deployment_action(self, mock_execution_manager):
        """Test scale deployment execution."""
        manager = ExecutionManager()
        manager._kubernetes = mock_execution_manager

        action = RemediationAction(
            id="action-1",
            type="scale_deployment",
            target="api-service",
            risk_level="low",
            parameters={"replicas": 3, "namespace": "default"},
        )

        mock_execution_manager.scale_deployment = AsyncMock(return_value={
            "success": True,
            "action": "scale_deployment",
            "replicas": 3,
        })

        result = await manager._execute_scale_deployment(action)

        assert result["success"] is True
