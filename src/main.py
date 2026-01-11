"""Main entry point for the DevOps Agent."""

import asyncio
import logging
import sys

from src.agent import DevOpsAgent
from src.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Main entry point."""
    logger.info("Starting DevOps/SRE Agent v0.1.0")

    agent = DevOpsAgent()

    try:
        await agent.initialize()

        # Run health check
        health = await agent.health_check()
        logger.info("Health check results: %s", health)

        # Run agent once
        result = await agent.run_once()
        logger.info("Agent run completed. Final step: %s", result.get("current_step"))

        # Print graph diagram
        diagram = agent.get_graph_diagram()
        logger.info("Graph diagram available")

    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    except Exception as e:
        logger.error("Fatal error: %s", e)
        raise
    finally:
        await agent.shutdown()
        logger.info("DevOps Agent stopped")


if __name__ == "__main__":
    asyncio.run(main())
