"""Base signal ingestor interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from src.types.state import Signal, SignalType


class BaseIngestor(ABC):
    """Base class for signal ingestors."""

    @property
    @abstractmethod
    def signal_type(self) -> SignalType:
        """Return the type of signals this ingestor handles."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start the ingestor."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the ingestor."""
        ...

    @abstractmethod
    async def fetch_signals(self) -> list[Signal]:
        """Fetch new signals from the source."""
        ...

    def _create_signal(
        self,
        signal_id: str,
        source: str,
        service: str,
        raw_content: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Signal:
        """Helper to create a Signal object."""
        return Signal(
            id=signal_id,
            type=self.signal_type,
            timestamp=datetime.utcnow(),
            source=source,
            service=service,
            metadata=metadata or {},
            raw_content=raw_content,
        )
