"""Ingestion manager for coordinating all signal sources."""

import asyncio
import logging
from datetime import datetime
from typing import Any

from src.ingestion.base import BaseIngestor
from src.ingestion.log_ingestor import LogIngestor, LogIngestorConfig
from src.ingestion.metric_ingestor import MetricIngestor, MetricIngestorConfig
from src.ingestion.trace_ingestor import TraceIngestor, TraceIngestorConfig
from src.types.state import Signal

logger = logging.getLogger(__name__)


class IngestionManager:
    """Manages all signal ingestion sources."""

    def __init__(self) -> None:
        """Initialize the ingestion manager."""
        self._ingestors: dict[str, BaseIngestor] = {}
        self._running = False
        self._poll_tasks: list[asyncio.Task] = []

    def add_ingestor(self, name: str, ingestor: BaseIngestor) -> None:
        """Add an ingestor to the manager."""
        self._ingestors[name] = ingestor
        logger.info("Added ingestor: %s", name)

    def create_default_ingestors(self) -> None:
        """Create and add default ingestors."""
        # Log ingestor
        log_config = LogIngestorConfig()
        self.add_ingestor("logs", LogIngestor(log_config))

        # Metric ingestor
        metric_config = MetricIngestorConfig()
        self.add_ingestor("metrics", MetricIngestor(metric_config))

        # Trace ingestor
        trace_config = TraceIngestorConfig()
        self.add_ingestor("traces", TraceIngestor(trace_config))

    async def start(self) -> None:
        """Start all ingestors and begin polling."""
        self._running = True

        for name, ingestor in self._ingestors.items():
            await ingestor.start()
            logger.info("Started ingestor: %s", name)

        # Start polling tasks
        for name, ingestor in self._ingestors.items():
            task = asyncio.create_task(self._poll_ingestor(name, ingestor))
            self._poll_tasks.append(task)

        logger.info("Ingestion manager started with %d ingestors", len(self._ingestors))

    async def stop(self) -> None:
        """Stop all ingestors."""
        self._running = False

        # Cancel all polling tasks
        for task in self._poll_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._poll_tasks.clear()

        for name, ingestor in self._ingestors.items():
            await ingestor.stop()
            logger.info("Stopped ingestor: %s", name)

        logger.info("Ingestion manager stopped")

    async def _poll_ingestor(self, name: str, ingestor: BaseIngestor) -> None:
        """Poll an ingestor for new signals."""
        while self._running:
            try:
                signals = await ingestor.fetch_signals()
                if signals:
                    logger.info("Fetched %d signals from %s", len(signals), name)
            except Exception as e:
                logger.error("Error polling %s: %s", name, e)

            await asyncio.sleep(10)  # Poll interval

    async def fetch_all_signals(self) -> list[Signal]:
        """Fetch signals from all ingestors."""
        signals = []

        for name, ingestor in self._ingestors.items():
            try:
                ingestor_signals = await ingestor.fetch_signals()
                signals.extend(ingestor_signals)
            except Exception as e:
                logger.error("Error fetching from %s: %s", name, e)

        return signals

    async def health_check(self) -> dict[str, Any]:
        """Check health of all ingestors."""
        results = {}

        for name, ingestor in self._ingestors.items():
            try:
                healthy = await ingestor.health_check()
                results[name] = {"healthy": healthy, "status": "healthy" if healthy else "unhealthy"}
            except Exception as e:
                results[name] = {"healthy": False, "status": "error", "error": str(e)}

        return results

    def get_ingestor(self, name: str) -> BaseIngestor | None:
        """Get an ingestor by name."""
        return self._ingestors.get(name)
