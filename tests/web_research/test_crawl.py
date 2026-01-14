"""TDD: Tests for web research capabilities.

Tests for crawl4ai integration and web crawling.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from src.web_research.crawl import (
    CrawlResult,
    ResearchConfig,
    WebResearchClient,
    FallbackResearchClient,
    get_research_client,
)


class TestCrawlResult:
    """Tests for CrawlResult dataclass."""

    def test_crawl_result_success(self):
        """Test successful crawl result."""
        result = CrawlResult(
            url="https://example.com",
            title="Example",
            content="Page content here",
            summary="Summarized content",
            links=["https://example.com/page1"],
        )

        assert result.url == "https://example.com"
        assert result.title == "Example"
        assert result.content == "Page content here"
        assert result.summary == "Summarized content"
        assert result.links == ["https://example.com/page1"]
        assert result.error is None

    def test_crawl_result_error(self):
        """Test crawl result with error."""
        result = CrawlResult(
            url="https://example.com",
            title="",
            content="",
            error="Connection timeout",
        )

        assert result.error == "Connection timeout"
        assert result.content == ""


class TestResearchConfig:
    """Tests for ResearchConfig."""

    def test_default_config(self):
        """Test default research config."""
        config = ResearchConfig()

        assert config.crawl_base_url == "http://localhost:8000"
        assert config.timeout == 60
        assert config.max_pages == 5
        assert config.summarize is True

    def test_custom_config(self):
        """Test custom research config."""
        config = ResearchConfig(
            crawl_base_url="http://crawl4ai:8000",
            timeout=120,
            max_pages=10,
            summarize=False,
        )

        assert config.crawl_base_url == "http://crawl4ai:8000"
        assert config.timeout == 120
        assert config.max_pages == 10


class TestWebResearchClient:
    """Tests for WebResearchClient."""

    @pytest.mark.asyncio
    async def test_crawl_success(self):
        """Test successful crawl."""
        client = WebResearchClient()

        with patch.object(client.async_client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "url": "https://example.com",
                "title": "Example Page",
                "content": "Full page content here",
                "summary": "Summarized version",
                "links": ["https://example.com/1", "https://example.com/2"],
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            result = await client.crawl("https://example.com", "Extract info")

            assert result.url == "https://example.com"
            assert result.title == "Example Page"
            assert "Full page content" in result.content
            assert result.summary == "Summarized version"

    @pytest.mark.asyncio
    async def test_crawl_error(self):
        """Test crawl with HTTP error."""
        client = WebResearchClient()

        with patch.object(client.async_client, "post") as mock_post:
            mock_post.side_effect = Exception("Connection refused")

            result = await client.crawl("https://example.com")

            assert result.error is not None
            assert "Connection refused" in result.error

    @pytest.mark.asyncio
    async def test_crawl_multiple(self):
        """Test crawling multiple URLs."""
        client = WebResearchClient()

        with patch.object(client.async_client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "url": "https://example.com",
                "title": "Example",
                "content": "Content",
                "links": [],
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            urls = [
                "https://example.com/1",
                "https://example.com/2",
                "https://example.com/3",
            ]
            results = await client.crawl_multiple(urls, "Extract")

            assert len(results) == 3
            for i, result in enumerate(results):
                assert f"/{i+1}" in result.url

    @pytest.mark.asyncio
    async def test_research_with_sources(self):
        """Test research with provided sources."""
        client = WebResearchClient()

        with patch.object(client.async_client, "post") as mock_post:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "url": "https://example.com",
                "title": "Kubernetes Documentation",
                "content": "K8s content here",
                "summary": "K8s overview",
                "links": [],
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            result = await client.research(
                topic="Kubernetes OOMKilled",
                sources=["https://kubernetes.io/docs"],
            )

            assert result["topic"] == "Kubernetes OOMKilled"
            assert result["sources_crawled"] == 1
            assert len(result["findings"]) == 1

    @pytest.mark.asyncio
    async def test_is_available_success(self):
        """Test availability check when server is up."""
        client = WebResearchClient()

        with patch.object(client.async_client, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            available = await client.is_available()
            assert available is True

    @pytest.mark.asyncio
    async def test_is_available_failure(self):
        """Test availability check when server is down."""
        client = WebResearchClient()

        with patch.object(client.async_client, "get") as mock_get:
            mock_get.side_effect = Exception("Connection refused")

            available = await client.is_available()
            assert available is False


class TestFallbackResearchClient:
    """Tests for FallbackResearchClient."""

    @pytest.mark.asyncio
    async def test_fallback_crawl_success(self):
        """Test fallback crawl with httpx."""
        client = FallbackResearchClient()

        with patch.object(client.async_client, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = """
                <html><head><title>Test Page</title></head>
                <body>Content here</body></html>
            """
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = await client.crawl("https://example.com")

            assert result.url == "https://example.com"
            assert result.title == "Test Page"
            assert "Content here" in result.content

    @pytest.mark.asyncio
    async def test_fallback_crawl_error(self):
        """Test fallback crawl with error."""
        client = FallbackResearchClient()

        with patch.object(client.async_client, "get") as mock_get:
            mock_get.side_effect = Exception("DNS not found")

            result = await client.crawl("https://nonexistent.com")

            assert result.error is not None
            assert result.content == ""

    @pytest.mark.asyncio
    async def test_fallback_research(self):
        """Test fallback research."""
        client = FallbackResearchClient()

        with patch.object(client.async_client, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = "<html><title>Page</title></html>"
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            result = await client.research(
                topic="test",
                sources=["https://example.com"],
            )

            assert result["topic"] == "test"
            assert result["sources_crawled"] == 1

    @pytest.mark.asyncio
    async def test_fallback_research_no_sources(self):
        """Test fallback research without sources."""
        client = FallbackResearchClient()

        result = await client.research("test", sources=None)

        assert result["error"] == "No sources provided"
        assert result["results"] == []


class TestGetResearchClient:
    """Tests for get_research_client function."""

    @pytest.mark.asyncio
    async def test_get_crawl4ai_client(self):
        """Test getting crawl4ai client when available."""
        client = WebResearchClient()

        with patch.object(client.async_client, "get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response

            result = await get_research_client()
            assert isinstance(result, WebResearchClient)

            await result.close()

    @pytest.mark.asyncio
    async def test_get_fallback_client(self):
        """Test getting fallback client when crawl4ai unavailable."""
        client = WebResearchClient()

        with patch.object(client.async_client, "get") as mock_get:
            mock_get.side_effect = Exception("Unavailable")

            result = await get_research_client()
            assert isinstance(result, FallbackResearchClient)

            await result.close()
