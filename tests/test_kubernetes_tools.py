"""TDD: Tests for Kubernetes tools layer.

RED PHASE: Write tests first for kubectl wrappers.
"""

import asyncio
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.tools.kubernetes import K8sTools, ToolResult, K8sToolsConfig


class TestToolResult:
    """Tests for ToolResult model."""

    def test_tool_result_success(self):
        """Test successful tool result."""
        result = ToolResult(
            success=True,
            output={"pods": ["pod-1", "pod-2"]},
            duration_ms=150,
        )

        assert result.success is True
        assert result.output["pods"] == ["pod-1", "pod-2"]
        assert result.error is None
        assert result.duration_ms == 150

    def test_tool_result_failure(self):
        """Test failed tool result."""
        result = ToolResult(
            success=False,
            output={},
            error="Pod not found",
            duration_ms=50,
        )

        assert result.success is False
        assert result.error == "Pod not found"


class TestK8sToolsListPods:
    """Tests for K8sTools.list_pods."""

    @pytest.fixture
    def k8s_tools(self):
        """Create K8sTools instance."""
        return K8sTools(K8sToolsConfig())

    @pytest.mark.asyncio
    async def test_list_pods_success(self, k8s_tools):
        """Test listing pods successfully."""
        mock_output = json.dumps({
            "items": [
                {
                    "metadata": {"name": "pod-1", "namespace": "prod"},
                    "status": {"phase": "Running"},
                },
                {
                    "metadata": {"name": "pod-2", "namespace": "prod"},
                    "status": {"phase": "Running"},
                },
            ]
        })

        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(
                success=True,
                output=mock_output,
                duration_ms=100,
            )

            result = await k8s_tools.list_pods("prod")

            assert result.success is True
            assert len(result.output["items"]) == 2
            mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_pods_with_label_selector(self, k8s_tools):
        """Test listing pods with label selector."""
        mock_output = json.dumps({"items": []})

        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(
                success=True,
                output=mock_output,
                duration_ms=100,
            )

            result = await k8s_tools.list_pods("prod", label_selector="app=demo")

            assert result.success is True
            # Verify the command includes the label selector
            call_args = mock_run.call_args[0][0]
            assert "-l" in call_args
            assert "app=demo" in call_args

    @pytest.mark.asyncio
    async def test_list_pods_failure(self, k8s_tools):
        """Test listing pods failure - namespace not allowed."""
        # Namespace validation happens before command runs
        result = await k8s_tools.list_pods("nonexistent")

        assert result.success is False
        assert "not allowed" in result.error


class TestK8sToolsGetPod:
    """Tests for K8sTools.get_pod."""

    @pytest.fixture
    def k8s_tools(self):
        """Create K8sTools instance."""
        return K8sTools(K8sToolsConfig())

    @pytest.mark.asyncio
    async def test_get_pod_success(self, k8s_tools):
        """Test getting pod details."""
        mock_output = json.dumps({
            "metadata": {"name": "pod-1", "namespace": "prod"},
            "status": {"phase": "Running"},
        })

        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(
                success=True,
                output=mock_output,
                duration_ms=100,
            )

            result = await k8s_tools.get_pod("pod-1", "prod")

            assert result.success is True
            assert result.output["metadata"]["name"] == "pod-1"

    @pytest.mark.asyncio
    async def test_get_pod_not_found(self, k8s_tools):
        """Test getting non-existent pod."""
        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(
                success=False,
                output="",
                error="Error from server (NotFound): pods \"missing\" not found",
                duration_ms=50,
            )

            result = await k8s_tools.get_pod("missing", "prod")

            assert result.success is False
            assert "NotFound" in result.error


class TestK8sToolsGetEvents:
    """Tests for K8sTools.get_events."""

    @pytest.fixture
    def k8s_tools(self):
        """Create K8sTools instance."""
        return K8sTools(K8sToolsConfig())

    @pytest.mark.asyncio
    async def test_get_events_success(self, k8s_tools):
        """Test getting namespace events."""
        mock_output = json.dumps({
            "items": [
                {
                    "metadata": {"name": "event-1"},
                    "reason": "OOMKilled",
                    "message": "Container killed due to OOM",
                    "type": "Warning",
                },
            ]
        })

        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(
                success=True,
                output=mock_output,
                duration_ms=100,
            )

            result = await k8s_tools.get_events("prod")

            assert result.success is True
            assert len(result.output["items"]) == 1
            assert result.output["items"][0]["reason"] == "OOMKilled"


