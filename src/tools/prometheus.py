"""Prometheus tools for SRE Agent.

Implements metric queries and alert retrieval.
"""

import logging
from datetime import datetime
from typing import Optional

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PrometheusConfig(BaseModel):
    """Configuration for Prometheus tools."""

    url: str = "http://localhost:9090"
    timeout: float = 30.0
    alertmanager_url: Optional[str] = "http://localhost:9093"


class PrometheusTools:
    """Prometheus query and alert tools."""

    def __init__(self, config: Optional[PrometheusConfig] = None) -> None:
        """Initialize Prometheus tools."""
        self._config = config or PrometheusConfig()
        self._client = httpx.AsyncClient(timeout=self._config.timeout)

    async def query_instant(self, query: str) -> dict:
        """Execute an instant query.

        Args:
            query: PromQL query string

        Returns:
            Query result as dict
        """
        try:
            response = await self._client.get(
                f"{self._config.url}/api/v1/query",
                params={"query": query},
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Prometheus query failed: {e}")
            return {"status": "error", "error": str(e)}

    async def query_range(
        self,
        query: str,
        start: int,
        end: int,
        step: str = "15s",
    ) -> dict:
        """Execute a range query.

        Args:
            query: PromQL query string
            start: Start timestamp (Unix)
            end: End timestamp (Unix)
            step: Query resolution step

        Returns:
            Query result as dict
        """
        try:
            response = await self._client.get(
                f"{self._config.url}/api/v1/query_range",
                params={
                    "query": query,
                    "start": start,
                    "end": end,
                    "step": step,
                },
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Prometheus range query failed: {e}")
            return {"status": "error", "error": str(e)}

    async def get_active_alerts(self) -> list[dict]:
        """Get active alerts from Prometheus.

        Returns:
            List of active alerts
        """
        try:
            response = await self._client.get(f"{self._config.url}/api/v1/alerts")
            response.raise_for_status()
            data = response.json()
            return data.get("data", {}).get("alerts", [])
        except Exception as e:
            logger.error(f"Failed to get alerts: {e}")
            return []

    async def get_alertmanager_alerts(self) -> list[dict]:
        """Get alerts from Alertmanager.

        Returns:
            List of alerts from Alertmanager
        """
        if not self._config.alertmanager_url:
            return []

        try:
            response = await self._client.get(
                f"{self._config.alertmanager_url}/api/v2/alerts",
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get Alertmanager alerts: {e}")
            return []

    async def get_targets(self) -> dict:
        """Get scrape targets status.

        Returns:
            Target status information
        """
        try:
            response = await self._client.get(f"{self._config.url}/api/v1/targets")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get targets: {e}")
            return {"status": "error", "error": str(e)}

    async def health_check(self) -> bool:
        """Check if Prometheus is reachable."""
        try:
            response = await self._client.get(f"{self._config.url}/-/healthy")
            return response.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
