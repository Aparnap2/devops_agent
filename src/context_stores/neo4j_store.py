"""Neo4j context store for service dependency graph."""

import logging
from typing import Any

from neo4j import AsyncGraphDatabase
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class Neo4jConfig(BaseModel):
    """Neo4j connection configuration."""

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str | None = None
    database: str = "neo4j"


class Neo4jContextStore:
    """Neo4j-based context store for service dependency graph and relationships."""

    def __init__(self, config: Neo4jConfig | None = None) -> None:
        """Initialize the Neo4j context store."""
        self.config = config or Neo4jConfig()
        self._driver = None

    async def connect(self) -> None:
        """Establish connection to Neo4j."""
        self._driver = AsyncGraphDatabase.driver(
            self.config.uri,
            auth=(self.config.user, self.config.password),
        )
        await self._driver.verify_connectivity()
        logger.info("Connected to Neo4j at %s", self.config.uri)

    async def disconnect(self) -> None:
        """Close the Neo4j connection."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("Disconnected from Neo4j")

    async def execute_query(
        self, query: str, parameters: dict | None = None
    ) -> list[dict]:
        """Execute a Cypher query."""
        if not self._driver:
            raise RuntimeError("Neo4j driver not connected")

        async with self._driver.session(database=self.config.database) as session:
            result = await session.run(query, parameters)
            records = await result.data()
            return records

    # Service graph operations

    async def upsert_service(
        self,
        service_id: str,
        name: str,
        namespace: str = "default",
        properties: dict | None = None,
    ) -> None:
        """Upsert a service node."""
        query = """
        MERGE (s:Service {id: $service_id})
        SET s.name = $name,
            s.namespace = $namespace,
            s.last_updated = datetime()
        WITH s
        SET s += $properties
        """
        await self.execute_query(query, {
            "service_id": service_id,
            "name": name,
            "namespace": namespace,
            "properties": properties or {},
        })

    async def add_dependency(
        self, from_service: str, to_service: str, relationship_type: str = "DEPENDS_ON"
    ) -> None:
        """Add a dependency relationship between services."""
        query = """
        MATCH (a:Service {id: $from_service})
        MATCH (b:Service {id: $to_service})
        MERGE (a)-[r:DEPENDS_ON]->(b)
        SET r.relationship_type = $relationship_type,
            r.created_at = datetime()
        """
        await self.execute_query(query, {
            "from_service": from_service,
            "to_service": to_service,
            "relationship_type": relationship_type,
        })

    async def get_service_dependencies(self, service_id: str) -> list[dict]:
        """Get all services that the given service depends on."""
        query = """
        MATCH (s:Service {id: $service_id})-[r:DEPENDS_ON]->(dep:Service)
        RETURN dep.id as id, dep.name as name, dep.namespace as namespace,
               r.relationship_type as relationship_type
        """
        return await self.execute_query(query, {"service_id": service_id})

    async def get_service_dependents(self, service_id: str) -> list[dict]:
        """Get all services that depend on the given service."""
        query = """
        MATCH (dep:Service)-[r:DEPENDS_ON]->(s:Service {id: $service_id})
        RETURN dep.id as id, dep.name as name, dep.namespace as namespace,
               r.relationship_type as relationship_type
        """
        return await self.execute_query(query, {"service_id": service_id})

    async def get_impact_chain(self, service_id: str) -> dict:
        """Get the full impact chain for a service (dependencies and dependents)."""
        dependencies = await self.get_service_dependencies(service_id)
        dependents = await self.get_service_dependents(service_id)

        return {
            "service_id": service_id,
            "dependencies": [d["id"] for d in dependencies],
            "dependents": [d["id"] for d in dependents],
            "all_affected": list(set([d["id"] for d in dependencies] + [d["id"] for d in dependents])),
        }

    async def get_services_by_namespace(self, namespace: str) -> list[dict]:
        """Get all services in a namespace."""
        query = """
        MATCH (s:Service)
        WHERE s.namespace = $namespace
        RETURN s.id as id, s.name as name
        """
        return await self.execute_query(query, {"namespace": namespace})

    async def get_services_with_issue(self, issue_type: str) -> list[dict]:
        """Get services marked with a specific issue."""
        query = """
        MATCH (s:Service)-[:HAS_ISSUE]->(i:Issue {type: $issue_type})
        RETURN s.id as id, s.name as name, i.severity as severity
        """
        return await self.execute_query(query, {"issue_type": issue_type})

    async def mark_service_with_issue(
        self, service_id: str, issue_type: str, severity: str
    ) -> None:
        """Mark a service with an issue."""
        query = """
        MATCH (s:Service {id: $service_id})
        MERGE (i:Issue {type: $issue_type})
        MERGE (s)-[:HAS_ISSUE]->(i)
        SET i.severity = $severity, i.timestamp = datetime()
        """
        await self.execute_query(query, {
            "service_id": service_id,
            "issue_type": issue_type,
            "severity": severity,
        })

    async def clear_service_issues(self, service_id: str) -> None:
        """Clear all issues from a service."""
        query = """
        MATCH (s:Service {id: $service_id})-[r:HAS_ISSUE]->(i:Issue)
        DELETE r
        """
        await self.execute_query(query, {"service_id": service_id})

    async def health_check(self) -> bool:
        """Check if Neo4j is healthy."""
        try:
            if self._driver:
                await self._driver.verify_connectivity()
                return True
            return False
        except Exception as e:
            logger.error("Neo4j health check failed: %s", e)
            return False

    async def get_graph_summary(self) -> dict:
        """Get a summary of the service graph."""
        query = """
        MATCH (s:Service)
        RETURN count(s) as service_count
        """
        services_result = await self.execute_query(query)
        query = """
        MATCH ()-[r:DEPENDS_ON]->()
        RETURN count(r) as relationship_count
        """
        relationships_result = await self.execute_query(query)

        return {
            "services": services_result[0]["service_count"] if services_result else 0,
            "relationships": relationships_result[0]["relationship_count"] if relationships_result else 0,
        }
