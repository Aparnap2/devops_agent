"""Trace ingestion from OpenTelemetry and Jaeger."""

import json
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

from src.ingestion.base import BaseIngestor
from src.types.state import Signal, SignalType

logger = logging.getLogger(__name__)


class TraceIngestorConfig:
    """Configuration for trace ingestion."""

    otlp_endpoint: str = "http://localhost:4318"
    jaeger_url: str = "http://localhost:16686"
    poll_interval_seconds: int = 20
    batch_size: int = 50

    # Error detection patterns
    error_attributes: list[str] = None  # Will be set in __init__

    def __init__(self) -> None:
        """Initialize config with default error attributes."""
        self.error_attributes = [
            "error.type",
            "exception.type",
            "otel.status_code",
            "http.status_code",
        ]


class TraceIngestor(BaseIngestor):
    """Ingests traces from OpenTelemetry and Jaeger."""

    signal_type = SignalType.TRACE

    def __init__(self, config: TraceIngestorConfig | None = None) -> None:
        """Initialize the trace ingestor."""
        self.config = config or TraceIngestorConfig()
        self._client = httpx.AsyncClient(timeout=30.0)
        self._running = False

    async def start(self) -> None:
        """Start the trace ingestor."""
        self._running = True
        logger.info("Trace ingestor started")

    async def stop(self) -> None:
        """Stop the trace ingestor."""
        self._running = False
        await self._client.aclose()
        logger.info("Trace ingestor stopped")

    async def fetch_signals(self) -> list[Signal]:
        """Fetch traces and convert to signals."""
        signals = []

        try:
            # Fetch error traces from Jaeger
            error_traces = await self._fetch_error_traces()
            signals.extend(error_traces)

            # Fetch slow traces
            slow_traces = await self._fetch_slow_traces()
            signals.extend(slow_traces)

        except Exception as e:
            logger.error("Error fetching traces: %s", e)

        return signals

    async def _fetch_error_traces(self) -> list[Signal]:
        """Fetch traces with errors."""
        signals = []

        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(minutes=5)

            params = {
                "service": "devops-agent",
                "lookback": "5m",
                "maxDuration": "",
                "minDuration": "",
                "operation": "",
                "tags": json.dumps({"error": "true"}),
            }

            response = await self._client.get(
                f"{self.config.jaeger_url}/api/traces",
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()

            data = response.json()
            for trace in data.get("data", []):
                spans = trace.get("spans", [])
                if spans:
                    root_span = spans[0]
                    signal = self._create_signal(
                        signal_id=f"trace-error-{root_span.get('traceID')}",
                        source="jaeger",
                        service=root_span.get("process", {}).get("serviceName", "unknown"),
                        raw_content={
                            "trace_id": root_span.get("traceID"),
                            "span_id": root_span.get("spanID"),
                            "operation": root_span.get("operationName"),
                            "duration": root_span.get("duration"),
                            "tags": root_span.get("tags", []),
                            "spans_count": len(spans),
                            "trace_type": "error",
                        },
                        metadata={
                            "trace_id": root_span.get("traceID"),
                            "trace_type": "error",
                        },
                    )
                    signals.append(signal)

        except Exception as e:
            logger.error("Error fetching error traces: %s", e)

        return signals

    async def _fetch_slow_traces(self) -> list[Signal]:
        """Fetch traces with high latency."""
        signals = []

        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(minutes=5)

            params = {
                "service": "devops-agent",
                "lookback": "5m",
                "maxDuration": "5s",
                "minDuration": "2s",
                "operation": "",
                "tags": json.dumps({}),
            }

            response = await self._client.get(
                f"{self.config.jaeger_url}/api/traces",
                params=params,
                timeout=30.0,
            )
            response.raise_for_status()

            data = response.json()
            for trace in data.get("data", []):
                spans = trace.get("spans", [])
                if spans:
                    root_span = spans[0]
                    duration_ms = root_span.get("duration", 0) / 1000

                    signal = self._create_signal(
                        signal_id=f"trace-slow-{root_span.get('traceID')}",
                        source="jaeger",
                        service=root_span.get("process", {}).get("serviceName", "unknown"),
                        raw_content={
                            "trace_id": root_span.get("traceID"),
                            "span_id": root_span.get("spanID"),
                            "operation": root_span.get("operationName"),
                            "duration_ms": duration_ms,
                            "tags": root_span.get("tags", []),
                            "spans_count": len(spans),
                            "trace_type": "slow",
                        },
                        metadata={
                            "trace_id": root_span.get("traceID"),
                            "trace_type": "slow",
                            "duration_ms": duration_ms,
                        },
                    )
                    signals.append(signal)

        except Exception as e:
            logger.error("Error fetching slow traces: %s", e)

        return signals

    async def health_check(self) -> bool:
        """Check if trace sources are healthy."""
        try:
            response = await self._client.get(
                f"{self.config.jaeger_url}/api/services",
                timeout=5.0,
            )
            return response.status_code == 200
        except Exception as e:
            logger.error("Trace ingestor health check failed: %s", e)
            return False

    async def get_trace_details(self, trace_id: str) -> dict[str, Any]:
        """Get details of a specific trace."""
        response = await self._client.get(
            f"{self.config.jaeger_url}/api/traces/{trace_id}",
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()

    async def get_service_dependencies(self) -> list[dict]:
        """Get service dependency graph from traces."""
        response = await self._client.get(
            f"{self.config.jaeger_url}/api/services",
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json().get("data", [])
