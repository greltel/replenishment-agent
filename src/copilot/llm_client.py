"""
Ollama HTTP client.

Thin wrapper around Ollama's REST API (default: http://localhost:11434).
Supports plain chat completion with optional tool-use protocol.

Why Ollama?
  • Local inference → εταιρικά δεδομένα ποτέ δεν φεύγουν εκτός laptop
  • Open-source models (Llama 3.1, Qwen 2.5, Mistral)
  • Zero cost, fully reproducible for thesis evaluation
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import requests

from src.utils.logger import log


# ============================================================
# Configuration
# ============================================================
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1:8b"
DEFAULT_TIMEOUT = 120  # seconds


# ============================================================
# Data classes
# ============================================================
@dataclass
class ChatMessage:
    """One turn in a conversation."""
    role: str           # 'system' | 'user' | 'assistant' | 'tool'
    content: str
    tool_calls: Optional[list[dict]] = None
    tool_name: Optional[str] = None  # for role='tool'

    def to_dict(self) -> dict:
        d = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_name and self.role == "tool":
            d["name"] = self.tool_name
        return d


@dataclass
class ChatResponse:
    """Single response from the model."""
    content: str
    tool_calls: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


# ============================================================
# Client
# ============================================================
class OllamaClient:
    """Synchronous client for Ollama's REST API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    # ---------- Health check ----------
    def is_available(self) -> bool:
        """Quick ping to see if Ollama server is up."""
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return r.status_code == 200
        except (requests.RequestException, OSError):
            return False

    def list_models(self) -> list[str]:
        """Names of models pulled locally."""
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except requests.RequestException:
            return []

    def has_model(self, model: str | None = None) -> bool:
        """Whether the configured model is available locally."""
        target = model or self.model
        return any(m.startswith(target) for m in self.list_models())

    # ---------- Chat ----------
    def chat(
        self,
        messages: list[ChatMessage],
        tools: Optional[list[dict]] = None,
        temperature: float = 0.2,
    ) -> ChatResponse:
        """Single non-streaming chat completion.

        Args:
            messages: Conversation so far
            tools: OpenAI-style tool schemas. Pass None for plain chat.
            temperature: Sampling temperature

        Returns:
            ChatResponse with .content (str) and optional .tool_calls (list).
        """
        payload = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = tools

        url = f"{self.base_url}/api/chat"
        log.debug(f"POST {url} (model={self.model}, n_msgs={len(messages)})")

        try:
            r = requests.post(url, json=payload, timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as e:
            log.error(f"Ollama request failed: {e}")
            raise OllamaError(f"Ollama API error: {e}") from e

        data = r.json()
        msg = data.get("message", {}) or {}

        return ChatResponse(
            content=msg.get("content", "") or "",
            tool_calls=msg.get("tool_calls", []) or [],
            raw=data,
        )


# ============================================================
# Exceptions
# ============================================================
class OllamaError(Exception):
    """Raised on Ollama API failures."""


class OllamaUnavailableError(OllamaError):
    """Raised when the Ollama server is not running / not reachable."""


# ============================================================
# Diagnostics helper
# ============================================================
def diagnose(client: OllamaClient) -> dict:
    """Returns a dict describing the current state of the Ollama setup.

    Useful for showing helpful error messages in the dashboard.
    """
    if not client.is_available():
        return {
            "ok": False,
            "error": "Ollama server is not reachable",
            "hint": (
                f"Make sure Ollama is running. Visit https://ollama.com to install. "
                f"Then run: `ollama serve` (or just open the Ollama app). "
                f"Expected URL: {client.base_url}"
            ),
        }

    models = client.list_models()
    if not client.has_model():
        return {
            "ok": False,
            "error": f"Model '{client.model}' is not pulled locally",
            "hint": (
                f"Run in terminal:  ollama pull {client.model}\n"
                f"Currently available models: {', '.join(models) or '(none)'}"
            ),
            "available_models": models,
        }

    return {
        "ok": True,
        "model": client.model,
        "available_models": models,
    }