class TestK8sToolsGetLogs:
    """Tests for K8sTools.get_logs."""

    @pytest.fixture
    def k8s_tools(self):
        """Create K8sTools instance."""
        return K8sTools(K8sToolsConfig())

    @pytest.mark.asyncio
    async def test_get_logs_success(self, k8s_tools):
        """Test getting pod logs."""
        mock_logs = "2024-01-01 ERROR Connection failed\n2024-01-01 INFO Retrying..."

        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(
                success=True,
                output=mock_logs,
                duration_ms=100,
            )

            result = await k8s_tools.get_logs("pod-1", "prod", tail_lines=100)

            assert result.success is True
            assert "ERROR" in result.output["logs"]
            assert "Connection failed" in result.output["logs"]

    @pytest.mark.asyncio
    async def test_get_logs_with_container(self, k8s_tools):
        """Test getting logs from specific container."""
        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(
                success=True,
                output="container logs",
                duration_ms=100,
            )

            result = await k8s_tools.get_logs("pod-1", "prod", container="app")

            call_args = mock_run.call_args[0][0]
            assert "-c" in call_args
            assert "app" in call_args


class TestK8sToolsRestartPod:
    """Tests for K8sTools.restart_pod (delete pod)."""

    @pytest.fixture
    def k8s_tools(self):
        """Create K8sTools instance."""
        return K8sTools(K8sToolsConfig())

    @pytest.mark.asyncio
    async def test_restart_pod_success(self, k8s_tools):
        """Test restarting a pod (delete to trigger recreate)."""
        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(
                success=True,
                output="pod \"pod-1\" deleted",
                duration_ms=200,
            )

            result = await k8s_tools.restart_pod("pod-1", "prod")

            assert result.success is True
            assert result.output["restarted"] == "pod-1"

    @pytest.mark.asyncio
    async def test_restart_pod_not_found(self, k8s_tools):
        """Test restarting non-existent pod."""
        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(
                success=False,
                output="",
                error="Error from server (NotFound): pods \"missing\" not found",
                duration_ms=50,
            )

            result = await k8s_tools.restart_pod("missing", "prod")

            assert result.success is False


class TestK8sToolsScaleDeployment:
    """Tests for K8sTools.scale_deployment."""

    @pytest.fixture
    def k8s_tools(self):
        """Create K8sTools instance."""
        return K8sTools(K8sToolsConfig())

    @pytest.mark.asyncio
    async def test_scale_deployment_success(self, k8s_tools):
        """Test scaling a deployment."""
        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(
                success=True,
                output="deployment.apps/demo-app scaled",
                duration_ms=150,
            )

            result = await k8s_tools.scale_deployment("demo-app", "prod", replicas=3)

            assert result.success is True
            assert result.output["scaled"] == "demo-app"
            assert result.output["replicas"] == 3

    @pytest.mark.asyncio
    async def test_scale_deployment_validates_bounds(self, k8s_tools):
        """Test scale deployment validates replica bounds."""
        # Min replicas check
        result = await k8s_tools.scale_deployment("demo-app", "prod", replicas=-1)
        assert result.success is False
        assert "invalid" in result.error.lower() or "replicas" in result.error.lower()

        # Max replicas check (configurable, default 10)
        result = await k8s_tools.scale_deployment("demo-app", "prod", replicas=100)
        assert result.success is False


class TestK8sToolsRolloutStatus:
    """Tests for K8sTools.rollout_status."""

    @pytest.fixture
    def k8s_tools(self):
        """Create K8sTools instance."""
        return K8sTools(K8sToolsConfig())

    @pytest.mark.asyncio
    async def test_rollout_status_complete(self, k8s_tools):
        """Test checking rollout status when complete."""
        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(
                success=True,
                output="deployment \"demo-app\" successfully rolled out",
                duration_ms=100,
            )

            result = await k8s_tools.rollout_status("demo-app", "prod")

            assert result.success is True
            assert result.output["status"] == "complete"

    @pytest.mark.asyncio
    async def test_rollout_status_pending(self, k8s_tools):
        """Test checking rollout status when pending."""
        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(
                success=False,
                output="Waiting for deployment \"demo-app\" rollout to finish: 1 of 3 updated replicas are available",
                error="timeout",
                duration_ms=5000,
            )

            result = await k8s_tools.rollout_status("demo-app", "prod")

            assert result.output["status"] == "pending"


class TestK8sToolsRollbackDeployment:
    """Tests for K8sTools.rollback_deployment."""

    @pytest.fixture
    def k8s_tools(self):
        """Create K8sTools instance."""
        return K8sTools(K8sToolsConfig())

    @pytest.mark.asyncio
    async def test_rollback_deployment_success(self, k8s_tools):
        """Test rolling back a deployment."""
        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(
                success=True,
                output="deployment.apps/demo-app rolled back",
                duration_ms=200,
            )

            result = await k8s_tools.rollback_deployment("demo-app", "prod")

            assert result.success is True
            assert result.output["rolled_back"] == "demo-app"

    @pytest.mark.asyncio
    async def test_rollback_to_specific_revision(self, k8s_tools):
        """Test rolling back to specific revision."""
        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(
                success=True,
                output="deployment.apps/demo-app rolled back to revision 2",
                duration_ms=200,
            )

            result = await k8s_tools.rollback_deployment("demo-app", "prod", revision=2)

            call_args = mock_run.call_args[0][0]
            assert "--to-revision=2" in call_args


