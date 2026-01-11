"""Kubernetes execution client."""

import asyncio
import logging
from datetime import datetime
from typing import Any

from kubernetes import client, config
from kubernetes.client import ApiClient, CoreV1Api, AppsV1Api
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class KubernetesConfig(BaseModel):
    """Kubernetes connection configuration."""

    kube_config_path: str | None = None
    context: str | None = None
    namespace: str = "default"
    in_cluster: bool = False

    # Safety settings
    require_confirmation: bool = True
    max_concurrent_operations: int = 5


class KubernetesExecutor:
    """Executes operations on Kubernetes clusters."""

    def __init__(self, config: KubernetesConfig | None = None) -> None:
        """Initialize the Kubernetes executor."""
        self.config = config or KubernetesConfig()
        self._client: ApiClient | None = None
        self._core_v1: CoreV1Api | None = None
        self._apps_v1: AppsV1Api | None = None
        _semaphore = asyncio.Semaphore(self.config.max_concurrent_operations)

    async def connect(self) -> None:
        """Connect to Kubernetes cluster."""
        if self.config.in_cluster:
            config.load_incluster_config()
        elif self.config.kube_config_path:
            config.load_kube_config(
                config_file=self.config.kube_config_path,
                context=self.config.context,
            )
        else:
            config.load_kube_config(context=self.config.context)

        self._client = client.ApiClient()
        self._core_v1 = client.CoreV1Api(self._client)
        self._apps_v1 = client.AppsV1Api(self._client)

        logger.info("Connected to Kubernetes namespace: %s", self.config.namespace)

    async def disconnect(self) -> None:
        """Disconnect from Kubernetes."""
        if self._client:
            self._client.close()
            self._client = None
            logger.info("Disconnected from Kubernetes")

    # Pod operations

    async def restart_pod(
        self, pod_name: str, namespace: str | None = None
    ) -> dict[str, Any]:
        """Restart a pod by deleting it."""
        namespace = namespace or self.config.namespace

        try:
            # Get pod info before deletion
            pod = await self._get_pod(pod_name, namespace)
            if not pod:
                raise ValueError(f"Pod {pod_name} not found in namespace {namespace}")

            # Delete the pod (it will be recreated if managed by a controller)
            await self._execute_async(
                self._core_v1.delete_namespaced_pod, pod_name, namespace
            )

            logger.info("Pod %s deleted in namespace %s", pod_name, namespace)

            return {
                "success": True,
                "action": "restart_pod",
                "pod_name": pod_name,
                "namespace": namespace,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error("Failed to restart pod %s: %s", pod_name, e)
            return {
                "success": False,
                "action": "restart_pod",
                "pod_name": pod_name,
                "error": str(e),
            }

    async def get_pod_logs(
        self,
        pod_name: str,
        container: str | None = None,
        tail_lines: int = 100,
        namespace: str | None = None,
    ) -> str:
        """Get logs from a pod."""
        namespace = namespace or self.config.namespace

        response = await self._execute_async(
            self._core_v1.read_namespaced_pod_log,
            pod_name,
            namespace,
            container=container,
            tail_lines=tail_lines,
        )

        return response

    async def list_pods(
        self,
        namespace: str | None = None,
        label_selector: str | None = None,
    ) -> list[dict]:
        """List pods in a namespace."""
        namespace = namespace or self.config.namespace

        response = await self._execute_async(
            self._core_v1.list_namespaced_pod,
            namespace,
            label_selector=label_selector,
        )

        return [
            {
                "name": pod.metadata.name,
                "status": pod.status.phase,
                "ip": pod.status.pod_ip,
                "node": pod.spec.node_name,
                "restarts": sum(
                    cs.restart_count
                    for cs in pod.status.container_statuses or []
                ),
            }
            for pod in response.items
        ]

    async def _get_pod(
        self, pod_name: str, namespace: str
    ) -> client.V1Pod | None:
        """Get a specific pod."""
        try:
            response = await self._execute_async(
                self._core_v1.read_namespaced_pod, pod_name, namespace
            )
            return response
        except Exception:
            return None

    # Deployment operations

    async def scale_deployment(
        self,
        deployment_name: str,
        replicas: int,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        """Scale a deployment to the specified number of replicas."""
        namespace = namespace or self.config.namespace

        try:
            # Get current deployment
            deployment = await self._execute_async(
                self._apps_v1.read_namespaced_deployment, deployment_name, namespace
            )

            # Update replica count
            deployment.spec.replicas = replicas

            # Apply the change
            await self._execute_async(
                self._apps_v1.patch_namespaced_deployment,
                deployment_name,
                namespace,
                {"spec": {"replicas": replicas}},
            )

            logger.info(
                "Deployment %s scaled to %d replicas in namespace %s",
                deployment_name,
                replicas,
                namespace,
            )

            return {
                "success": True,
                "action": "scale_deployment",
                "deployment_name": deployment_name,
                "replicas": replicas,
                "previous_replicas": deployment.spec.replicas,
                "namespace": namespace,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error("Failed to scale deployment %s: %s", deployment_name, e)
            return {
                "success": False,
                "action": "scale_deployment",
                "deployment_name": deployment_name,
                "error": str(e),
            }

    async def restart_deployment(
        self, deployment_name: str, namespace: str | None = None
    ) -> dict[str, Any]:
        """Restart all pods in a deployment by rolling them."""
        namespace = namespace or self.config.namespace

        try:
            # Get current deployment
            deployment = await self._execute_async(
                self._apps_v1.read_namespaced_deployment, deployment_name, namespace
            )

            # Add/Update the restart annotation
            annotations = deployment.spec.template.metadata.annotations or {}
            annotations["kubectl.kubernetes.io/restartedAt"] = datetime.utcnow().isoformat()

            # Patch the deployment
            await self._execute_async(
                self._apps_v1.patch_namespaced_deployment,
                deployment_name,
                namespace,
                {"spec": {"template": {"metadata": {"annotations": annotations}}}},
            )

            logger.info(
                "Deployment %s restarted in namespace %s", deployment_name, namespace
            )

            return {
                "success": True,
                "action": "restart_deployment",
                "deployment_name": deployment_name,
                "namespace": namespace,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error("Failed to restart deployment %s: %s", deployment_name, e)
            return {
                "success": False,
                "action": "restart_deployment",
                "deployment_name": deployment_name,
                "error": str(e),
            }

    async def get_deployment(
        self, deployment_name: str, namespace: str | None = None
    ) -> dict | None:
        """Get deployment details."""
        namespace = namespace or self.config.namespace

        try:
            deployment = await self._execute_async(
                self._apps_v1.read_namespaced_deployment, deployment_name, namespace
            )

            return {
                "name": deployment.metadata.name,
                "replicas": deployment.spec.replicas,
                "available_replicas": deployment.status.available_replicas or 0,
                "ready_replicas": deployment.status.ready_replicas or 0,
                "updated_replicas": deployment.status.updated_replicas or 0,
            }

        except Exception as e:
            logger.error("Failed to get deployment %s: %s", deployment_name, e)
            return None

    # Service operations

    async def get_service_endpoints(
        self, service_name: str, namespace: str | None = None
    ) -> list[dict]:
        """Get endpoints for a service."""
        namespace = namespace or self.config.namespace

        try:
            response = await self._execute_async(
                self._core_v1.read_namespaced_endpoints, service_name, namespace
            )

            endpoints = []
            for subset in response.subsets or []:
                for address in subset.addresses or []:
                    for port in subset.ports or []:
                        endpoints.append({
                            "ip": address.ip,
                            "port": port.port,
                            "protocol": port.protocol,
                            "name": port.name,
                        })

            return endpoints

        except Exception as e:
            logger.error(
                "Failed to get endpoints for service %s: %s", service_name, e
            )
            return []

    # Namespace operations

    async def list_namespaces(self) -> list[dict]:
        """List all namespaces."""
        response = await self._execute_async(self._core_v1.list_namespace)

        return [
            {
                "name": ns.metadata.name,
                "status": ns.status.phase,
            }
            for ns in response.items
        ]

    # Helper methods

    async def _execute_async(self, func, *args, **kwargs):
        """Execute a blocking Kubernetes API call asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    async def health_check(self) -> bool:
        """Check if Kubernetes is accessible."""
        try:
            await self._execute_async(self._core_v1.list_namespace, limit=1)
            return True
        except Exception as e:
            logger.error("Kubernetes health check failed: %s", e)
            return False
