"""Vector context store for embeddings and similarity search (PGVector)."""

import logging
from typing import Any

import pgvector.psycopg as pgvector
from pydantic import BaseModel
from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


class VectorConfig(BaseModel):
    """PostgreSQL/PGVector connection configuration."""

    host: str = "localhost"
    port: int = 5432
    database: str = "postgres"
    user: str = "postgres"
    password: str | None = None
    table_name: str = "embeddings"


class VectorContextStore:
    """PGVector-based context store for embeddings and similarity search."""

    def __init__(self, config: VectorConfig | None = None) -> None:
        """Initialize the vector context store."""
        self.config = config or VectorConfig()
        self._connection: AsyncConnection | None = None

    async def connect(self) -> None:
        """Establish connection to PostgreSQL with PGVector."""
        conn_params = {
            "host": self.config.host,
            "port": self.config.port,
            "dbname": self.config.database,
            "user": self.config.user,
            "password": self.config.password,
        }
        self._connection = await AsyncConnection.connect(**conn_params)
        await self._connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await self._initialize_table()
        logger.info("Connected to PostgreSQL at %s:%s", self.config.host, self.config.port)

    async def disconnect(self) -> None:
        """Close the PostgreSQL connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.info("Disconnected from PostgreSQL")

    async def _initialize_table(self) -> None:
        """Initialize the embeddings table."""
        table = self.config.table_name
        async with self._connection.cursor() as cur:
            await cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    id VARCHAR(255) PRIMARY KEY,
                    content TEXT,
                    embedding vector(1536),
                    metadata JSONB,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            await cur.execute(f"""
                CREATE INDEX IF NOT EXISTS {table}_embedding_idx
                ON {table} USING ivfflat (embedding vector_cosine_ops)
            """)

    async def execute_query(
        self, query: str, parameters: dict | None = None
    ) -> list[dict]:
        """Execute a query."""
        if not self._connection:
            raise RuntimeError("PostgreSQL connection not established")

        async with self._connection.cursor() as cur:
            await cur.execute(query, parameters)
            columns = [desc[0] for desc in cur.description]
            rows = await cur.fetchall()
            return [dict(zip(columns, row)) for row in rows]

    # Embedding operations

    async def store_embedding(
        self,
        id: str,
        content: str,
        embedding: list[float],
        metadata: dict | None = None,
    ) -> None:
        """Store an embedding with content and metadata."""
        table = self.config.table_name
        query = f"""
            INSERT INTO {table} (id, content, embedding, metadata)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                content = EXCLUDED.content,
                embedding = EXCLUDED.embedding,
                metadata = EXCLUDED.metadata,
                created_at = NOW()
        """
        await self.execute_query(query, {
            "id": id,
            "content": content,
            "embedding": embedding,
            "metadata": metadata,
        })

    async def search_similar(
        self,
        query_embedding: list[float],
        limit: int = 5,
        filters: dict | None = None,
    ) -> list[dict]:
        """Search for similar embeddings using cosine similarity."""
        table = self.config.table_name
        base_query = f"""
            SELECT id, content, embedding,
                   1 - (embedding <=> %s::vector) as similarity,
                   metadata
            FROM {table}
        """
        params = {"embedding": query_embedding}

        if filters:
            conditions = []
            for key, value in filters.items():
                conditions.append(f"metadata->>'{key}' = %s")
                params[key] = str(value)
            if conditions:
                base_query += " WHERE " + " AND ".join(conditions)

        base_query += f" ORDER BY embedding <=> %s::vector LIMIT {limit}"

        params["embedding"] = query_embedding
        return await self.execute_query(base_query, params)

    async def find_similar_incidents(
        self, description_embedding: list[float], limit: int = 5
    ) -> list[dict]:
        """Find similar past incidents based on description embedding."""
        table = self.config.table_name
        query = f"""
            SELECT id, content as description,
                   1 - (embedding <=> %s::vector) as similarity,
                   metadata->>'resolution' as resolution,
                   metadata->>'outcome' as outcome
            FROM {table}
            WHERE metadata->>'type' = 'incident'
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """
        return await self.execute_query(query, {
            "embedding": description_embedding,
            "limit": limit,
        })

    async def store_incident_memory(
        self,
        incident_id: str,
        description: str,
        embedding: list[float],
        resolution: str,
        outcome: str,
    ) -> None:
        """Store an incident memory for future reference."""
        await self.store_embedding(
            id=incident_id,
            content=description,
            embedding=embedding,
            metadata={
                "type": "incident",
                "resolution": resolution,
                "outcome": outcome,
            },
        )

    async def delete_embedding(self, id: str) -> None:
        """Delete an embedding by ID."""
        table = self.config.table_name
        query = f"DELETE FROM {table} WHERE id = %s"
        await self.execute_query(query, {"id": id})

    async def health_check(self) -> bool:
        """Check if PostgreSQL is healthy."""
        try:
            if self._connection:
                async with self._connection.cursor() as cur:
                    await cur.execute("SELECT 1")
                    return True
            return False
        except Exception as e:
            logger.error("PostgreSQL health check failed: %s", e)
            return False

    async def get_stats(self) -> dict:
        """Get statistics about the vector store."""
        table = self.config.table_name
        query = f"SELECT COUNT(*) as count FROM {table}"
        result = await self.execute_query(query)
        return {"total_embeddings": result[0]["count"] if result else 0}
