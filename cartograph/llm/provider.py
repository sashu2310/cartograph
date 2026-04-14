"""LLM provider protocol and factory.

Set CARTOGRAPH_LLM_PROVIDER env var:
    claude  → Anthropic API (default)
    openai  → OpenAI API
    ollama  → Local Ollama

Set the corresponding API key:
    ANTHROPIC_API_KEY for claude
    OPENAI_API_KEY for openai
    OLLAMA_HOST for ollama (defaults to http://localhost:11434)
"""

import os
from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResponse:
    """Response from an LLM provider."""

    content: str
    model: str = ""
    usage: dict | None = None


class LLMProvider(Protocol):
    """Protocol for LLM providers."""

    def narrate(self, system: str, user: str) -> LLMResponse:
        """Send a system + user prompt, get a response."""
        ...


class ClaudeProvider:
    """Anthropic Claude provider."""

    def __init__(self):
        import anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = os.getenv("CARTOGRAPH_LLM_MODEL", "claude-sonnet-4-20250514")

    def narrate(self, system: str, user: str) -> LLMResponse:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return LLMResponse(
            content=response.content[0].text,
            model=response.model,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        )


class OpenAIProvider:
    """OpenAI provider."""

    def __init__(self):
        from openai import OpenAI

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        self._client = OpenAI(api_key=api_key)
        self._model = os.getenv("CARTOGRAPH_LLM_MODEL", "gpt-4o-mini")

    def narrate(self, system: str, user: str) -> LLMResponse:
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            usage={
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens
                if response.usage
                else 0,
            },
        )


class OllamaProvider:
    """Local Ollama provider."""

    def __init__(self):
        import httpx

        self._host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self._model = os.getenv("CARTOGRAPH_LLM_MODEL", "llama3.2")
        self._client = httpx.Client(timeout=120)

    def narrate(self, system: str, user: str) -> LLMResponse:
        resp = self._client.post(
            f"{self._host}/api/chat",
            json={
                "model": self._model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return LLMResponse(
            content=data.get("message", {}).get("content", ""),
            model=self._model,
        )


def get_llm_provider() -> LLMProvider:
    """Factory — returns the configured LLM provider."""
    provider = os.getenv("CARTOGRAPH_LLM_PROVIDER", "claude").lower()

    if provider == "claude":
        return ClaudeProvider()
    elif provider == "openai":
        return OpenAIProvider()
    elif provider == "ollama":
        return OllamaProvider()
    else:
        raise ValueError(
            f"Unknown CARTOGRAPH_LLM_PROVIDER: {provider}. "
            "Use 'claude', 'openai', or 'ollama'."
        )
