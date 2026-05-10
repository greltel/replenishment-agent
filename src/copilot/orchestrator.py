"""
Copilot orchestrator — coordinates LLM ↔ tools ↔ user.

The flow:
  1. User sends a question
  2. We send {system_prompt, history, user_msg, tools} to Ollama
  3. Ollama responds with either text (final answer) or tool_calls
  4. If tool_calls: execute each tool, append results to history, loop
  5. Otherwise: return the text answer

Tool-use loop has a hard limit (MAX_TOOL_ITERATIONS) to prevent runaway.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from src.copilot.llm_client import (
    OllamaClient, ChatMessage, ChatResponse, OllamaError, diagnose
)
from src.copilot.prompts import get_system_prompt
from src.copilot.tools import TOOL_SCHEMAS, execute_tool
from src.data_layer.repository import Repository
from src.utils.logger import log


MAX_TOOL_ITERATIONS = 5    # hard cap per user turn


@dataclass
class CopilotResponse:
    """Final response to the user, with full trace for transparency."""
    text: str                                 # user-facing answer
    tool_calls_made: list[dict] = field(default_factory=list)
    iterations: int = 0
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class Copilot:
    """Orchestrates a conversation with the LLM, using tools as needed."""

    def __init__(
        self,
        repo: Repository,
        client: Optional[OllamaClient] = None,
        max_iterations: int = MAX_TOOL_ITERATIONS,
    ):
        self.repo = repo
        self.client = client or OllamaClient()
        self.max_iterations = max_iterations
        self.history: list[ChatMessage] = [
            ChatMessage(role="system", content=get_system_prompt())
        ]

    # ---------- Public API ----------
    def health_check(self) -> dict:
        """Run diagnose() against the configured Ollama client."""
        return diagnose(self.client)

    def reset(self) -> None:
        """Clear conversation history (keep system prompt)."""
        self.history = [self.history[0]] if self.history else [
            ChatMessage(role="system", content=get_system_prompt())
        ]

    def ask(self, user_message: str) -> CopilotResponse:
        """Send one user message, run the tool-use loop, return final answer."""
        self.history.append(ChatMessage(role="user", content=user_message))

        tool_calls_log: list[dict] = []

        for iteration in range(self.max_iterations):
            try:
                response = self.client.chat(
                    messages=self.history,
                    tools=TOOL_SCHEMAS,
                )
            except OllamaError as e:
                err = f"LLM call failed: {e}"
                log.error(err)
                return CopilotResponse(
                    text="Δεν μπόρεσα να επικοινωνήσω με το LLM. Ελέγξτε ότι "
                         "τρέχει το Ollama (`ollama serve`).",
                    iterations=iteration,
                    error=err,
                )

            # Append assistant response to history (with possible tool_calls)
            self.history.append(ChatMessage(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls or None,
            ))

            # No tool calls → final answer
            if not response.has_tool_calls:
                return CopilotResponse(
                    text=response.content or "(empty response)",
                    tool_calls_made=tool_calls_log,
                    iterations=iteration + 1,
                )

            # Tool calls requested — execute each and append results
            for tc in response.tool_calls:
                fn = tc.get("function", {}) or {}
                name = fn.get("name", "")
                raw_args = fn.get("arguments", {}) or {}

                # Ollama may return arguments as dict or as JSON string
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {}
                else:
                    args = raw_args

                log.info(f"Copilot tool call: {name}({args})")
                result = execute_tool(name, args, self.repo)

                tool_calls_log.append({
                    "name":   name,
                    "args":   args,
                    "result": result[:500] + ("…" if len(result) > 500 else ""),
                })

                self.history.append(ChatMessage(
                    role="tool",
                    content=result,
                    tool_name=name,
                ))

        # Hit iteration limit — return whatever last assistant message we have
        last_assistant = next(
            (m for m in reversed(self.history) if m.role == "assistant"),
            None,
        )
        return CopilotResponse(
            text=(last_assistant.content if last_assistant else "")
                  or "(no response generated within iteration limit)",
            tool_calls_made=tool_calls_log,
            iterations=self.max_iterations,
            error="Reached max tool iterations without final answer",
        )
