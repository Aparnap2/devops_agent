"""Redis context store for caching and real-time data."""

import json
import logging
from datetime import timedelta
from typing import Any

import redis.asyncio as redis
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RedisConfig(BaseModel):
    """Redis connection configuration."""

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None
    ssl: bool = False
    max_connections: int = 50


class RedisContextStore:
    """Redis-based context store for caching and real-time state."""

    def __init__(self, config: RedisConfig | None = None) -> None:
        """Initialize the Redis context store."""
        self.config = config or RedisConfig()
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        """Establish connection to Redis."""
        self._client = redis.Redis(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            password=self.config.password,
            ssl=self.config.ssl,
            decode_responses=True,
        )
        await self._client.ping()
        logger.info("Connected to Redis at %s:%s", self.config.host, self.config.port)

    async def disconnect(self) -> None:
        """Close the Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Disconnected from Redis")

    async def get(self, key: str) -> Any | None:
        """Get a value from the cache."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        value = await self._client.get(key)
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return None

    async def set(
        self, key: str, value: Any, ttl_seconds: int | None = None
    ) -> None:
        """Set a value in the cache with optional TTL."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        serialized = json.dumps(value)
        if ttl_seconds:
            await self._client.setex(key, ttl_seconds, serialized)
        else:
            await self._client.set(key, serialized)

    async def delete(self, key: str) -> None:
        """Delete a key from the cache."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        await self._client.delete(key)

    async def get_or_set(
        self, key: str, factory: callable, ttl_seconds: int | None = None
    ) -> Any:
        """Get a value or set it using the factory function."""
        value = await self.get(key)
        if value is None:
            value = await factory()
            await self.set(key, value, ttl_seconds)
        return value

    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment a counter."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        return await self._client.incrby(key, amount)

    async def set_ttl(self, key: str, ttl_seconds: int) -> None:
        """Set TTL on an existing key."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        await self._client.expire(key, ttl_seconds)

    async def health_check(self) -> bool:
        """Check if Redis is healthy."""
        try:
            if self._client:
                await self._client.ping()
                return True
            return False
        except Exception as e:
            logger.error("Redis health check failed: %s", e)
            return False

    # Specialized methods for DevOps Agent

    async def cache_signal(self, signal_id: str, signal_data: dict) -> None:
        """Cache a processed signal."""
        await self.set(f"signal:{signal_id}", signal_data, ttl_seconds=3600)

    async def get_cached_signal(self, signal_id: str) -> dict | None:
        """Get a cached signal."""
        return await self.get(f"signal:{signal_id}")

    async def set_incident_state(self, incident_id: str, state: dict) -> None:
        """Cache incident state for quick access."""
        await self.set(f"incident:{incident_id}", state, ttl_seconds=86400)

    async def get_incident_state(self, incident_id: str) -> dict | None:
        """Get cached incident state."""
        return await self.get(f"incident:{incident_id}")

    async def increment_metric_counter(self, metric_name: str) -> int:
        """Increment a metric counter (for prometheus-style metrics)."""
        key = f"metric:counter:{metric_name}"
        return await self.increment(key)

    async def set_lock(self, lock_name: str, ttl_seconds: int = 30) -> bool:
        """Acquire a distributed lock."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        return await self._client.set(f"lock:{lock_name}", "1", nx=True, ex=ttl_seconds)

    async def release_lock(self, lock_name: str) -> None:
        """Release a distributed lock."""
        if not self._client:
            raise RuntimeError("Redis client not connected")
        await self._client.delete(f"lock:{lock_name}")
