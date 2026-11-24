"""Tests for the AI Copilot module."""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.copilot.llm_client import (
    OllamaClient, ChatMessage, ChatResponse, OllamaError, diagnose
)
from src.copilot.orchestrator import Copilot, CopilotResponse
from src.copilot.tools import (
    TOOL_SCHEMAS, TOOL_FUNCTIONS, execute_tool,
    get_summary, get_abc_distribution,
)


# ============================================================
# Tool schemas validation
# ============================================================
class TestToolSchemas:
    def test_schemas_are_well_formed(self):
        """Each schema must have correct OpenAI-style structure."""
        for schema in TOOL_SCHEMAS:
            assert schema["type"] == "function"
            fn = schema["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn
            assert fn["parameters"]["type"] == "object"

    def test_all_schema_names_have_implementations(self):
        """Every schema name must map to a function in TOOL_FUNCTIONS."""
        schema_names = {s["function"]["name"] for s in TOOL_SCHEMAS}
        impl_names = set(TOOL_FUNCTIONS.keys())
        assert schema_names == impl_names

    def test_schema_count_matches_functions(self):
        assert len(TOOL_SCHEMAS) == len(TOOL_FUNCTIONS)


# ============================================================
# Tool dispatcher
# ============================================================
class TestExecuteTool:
    def test_unknown_tool_returns_error(self):
        repo = MagicMock()
        result = execute_tool("nonexistent_tool", {}, repo)
        data = json.loads(result)
        assert "error" in data
        assert "Unknown tool" in data["error"]

    def test_returns_json_string(self):
        repo = MagicMock()
        repo.session.query.return_value.scalar.return_value = 0
        result = execute_tool("get_summary", {}, repo)
        # Must be valid JSON
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_invalid_args_returns_error(self):
        repo = MagicMock()
        result = execute_tool("get_material_details", {"bad_arg": "x"}, repo)
        data = json.loads(result)
        assert "error" in data


# ============================================================
# Tool implementations (with real in-memory DB)
# ============================================================
class TestToolsAgainstDB:
    def test_get_summary_with_empty_db(self, in_memory_repo):
        result = get_summary(in_memory_repo)
        assert result["total_materials"] == 0
        assert result["total_proposals"] == 0
        assert result["expedite_alerts"] == 0

    def test_get_abc_distribution_empty(self, in_memory_repo):
        result = get_abc_distribution(in_memory_repo)
        assert isinstance(result, dict)
        assert "materials_by_class" in result
        assert "proposals_by_class" in result

    def test_get_material_details_not_found(self, in_memory_repo):
        from src.copilot.tools import get_material_details
        result = get_material_details(in_memory_repo, "DOES_NOT_EXIST")
        assert "error" in result


# ============================================================
# Ollama client (without actually hitting Ollama)
# ============================================================
class TestOllamaClient:
    def test_default_init(self):
        client = OllamaClient()
        assert client.base_url == "http://localhost:11434"
        assert client.model == "llama3.1:8b"

    def test_strips_trailing_slash(self):
        client = OllamaClient(base_url="http://example.com/")
        assert client.base_url == "http://example.com"

    def test_is_available_handles_connection_error(self):
        """If Ollama is not running, is_available() should return False."""
        client = OllamaClient(base_url="http://nonexistent-host-12345:99999")
        assert client.is_available() is False

    def test_list_models_handles_connection_error(self):
        client = OllamaClient(base_url="http://nonexistent-host-12345:99999")
        assert client.list_models() == []

    def test_chat_message_to_dict(self):
        msg = ChatMessage(role="user", content="hello")
        assert msg.to_dict() == {"role": "user", "content": "hello"}

    def test_chat_message_with_tool_calls(self):
        tcs = [{"function": {"name": "x"}}]
        msg = ChatMessage(role="assistant", content="", tool_calls=tcs)
        d = msg.to_dict()
        assert d["tool_calls"] == tcs


# ============================================================
# Diagnostics
# ============================================================
class TestDiagnose:
    def test_unreachable_server(self):
        client = OllamaClient(base_url="http://nonexistent-host-12345:99999")
        result = diagnose(client)
        assert result["ok"] is False
        assert "not reachable" in result["error"].lower()

    @patch("src.copilot.llm_client.OllamaClient.is_available", return_value=True)
    @patch("src.copilot.llm_client.OllamaClient.list_models",
           return_value=["other-model"])
    def test_model_not_pulled(self, _models, _avail):
        client = OllamaClient(model="llama3.1:8b")
        result = diagnose(client)
        assert result["ok"] is False
        assert "not pulled" in result["error"].lower()

    @patch("src.copilot.llm_client.OllamaClient.is_available", return_value=True)
    @patch("src.copilot.llm_client.OllamaClient.list_models",
           return_value=["llama3.1:8b"])
    def test_all_good(self, _models, _avail):
        client = OllamaClient(model="llama3.1:8b")
        result = diagnose(client)
        assert result["ok"] is True


# ============================================================
# Orchestrator (with mocked LLM)
# ============================================================
class TestOrchestrator:
    def test_init_adds_system_prompt(self, in_memory_repo):
        cop = Copilot(repo=in_memory_repo)
        assert len(cop.history) == 1
        assert cop.history[0].role == "system"

    def test_reset_keeps_system_prompt(self, in_memory_repo):
        cop = Copilot(repo=in_memory_repo)
        cop.history.append(ChatMessage(role="user", content="hi"))
        cop.history.append(ChatMessage(role="assistant", content="hello"))
        cop.reset()
        assert len(cop.history) == 1
        assert cop.history[0].role == "system"

    def test_ask_returns_text_response(self, in_memory_repo):
        cop = Copilot(repo=in_memory_repo)
        # Mock the LLM to return plain text (no tool calls)
        cop.client = MagicMock()
        cop.client.chat.return_value = ChatResponse(
            content="Hello, planner!",
            tool_calls=[],
        )
        result = cop.ask("Hi")
        assert isinstance(result, CopilotResponse)
        assert result.text == "Hello, planner!"
        assert result.iterations == 1
        assert result.error is None

    def test_ask_handles_tool_call_loop(self, in_memory_repo):
        cop = Copilot(repo=in_memory_repo)
        cop.client = MagicMock()

        # First call: LLM asks for a tool
        # Second call: LLM produces final text
        cop.client.chat.side_effect = [
            ChatResponse(
                content="",
                tool_calls=[{
                    "function": {"name": "get_summary", "arguments": {}}
                }],
            ),
            ChatResponse(content="Here is the summary."),
        ]
        result = cop.ask("Give me a summary")
        assert result.text == "Here is the summary."
        assert len(result.tool_calls_made) == 1
        assert result.tool_calls_made[0]["name"] == "get_summary"

    def test_ask_handles_ollama_error(self, in_memory_repo):
        cop = Copilot(repo=in_memory_repo)
        cop.client = MagicMock()
        cop.client.chat.side_effect = OllamaError("Connection refused")
        result = cop.ask("Hi")
        assert result.error is not None
        assert "Ollama" in result.text or "LLM" in result.text

    def test_max_iterations_enforced(self, in_memory_repo):
        cop = Copilot(repo=in_memory_repo, max_iterations=2)
        cop.client = MagicMock()
        # LLM keeps asking for tools forever
        cop.client.chat.return_value = ChatResponse(
            content="",
            tool_calls=[{"function": {"name": "get_summary", "arguments": {}}}],
        )
        result = cop.ask("Loop forever")
        assert result.error is not None
        assert "iter" in result.error.lower()
        assert result.iterations == 2
