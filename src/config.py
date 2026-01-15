"""Configuration for the DevOps Agent."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # Application
    app_name: str = "devops-agent"
    log_level: str = "INFO"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str | None = None

    # PostgreSQL/PGVector
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_database: str = "devops_agent"
    pg_user: str = "postgres"
    pg_password: str | None = None

    # Kubernetes
    k8s_namespace: str = "default"
    k8s_in_cluster: bool = False
    k8s_config_path: str | None = None

    # Execution
    auto_approve_low_risk: bool = True
    max_concurrent_actions: int = 3

    # Prometheus
    prometheus_url: str = "http://localhost:9090"

    # Jaeger
    jaeger_url: str = "http://localhost:16686"

    # Ollama (local LLM)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "granite3.1-moe:3b"
    ollama_timeout: int = 120

    class Config:
        env_prefix = "DEVOPS_AGENT_"


settings = Settings()
