"""LLM module for local model inference."""

from src.llm.ollama import OllamaClient, get_ollama_client

__all__ = ["OllamaClient", "get_ollama_client"]
