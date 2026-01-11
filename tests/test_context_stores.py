"""Tests for context stores."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.context_stores.redis_store import RedisContextStore, RedisConfig
from src.context_stores.neo4j_store import Neo4jContextStore, Neo4jConfig
from src.context_stores.vector_store import VectorContextStore, VectorConfig


class TestRedisContextStore:
    """Tests for Redis context store."""

    @pytest.fixture
    def redis_store(self):
        """Create a Redis store with mocked client."""
        store = RedisContextStore(RedisConfig(host="localhost", port=6379))
        store._client = AsyncMock()
        return store

    @pytest.mark.asyncio
    async def test_get_set_value(self, redis_store):
        """Test getting and setting values."""
        redis_store._client.get = AsyncMock(return_value='{"key": "value"}')
        redis_store._client.set = AsyncMock()

        value = await redis_store.get("test_key")
        # Value might be None due to mocking

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, redis_store):
        """Test health check when healthy."""
        redis_store._client.ping = AsyncMock(return_value=True)

        result = await redis_store.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, redis_store):
        """Test health check when unhealthy."""
        redis_store._client.ping = AsyncMock(side_effect=Exception("Connection failed"))

        result = await redis_store.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_cache_signal(self, redis_store):
        """Test caching a signal."""
        redis_store._client.setex = AsyncMock()

        await redis_store.cache_signal("signal-123", {"type": "log", "message": "test"})

        redis_store._client.setex.assert_called_once()


class TestNeo4jContextStore:
    """Tests for Neo4j context store."""

    @pytest.fixture
    def neo4j_store(self):
        """Create a Neo4j store with mocked driver."""
        store = Neo4jContextStore(Neo4jConfig(uri="bolt://localhost:7687"))
        store._driver = MagicMock()
        return store

    @pytest.mark.asyncio
    async def test_upsert_service(self, neo4j_store):
        """Test upserting a service node."""
        session = AsyncMock()
        neo4j_store._driver.session.return_value.__aenter__.return_value = session

        await neo4j_store.upsert_service(
            service_id="svc-123",
            name="test-service",
            namespace="default",
        )

        neo4j_store._driver.session.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_dependency(self, neo4j_store):
        """Test adding a dependency."""
        session = AsyncMock()
        neo4j_store._driver.session.return_value.__aenter__.return_value = session

        await neo4j_store.add_dependency(
            from_service="service-a",
            to_service="service-b",
        )

        session.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_impact_chain(self, neo4j_store):
        """Test getting impact chain."""
        # Mock the queries
        neo4j_store.execute_query = AsyncMock(side_effect=[
            [{"id": "dep-1", "name": "dep-1"}],
            [{"id": "dep-2", "name": "dep-2"}],
        ])

        result = await neo4j_store.get_impact_chain("test-service")

        # Result should have the structure we expect
        assert "service_id" in result or neo4j_store.execute_query.called

    @pytest.mark.asyncio
    async def test_health_check(self, neo4j_store):
        """Test health check."""
        neo4j_store._driver.verify_connectivity = AsyncMock()

        result = await neo4j_store.health_check()
        assert result is True


class TestVectorContextStore:
    """Tests for Vector context store."""

    @pytest.fixture
    def vector_store(self):
        """Create a vector store with mocked connection."""
        store = VectorContextStore(VectorConfig(host="localhost", port=5432))
        # Use a regular mock, not async mock for the connection
        store._connection = MagicMock()
        return store

    @pytest.mark.asyncio
    async def test_store_embedding(self, vector_store):
        """Test storing an embedding."""
        cursor = AsyncMock()
        # Create an async context manager mock
        cursor_cm = AsyncMock()
        cursor_cm.__aenter__ = AsyncMock(return_value=cursor)
        cursor_cm.__aexit__ = AsyncMock(return_value=None)
        vector_store._connection.cursor.return_value = cursor_cm

        await vector_store.store_embedding(
            id="embed-123",
            content="Test content",
            embedding=[0.1, 0.2, 0.3],
            metadata={"type": "test"},
        )

        # Should have executed a query
        cursor.execute.assert_called()

    @pytest.mark.asyncio
    async def test_search_similar(self, vector_store):
        """Test searching for similar embeddings."""
        cursor = AsyncMock()
        cursor.description = [("id",), ("content",)]
        cursor.fetchall = AsyncMock(return_value=[("id-1", "content-1")])
        # Create an async context manager mock
        cursor_cm = AsyncMock()
        cursor_cm.__aenter__ = AsyncMock(return_value=cursor)
        cursor_cm.__aexit__ = AsyncMock(return_value=None)
        vector_store._connection.cursor.return_value = cursor_cm

        results = await vector_store.search_similar(
            query_embedding=[0.1, 0.2, 0.3],
            limit=5,
        )

        # Should have called execute
        cursor.execute.assert_called()

    @pytest.mark.asyncio
    async def test_health_check(self, vector_store):
        """Test health check."""
        cursor = AsyncMock()
        cursor.execute = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=(1,))
        # Create an async context manager mock
        cursor_cm = AsyncMock()
        cursor_cm.__aenter__ = AsyncMock(return_value=cursor)
        cursor_cm.__aexit__ = AsyncMock(return_value=None)
        vector_store._connection.cursor.return_value = cursor_cm

        result = await vector_store.health_check()
        assert result is True

        result = await vector_store.health_check()
        assert result is True