class TestK8sToolsDescribePod:
    """Tests for K8sTools.describe_pod."""

    @pytest.fixture
    def k8s_tools(self):
        """Create K8sTools instance."""
        return K8sTools(K8sToolsConfig())

    @pytest.mark.asyncio
    async def test_describe_pod_success(self, k8s_tools):
        """Test describing a pod."""
        mock_describe = """
Name:         pod-1
Namespace:    prod
Status:       Running
Events:
  Type     Reason     Age   Message
  ----     ------     ----  -------
  Normal   Scheduled  1m    Successfully assigned prod/pod-1 to node-1
  Warning  OOMKilled  30s   Container killed due to memory pressure
"""

        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(
                success=True,
                output=mock_describe,
                duration_ms=100,
            )

            result = await k8s_tools.describe_pod("pod-1", "prod")

            assert result.success is True
            assert "OOMKilled" in result.output["description"]


class TestK8sToolsInputValidation:
    """Tests for K8sTools input validation (SOP-SEC-001)."""

    @pytest.fixture
    def k8s_tools(self):
        """Create K8sTools instance with allowlisted namespaces."""
        config = K8sToolsConfig(
            allowed_namespaces=["prod", "staging", "default"],
        )
        return K8sTools(config)

    @pytest.mark.asyncio
    async def test_rejects_disallowed_namespace(self, k8s_tools):
        """Test that operations on non-allowlisted namespaces are rejected."""
        result = await k8s_tools.list_pods("kube-system")

        assert result.success is False
        assert "not allowed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_rejects_command_injection_in_pod_name(self, k8s_tools):
        """Test that command injection attempts are rejected."""
        # Attempt to inject command via pod name
        malicious_name = "pod; rm -rf /"

        result = await k8s_tools.get_pod(malicious_name, "prod")

        assert result.success is False
        assert "invalid" in result.error.lower()

    @pytest.mark.asyncio
    async def test_rejects_path_traversal(self, k8s_tools):
        """Test that path traversal attempts are rejected."""
        malicious_name = "../../../etc/passwd"

        result = await k8s_tools.get_pod(malicious_name, "prod")

        assert result.success is False
        assert "invalid" in result.error.lower()

    @pytest.mark.asyncio
    async def test_allows_valid_resource_names(self, k8s_tools):
        """Test that valid K8s resource names are accepted."""
        valid_names = [
            "my-pod",
            "my-pod-123",
            "pod.with.dots",
            "pod_with_underscores",  # Actually invalid in K8s, should be rejected
        ]

        with patch.object(k8s_tools, "_run_cmd") as mock_run:
            mock_run.return_value = ToolResult(success=True, output="{}", duration_ms=50)

            # Valid names should work
            result = await k8s_tools.get_pod("my-pod-123", "prod")
            assert result.success is True


class TestK8sToolsRunCmd:
    """Tests for internal _run_cmd method."""

    @pytest.fixture
    def k8s_tools(self):
        """Create K8sTools instance."""
        return K8sTools(K8sToolsConfig())

    @pytest.mark.asyncio
    async def test_run_cmd_success(self, k8s_tools):
        """Test running a command successfully."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (b'{"items": []}', b"")
            mock_exec.return_value = mock_process

            result = await k8s_tools._run_cmd(["kubectl", "get", "pods"])

            assert result.success is True
            assert result.output == '{"items": []}'

    @pytest.mark.asyncio
    async def test_run_cmd_failure(self, k8s_tools):
        """Test running a command that fails."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = AsyncMock()
            mock_process.returncode = 1
            mock_process.communicate.return_value = (b"", b"error: not found")
            mock_exec.return_value = mock_process

            result = await k8s_tools._run_cmd(["kubectl", "get", "pod", "missing"])

            assert result.success is False
            assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_run_cmd_timeout(self, k8s_tools):
        """Test command timeout handling."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_process = AsyncMock()
            mock_process.communicate.side_effect = asyncio.TimeoutError("Command timed out")
            mock_exec.return_value = mock_process

            result = await k8s_tools._run_cmd(["kubectl", "get", "pods"], timeout=1)

            assert result.success is False
            assert "timed out" in result.error.lower()
