"""Kubernetes tools using kubectl subprocess wrappers.

Implements SOP-OPS-002 (safe actions) and SOP-SEC-001 (input validation).
"""

import asyncio
import json
import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Valid Kubernetes resource name pattern (RFC 1123)
K8S_NAME_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$")

# Characters that could indicate command injection
DANGEROUS_CHARS = re.compile(r"[;&|`$(){}\\'\"]")


class ToolResult(BaseModel):
    """Result from a tool execution."""

    success: bool
    output: dict | str = Field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: int = 0


class K8sToolsConfig(BaseModel):
    """Configuration for Kubernetes tools."""

    kubectl_path: str = "kubectl"
    default_timeout: int = 30
    allowed_namespaces: list[str] = Field(default_factory=lambda: ["prod", "staging", "default"])
    max_replicas: int = 10
    min_replicas: int = 0


class K8sTools:
    """Kubernetes tools using kubectl subprocess wrappers.

    All methods are async and return ToolResult for consistent interface.
    Input validation is performed per SOP-SEC-001.
    """

    def __init__(self, config: Optional[K8sToolsConfig] = None) -> None:
        """Initialize K8s tools with configuration."""
        self._config = config or K8sToolsConfig()

    def _validate_namespace(self, namespace: str) -> Optional[str]:
        """Validate namespace is in allowlist."""
        if namespace not in self._config.allowed_namespaces:
            return f"Namespace '{namespace}' is not allowed. Allowed: {self._config.allowed_namespaces}"
        return None

    def _validate_resource_name(self, name: str) -> Optional[str]:
        """Validate resource name is safe (no injection, valid K8s name)."""
        if not name:
            return "Resource name cannot be empty"

        # Check for dangerous characters (command injection)
        if DANGEROUS_CHARS.search(name):
            return f"Invalid resource name: contains dangerous characters"

        # Check for path traversal
        if ".." in name or "/" in name:
            return f"Invalid resource name: contains path traversal characters"

        # Check length
        if len(name) > 253:
            return f"Invalid resource name: too long (max 253 characters)"

        return None

    async def list_pods(
        self,
        namespace: str,
        label_selector: Optional[str] = None,
    ) -> ToolResult:
        """List pods in a namespace.

        Args:
            namespace: Kubernetes namespace
            label_selector: Optional label selector (e.g., "app=demo")

        Returns:
            ToolResult with pod list in output
        """
        # Validate namespace
        if error := self._validate_namespace(namespace):
            return ToolResult(success=False, output={}, error=error)

        cmd = [self._config.kubectl_path, "get", "pods", "-n", namespace, "-o", "json"]

        if label_selector:
            cmd.extend(["-l", label_selector])

        result = await self._run_cmd(cmd)

        if result.success and isinstance(result.output, str):
            try:
                result.output = json.loads(result.output)
            except json.JSONDecodeError:
                result.output = {"raw": result.output}

        return result

    async def get_pod(self, name: str, namespace: str) -> ToolResult:
        """Get pod details.

        Args:
            name: Pod name
            namespace: Kubernetes namespace

        Returns:
            ToolResult with pod details
        """
        # Validate inputs
        if error := self._validate_namespace(namespace):
            return ToolResult(success=False, output={}, error=error)
        if error := self._validate_resource_name(name):
            return ToolResult(success=False, output={}, error=error)

        cmd = [self._config.kubectl_path, "get", "pod", name, "-n", namespace, "-o", "json"]
        result = await self._run_cmd(cmd)

        if result.success and isinstance(result.output, str):
            try:
                result.output = json.loads(result.output)
            except json.JSONDecodeError:
                result.output = {"raw": result.output}

        return result

    async def describe_pod(self, name: str, namespace: str) -> ToolResult:
        """Get detailed pod description.

        Args:
            name: Pod name
            namespace: Kubernetes namespace

        Returns:
            ToolResult with description text
        """
        if error := self._validate_namespace(namespace):
            return ToolResult(success=False, output={}, error=error)
        if error := self._validate_resource_name(name):
            return ToolResult(success=False, output={}, error=error)

        cmd = [self._config.kubectl_path, "describe", "pod", name, "-n", namespace]
        result = await self._run_cmd(cmd)

        if result.success:
            result.output = {"description": result.output}

        return result

    async def get_events(
        self,
        namespace: str,
        field_selector: Optional[str] = None,
    ) -> ToolResult:
        """Get events in a namespace.

        Args:
            namespace: Kubernetes namespace
            field_selector: Optional field selector

        Returns:
            ToolResult with events list
        """
        if error := self._validate_namespace(namespace):
            return ToolResult(success=False, output={}, error=error)

        cmd = [
            self._config.kubectl_path, "get", "events",
            "-n", namespace,
            "--sort-by", ".lastTimestamp",
            "-o", "json",
        ]

        if field_selector:
            cmd.extend(["--field-selector", field_selector])

        result = await self._run_cmd(cmd)

        if result.success and isinstance(result.output, str):
            try:
                result.output = json.loads(result.output)
            except json.JSONDecodeError:
                result.output = {"raw": result.output}

        return result

    async def get_logs(
        self,
        name: str,
        namespace: str,
        container: Optional[str] = None,
        tail_lines: int = 100,
        since: Optional[str] = None,
    ) -> ToolResult:
        """Get pod logs.

        Args:
            name: Pod name
            namespace: Kubernetes namespace
            container: Optional container name
            tail_lines: Number of lines to tail
            since: Optional duration (e.g., "1h", "30m")

        Returns:
            ToolResult with logs text
        """
        if error := self._validate_namespace(namespace):
            return ToolResult(success=False, output={}, error=error)
        if error := self._validate_resource_name(name):
            return ToolResult(success=False, output={}, error=error)

        cmd = [
            self._config.kubectl_path, "logs", name,
            "-n", namespace,
            f"--tail={tail_lines}",
        ]

        if container:
            if error := self._validate_resource_name(container):
                return ToolResult(success=False, output={}, error=error)
            cmd.extend(["-c", container])

        if since:
            cmd.extend([f"--since={since}"])

        result = await self._run_cmd(cmd)

        if result.success:
            result.output = {"logs": result.output}

        return result

    async def restart_pod(self, name: str, namespace: str) -> ToolResult:
        """Restart a pod by deleting it (relies on controller to recreate).

        This is an allowlisted safe action per SOP-OPS-002.

        Args:
            name: Pod name
            namespace: Kubernetes namespace

        Returns:
            ToolResult indicating success/failure
        """
        if error := self._validate_namespace(namespace):
            return ToolResult(success=False, output={}, error=error)
        if error := self._validate_resource_name(name):
            return ToolResult(success=False, output={}, error=error)

        cmd = [
            self._config.kubectl_path, "delete", "pod", name,
            "-n", namespace,
            "--wait=false",
        ]

        result = await self._run_cmd(cmd)

        if result.success:
            result.output = {"restarted": name, "namespace": namespace}
            logger.info(f"Restarted pod {name} in {namespace}")

        return result

    async def scale_deployment(
        self,
        name: str,
        namespace: str,
        replicas: int,
    ) -> ToolResult:
        """Scale a deployment to specified replicas.

        This is an allowlisted safe action per SOP-OPS-002 (within bounds).

        Args:
            name: Deployment name
            namespace: Kubernetes namespace
            replicas: Target replica count

        Returns:
            ToolResult indicating success/failure
        """
        if error := self._validate_namespace(namespace):
            return ToolResult(success=False, output={}, error=error)
        if error := self._validate_resource_name(name):
            return ToolResult(success=False, output={}, error=error)

        # Validate replica bounds
        if replicas < self._config.min_replicas:
            return ToolResult(
                success=False,
                output={},
                error=f"Invalid replicas: {replicas} is below minimum ({self._config.min_replicas})",
            )

        if replicas > self._config.max_replicas:
            return ToolResult(
                success=False,
                output={},
                error=f"Invalid replicas: {replicas} exceeds maximum ({self._config.max_replicas})",
            )

        cmd = [
            self._config.kubectl_path, "scale", "deployment", name,
            "-n", namespace,
            f"--replicas={replicas}",
        ]

        result = await self._run_cmd(cmd)

        if result.success:
            result.output = {"scaled": name, "replicas": replicas, "namespace": namespace}
            logger.info(f"Scaled deployment {name} in {namespace} to {replicas} replicas")

        return result

    async def rollout_status(self, name: str, namespace: str) -> ToolResult:
        """Check deployment rollout status.

        Args:
            name: Deployment name
            namespace: Kubernetes namespace

        Returns:
            ToolResult with rollout status
        """
        if error := self._validate_namespace(namespace):
            return ToolResult(success=False, output={}, error=error)
        if error := self._validate_resource_name(name):
            return ToolResult(success=False, output={}, error=error)

        cmd = [
            self._config.kubectl_path, "rollout", "status",
            "deployment", name,
            "-n", namespace,
            "--timeout=10s",
        ]

        result = await self._run_cmd(cmd)

        # Determine status based on result
        if result.success:
            result.output = {"status": "complete", "deployment": name}
        else:
            result.output = {"status": "pending", "deployment": name, "message": result.error or result.output}

        return result

    async def rollback_deployment(
        self,
        name: str,
        namespace: str,
        revision: Optional[int] = None,
    ) -> ToolResult:
        """Rollback a deployment.

        This action requires HITL approval per SOP-OPS-003.

        Args:
            name: Deployment name
            namespace: Kubernetes namespace
            revision: Optional specific revision to rollback to

        Returns:
            ToolResult indicating success/failure
        """
        if error := self._validate_namespace(namespace):
            return ToolResult(success=False, output={}, error=error)
        if error := self._validate_resource_name(name):
            return ToolResult(success=False, output={}, error=error)

        cmd = [
            self._config.kubectl_path, "rollout", "undo",
            "deployment", name,
            "-n", namespace,
        ]

        if revision is not None:
            cmd.append(f"--to-revision={revision}")

        result = await self._run_cmd(cmd)

        if result.success:
            result.output = {"rolled_back": name, "namespace": namespace}
            if revision:
                result.output["revision"] = revision
            logger.info(f"Rolled back deployment {name} in {namespace}")

        return result

    async def _run_cmd(
        self,
        cmd: list[str],
        timeout: Optional[int] = None,
    ) -> ToolResult:
        """Run a kubectl command asynchronously.

        Args:
            cmd: Command and arguments
            timeout: Optional timeout in seconds

        Returns:
            ToolResult with command output
        """
        timeout = timeout or self._config.default_timeout
        start_time = asyncio.get_event_loop().time()

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult(
                    success=False,
                    output="",
                    error=f"Command timed out after {timeout} seconds",
                    duration_ms=int((asyncio.get_event_loop().time() - start_time) * 1000),
                )

            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)

            if process.returncode == 0:
                return ToolResult(
                    success=True,
                    output=stdout.decode().strip(),
                    duration_ms=duration_ms,
                )
            else:
                return ToolResult(
                    success=False,
                    output=stdout.decode().strip(),
                    error=stderr.decode().strip(),
                    duration_ms=duration_ms,
                )

        except FileNotFoundError:
            return ToolResult(
                success=False,
                output="",
                error=f"kubectl not found at {self._config.kubectl_path}",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=str(e),
            )

    async def health_check(self) -> bool:
        """Check if kubectl is available and cluster is reachable."""
        result = await self._run_cmd([self._config.kubectl_path, "cluster-info"], timeout=5)
        return result.success
