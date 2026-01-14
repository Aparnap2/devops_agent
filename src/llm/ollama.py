"""Ollama client using OpenAI SDK compatibility.

Ollama provides an OpenAI-compatible API endpoint.
"""

import json
import logging
from typing import Any, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel

from src.config import settings

logger = logging.getLogger(__name__)


class LLMResponse(BaseModel):
    """Structured LLM response."""
    content: str
    model: str
    usage: Optional[dict[str, Any]] = None


class OllamaClient:
    """OpenAI-compatible client for local Ollama instance."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: str = "ollama",  # Ollama doesn't require real key
        timeout: int = 120,
    ):
        """Initialize Ollama client.

        Args:
            base_url: Ollama server URL
            model: Model name
            api_key: API key ( Ollama accepts any value)
            timeout: Request timeout in seconds
        """
        self.base_url = base_url or settings.ollama_base_url
        self.model = model or settings.ollama_model
        self.timeout = timeout

        self._client = AsyncOpenAI(
            base_url=f"{self.base_url}/v1",
            api_key=api_key,
            timeout=timeout,
        )

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Generate text response.

        Args:
            prompt: User prompt
            system: System prompt
            temperature: Generation temperature
            max_tokens: Maximum tokens to generate

        Returns:
            LLMResponse with generated content
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return LLMResponse(
            content=response.choices[0].message.content,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else None,
                "completion_tokens": response.usage.completion_tokens if response.usage else None,
                "total_tokens": response.usage.total_tokens if response.usage else None,
            },
        )

    async def generate_structured(
        self,
        prompt: str,
        schema: dict[str, Any],
        system: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generate structured JSON output matching a schema.

        Args:
            prompt: User prompt
            schema: JSON Schema for output
            system: System prompt

        Returns:
            Parsed JSON response
        """
        schema_str = json.dumps(schema, indent=2)

        full_system = system or ""
        full_system += f"""

You must output valid JSON matching this schema:
{schema_str}

Do not include any additional text or formatting - only the JSON object.
"""

        messages = []
        if full_system:
            messages.append({"role": "system", "content": full_system})
        messages.append({"role": "user", "content": prompt})

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        text = response.choices[0].message.content
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            # Try to extract JSON from markdown
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            return json.loads(text)

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Chat completion.

        Args:
            messages: List of messages with "role" and "content"
            temperature: Generation temperature
            max_tokens: Maximum tokens

        Returns:
            LLMResponse with generated content
        """
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return LLMResponse(
            content=response.choices[0].message.content,
            model=response.model,
        )

    async def is_available(self) -> bool:
        """Check if Ollama is running and model is available."""
        try:
            await self._client.models.list()
            return True
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return False

    async def close(self):
        """Close the client."""
        await self._client.close()


# Global client instance
_ollama_client: Optional[OllamaClient] = None


def get_ollama_client() -> OllamaClient:
    """Get or create global Ollama client."""
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient()
    return _ollama_client


async def close_ollama_client():
    """Close the global Ollama client."""
    global _ollama_client
    if _ollama_client is not None:
        await _ollama_client.close()
        _ollama_client = None
