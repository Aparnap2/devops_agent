"""Log ingestion from various sources (ELK, CloudWatch, etc.)."""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

import httpx

from src.ingestion.base import BaseIngestor
from src.types.state import Signal, SignalType

logger = logging.getLogger(__name__)


class LogIngestorConfig:
    """Configuration for log ingestion."""

    # ELK Stack
    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_index: str = "logs-*"
    elasticsearch_user: str | None = None
    elasticsearch_password: str | None = None

    # CloudWatch
    aws_region: str = "us-east-1"
    log_group_name: str | None = None

    # Loki
    loki_url: str = "http://localhost:3100"

    # Common settings
    poll_interval_seconds: int = 10
    batch_size: int = 100
    lookback_seconds: int = 60


class LogIngestor(BaseIngestor):
    """Ingests logs from various sources."""

    signal_type = SignalType.LOG

    def __init__(self, config: LogIngestorConfig | None = None) -> None:
        """Initialize the log ingestor."""
        self.config = config or LogIngestorConfig()
        self._client = httpx.AsyncClient(timeout=30.0)
        self._last_poll: datetime | None = None
        self._running = False

    async def start(self) -> None:
        """Start the log ingestor."""
        self._running = True
        logger.info("Log ingestor started")

    async def stop(self) -> None:
        """Stop the log ingestor."""
        self._running = False
        await self._client.aclose()
        logger.info("Log ingestor stopped")

    async def fetch_signals(self) -> list[Signal]:
        """Fetch logs and convert to signals."""
        signals = []

        # For demo purposes, we'll simulate log signals
        # In production, this would connect to actual log sources
        signals.extend(await self._fetch_from_elasticsearch())
        signals.extend(await self._fetch_from_loki())

        self._last_poll = datetime.utcnow()
        return signals

    async def _fetch_from_elasticsearch(self) -> list[Signal]:
        """Fetch logs from Elasticsearch."""
        signals = []

        if not self.config.elasticsearch_url:
            return signals

        try:
            query = {
                "query": {
                    "bool": {
                        "must": [
                            {"range": {"@timestamp": {"gte": "now-1m"}}}
                        ]
                    }
                },
                "size": self.config.batch_size,
                "sort": [{"@timestamp": {"order": "desc"}}],
            }

            headers = {"Content-Type": "application/json"}
            if self.config.elasticsearch_user:
                auth = (self.config.elasticsearch_user, self.config.elasticsearch_password)
            else:
                auth = None

            response = await self._client.post(
                f"{self.config.elasticsearch_url}/{self.config.elasticsearch_index}/_search",
                json=query,
                headers=headers,
                auth=auth,
            )
            response.raise_for_status()

            data = response.json()
            hits = data.get("hits", {}).get("hits", [])

            for hit in hits:
                source = hit.get("_source", {})
                signal = self._create_signal(
                    signal_id=hit.get("_id", f"es-{datetime.utcnow().timestamp()}"),
                    source="elasticsearch",
                    service=source.get("service", source.get("app", "unknown")),
                    raw_content=source,
                    metadata={
                        "index": hit.get("_index"),
                        "level": source.get("level"),
                    },
                )
                signals.append(signal)

        except Exception as e:
            logger.error("Error fetching from Elasticsearch: %s", e)

        return signals

    async def _fetch_from_loki(self) -> list[Signal]:
        """Fetch logs from Loki."""
        signals = []

        if not self.config.loki_url:
            return signals

        try:
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(seconds=self.config.lookback_seconds)

            params = {
                "query": "{job=\"devops-agent\"}",
                "start": str(int(start_time.timestamp() * 1e9)),
                "end": str(int(end_time.timestamp() * 1e9)),
                "limit": self.config.batch_size,
            }

            response = await self._client.get(
                f"{self.config.loki_url}/loki/api/v1/query_range",
                params=params,
            )
            response.raise_for_status()

            data = response.json()
            streams = data.get("data", {}).get("result", [])

            for stream in streams:
                stream_labels = stream.get("stream", {})
                service = stream_labels.get("service", stream_labels.get("job", "unknown"))

                for entry in stream.get("values", []):
                    timestamp_ns, line = entry
                    timestamp = datetime.fromtimestamp(int(timestamp_ns) / 1e9)

                    # Parse log line for structured data
                    log_content = self._parse_log_line(line)

                    signal = self._create_signal(
                        signal_id=f"loki-{timestamp_ns}",
                        source="loki",
                        service=service,
                        raw_content={
                            "message": line,
                            "timestamp": timestamp.isoformat(),
                            **log_content,
                        },
                        metadata=stream_labels,
                    )
                    signals.append(signal)

        except Exception as e:
            logger.error("Error fetching from Loki: %s", e)

        return signals

    def _parse_log_line(self, line: str) -> dict[str, Any]:
        """Parse a log line to extract structured data."""
        result = {}

        # Try to parse as JSON
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        # Extract log level from common formats
        level_patterns = {
            "ERROR": r"ERROR|ERROR:|ERR|CRITICAL",
            "WARN": r"WARNING|WARN|WARN:|WARNING:",
            "INFO": r"INFO|INFO:",
            "DEBUG": r"DEBUG|DEBUG:",
        }

        for level, pattern in level_patterns.items():
            if re.search(pattern, line, re.IGNORECASE):
                result["level"] = level
                break

        return result

    async def health_check(self) -> bool:
        """Check if the log sources are healthy."""
        try:
            # Simple check - try to reach Elasticsearch
            if self.config.elasticsearch_url:
                response = await self._client.get(
                    f"{self.config.elasticsearch_url}/_cluster/health",
                    timeout=5.0,
                )
                return response.status_code == 200
            return True
        except Exception as e:
            logger.error("Log ingestor health check failed: %s", e)
            return False
