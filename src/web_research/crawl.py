"""Web research client for crawling and summarizing web content.

Uses crawl4ai for LLM-powered web crawling.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class CrawlResult:
    """Result of web crawl operation."""
    url: str
    title: str
    content: str
    summary: Optional[str] = None
    links: Optional[list[str]] = None
    error: Optional[str] = None


@dataclass
class ResearchConfig:
    """Configuration for web research."""
    crawl_base_url: str = "http://localhost:8000"  # crawl4ai server
    timeout: int = 60
    max_pages: int = 5
    summarize: bool = True


class WebResearchClient:
    """Client for web research using crawl4ai."""

    def __init__(self, config: Optional[ResearchConfig] = None):
        """Initialize web research client.

        Args:
            config: Research configuration
        """
        self.config = config or ResearchConfig()
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def async_client(self) -> httpx.AsyncClient:
        """Get async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout),
            )
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def crawl(
        self,
        url: str,
        query: Optional[str] = None,
    ) -> CrawlResult:
        """Crawl a URL and extract content.

        Args:
            url: URL to crawl
            query: Optional query to guide extraction

        Returns:
            CrawlResult with extracted content
        """
        try:
            # Call crawl4ai API
            payload = {
                "url": url,
                "query": query or "Extract the main content and key information",
            }

            response = await self.async_client.post(
                f"{self.config.crawl_base_url}/api/v1/crawl",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            return CrawlResult(
                url=url,
                title=data.get("title", ""),
                content=data.get("content", ""),
                summary=data.get("summary") if self.config.summarize else None,
                links=data.get("links", []),
            )

        except httpx.HTTPError as e:
            logger.error(f"Crawl error for {url}: {e}")
            return CrawlResult(
                url=url,
                title="",
                content="",
                error=str(e),
            )

    async def crawl_multiple(
        self,
        urls: list[str],
        query: Optional[str] = None,
    ) -> list[CrawlResult]:
        """Crawl multiple URLs.

        Args:
            urls: List of URLs to crawl
            query: Optional query to guide extraction

        Returns:
            List of CrawlResults
        """
        results = []
        for url in urls[:self.config.max_pages]:
            result = await self.crawl(url, query)
            results.append(result)
        return results

    async def research(
        self,
        topic: str,
        sources: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Conduct web research on a topic.

        Args:
            topic: Research topic/query
            sources: Optional list of URLs to research

        Returns:
            Research results with summaries
        """
        if sources:
            # Crawl specific sources
            results = await self.crawl_multiple(sources, topic)
        else:
            # Would use search API here (not implemented)
            return {
                "topic": topic,
                "error": "Search not implemented. Provide sources list.",
                "results": [],
            }

        # Combine results
        combined = {
            "topic": topic,
            "sources_crawled": len(results),
            "findings": [],
        }

        for result in results:
            if result.error:
                combined["findings"].append({
                    "url": result.url,
                    "error": result.error,
                })
            else:
                combined["findings"].append({
                    "url": result.url,
                    "title": result.title,
                    "summary": result.summary or result.content[:500],
                })

        return combined

    async def is_available(self) -> bool:
        """Check if crawl4ai server is available."""
        try:
            response = await self.async_client.get(
                f"{self.config.crawl_base_url}/health",
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False


class FallbackResearchClient:
    """Fallback client using httpx when crawl4ai is unavailable."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def async_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def crawl(self, url: str) -> CrawlResult:
        """Simple crawl using httpx."""
        try:
            response = await self.async_client.get(url, follow_redirects=True)
            response.raise_for_status()

            # Extract title
            title = ""
            if "<title>" in response.text:
                title = response.text.split("<title>")[1].split("</title>")[0]

            # Simple content extraction (would use beautifulsoup in production)
            content = response.text[:5000] if response.text else ""

            return CrawlResult(
                url=url,
                title=title,
                content=content,
            )

        except httpx.HTTPError as e:
            return CrawlResult(
                url=url,
                title="",
                content="",
                error=str(e),
            )

    async def research(
        self,
        topic: str,
        sources: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Simple research using httpx."""
        if not sources:
            return {
                "topic": topic,
                "error": "No sources provided",
                "results": [],
            }

        results = []
        for url in sources[:5]:
            result = await self.crawl(url)
            results.append({
                "url": url,
                "title": result.title,
                "summary": result.content[:300] if result.content else "Failed to crawl",
            })

        return {
            "topic": topic,
            "sources_crawled": len(results),
            "findings": results,
        }


async def get_research_client() -> WebResearchClient | FallbackResearchClient:
    """Get appropriate research client.

    Returns crawl4ai client if available, else fallback.
    """
    client = WebResearchClient()
    if await client.is_available():
        return client
    await client.close()
    return FallbackResearchClient()


# Global client instance
_research_client: Optional[WebResearchClient | FallbackResearchClient] = None


def get_research_client_sync() -> WebResearchClient | FallbackResearchClient:
    """Get research client synchronously."""
    global _research_client
    if _research_client is None:
        import asyncio
        _research_client = asyncio.run(get_research_client())
    return _research_client
