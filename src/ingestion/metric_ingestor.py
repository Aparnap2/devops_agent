"""Metric ingestion from Prometheus and other sources."""

import logging
from datetime import datetime
from typing import Any

import httpx

from src.ingestion.base import BaseIngestor
from src.types.state import Signal, SignalType

logger = logging.getLogger(__name__)


class MetricIngestorConfig:
    """Configuration for metric ingestion."""

    prometheus_url: str = "http://localhost:9090"
    poll_interval_seconds: int = 15
    batch_size: int = 100

    # Key metrics to watch
    critical_metrics: list[str] = None  # Will be set in __init__

    def __init__(self) -> None:
        """Initialize config with default metrics."""
        self.critical_metrics = [
            "up",
            "http_requests_total",
            "http_request_duration_seconds",
            "process_cpu_seconds_total",
            "process_resident_memory_bytes",
            "container_memory_usage_bytes",
            "container_cpu_usage_seconds_total",
            "kube_pod_status_ready",
            "kube_pod_container_status_restarts_total",
        ]


class MetricIngestor(BaseIngestor):
    """Ingests metrics from Prometheus."""

    signal_type = SignalType.METRIC

    def __init__(self, config: MetricIngestorConfig | None = None) -> None:
        """Initialize the metric ingestor."""
        self.config = config or MetricIngestorConfig()
        self._client = httpx.AsyncClient(timeout=30.0)
        self._running = False

    async def start(self) -> None:
        """Start the metric ingestor."""
        self._running = True
        logger.info("Metric ingestor started")

    async def stop(self) -> None:
        """Stop the metric ingestor."""
        self._running = False
        await self._client.aclose()
        logger.info("Metric ingestor stopped")

    async def fetch_signals(self) -> list[Signal]:
        """Fetch metrics and convert to signals."""
        signals = []

        try:
            # Query for critical metrics
            for metric in self.config.critical_metrics:
                metric_signals = await self._fetch_metric(metric)
                signals.extend(metric_signals)

        except Exception as e:
            logger.error("Error fetching metrics: %s", e)

        return signals

    async def _fetch_metric(self, metric_name: str) -> list[Signal]:
        """Fetch a specific metric."""
        signals = []

        try:
            query = metric_name
            if "container" in metric_name or "kube_pod" in metric_name:
                query = f'{metric_name}{{namespace=~".*"}}'

            response = await self._client.get(
                f"{self.config.prometheus_url}/api/v1/query",
                params={"query": query},
                timeout=10.0,
            )
            response.raise_for_status()

            data = response.json()
            if data.get("status") == "success":
                for result in data.get("data", {}).get("result", []):
                    metric = result.get("metric", {})
                    value = result.get("value", [])

                    if len(value) >= 2:
                        timestamp, metric_value = value[0], value[1]

                        # Check for anomalous values
                        anomaly_info = self._check_anomaly(metric_name, metric_value)

                        signal = self._create_signal(
                            signal_id=f"metric-{metric_name}-{timestamp}",
                            source="prometheus",
                            service=metric.get("service", metric.get("pod", "unknown")),
                            raw_content={
                                "metric_name": metric_name,
                                "value": float(metric_value),
                                "timestamp": timestamp,
                                "labels": metric,
                                "is_anomaly": anomaly_info["is_anomaly"],
                                "anomaly_reason": anomaly_info.get("reason"),
                            },
                            metadata={
                                "metric_family": metric_name,
                                "is_anomaly": anomaly_info["is_anomaly"],
                            },
                        )
                        signals.append(signal)

        except Exception as e:
            logger.error("Error fetching metric %s: %s", metric_name, e)

        return signals

    def _check_anomaly(self, metric_name: str, value: float) -> dict[str, Any]:
        """Check if a metric value is anomalous."""
        result = {"is_anomaly": False}

        # Define thresholds for common metrics
        thresholds = {
            "up": (1.0, "Service is down"),
            "http_request_duration_seconds": (0.5, "High latency"),
            "kube_pod_container_status_restarts_total": (3, "High restart count"),
        }

        if metric_name in thresholds:
            threshold, reason = thresholds[metric_name]
            if metric_name == "up" and value < threshold:
                result = {"is_anomaly": True, "reason": reason}
            elif value > threshold:
                result = {"is_anomaly": True, "reason": reason}

        return result

    async def health_check(self) -> bool:
        """Check if Prometheus is healthy."""
        try:
            response = await self._client.get(
                f"{self.config.prometheus_url}/-/healthy",
                timeout=5.0,
            )
            return response.status_code == 200
        except Exception as e:
            logger.error("Metric ingestor health check failed: %s", e)
            return False

    async def query_instant(self, query: str) -> dict[str, Any]:
        """Execute an instant query against Prometheus."""
        response = await self._client.get(
            f"{self.config.prometheus_url}/api/v1/query",
            params={"query": query},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()

    async def query_range(
        self,
        query: str,
        start: datetime,
        end: datetime,
        step: str = "15s",
    ) -> dict[str, Any]:
        """Execute a range query against Prometheus."""
        response = await self._client.get(
            f"{self.config.prometheus_url}/api/v1/query_range",
            params={
                "query": query,
                "start": str(start.timestamp()),
                "end": str(end.timestamp()),
                "step": step,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()
