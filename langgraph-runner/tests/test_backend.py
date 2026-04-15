"""
Tests for the FastAPI backend — NVIDIA OpenAI-compatible API proxy.
Run with: pytest tests/test_backend.py -v
"""

import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from main import app, _anthropic_tools_to_openai, _anthropic_messages_to_openai, _openai_response_to_anthropic

client = TestClient(app)


# ─── _anthropic_tools_to_openai ──────────────────────────────────────────

def test_tools_to_openai_single_tool():
    """Single tool converts to OpenAI function format."""
    tools = [{
        "name": "web_search",
        "description": "Search the web",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]
        }
    }]
    result = _anthropic_tools_to_openai(tools)
    assert len(result) == 1
    assert result[0]["type"] == "function"
    assert result[0]["function"]["name"] == "web_search"
    assert result[0]["function"]["description"] == "Search the web"
    assert result[0]["function"]["parameters"]["properties"]["query"]["type"] == "string"


def test_tools_to_openai_empty():
    """Empty tools array returns empty list."""
    result = _anthropic_tools_to_openai([])
    assert result == []


def test_tools_to_openai_missing_description():
    """Missing description defaults to empty string."""
    tools = [{
        "name": "calc",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    }]
    result = _anthropic_tools_to_openai(tools)
    assert result[0]["function"]["description"] == ""


# ─── _anthropic_messages_to_openai ──────────────────────────────────────

def test_messages_string_content_passthrough():
    """String content passes through with role intact."""
    msgs = [{"role": "user", "content": "Hello world"}]
    result = _anthropic_messages_to_openai(msgs)
    assert len(result) == 1
    assert result[0]["role"] == "user"
    assert result[0]["content"] == "Hello world"


def test_messages_text_block():
    """Text block is extracted into content string."""
    msgs = [{
        "role": "assistant",
        "content": [{"type": "text", "text": "Hello!"}]
    }]
    result = _anthropic_messages_to_openai(msgs)
    assert result[0]["role"] == "assistant"
    assert result[0]["content"] == "Hello!"


def test_messages_tool_use_block():
    """Tool use block becomes tool_calls entry with json.dumps(input)."""
    msgs = [{
        "role": "assistant",
        "content": [{
            "type": "tool_use",
            "id": "tu_001",
            "name": "web_search",
            "input": {"query": "LangGraph"}
        }]
    }]
    result = _anthropic_messages_to_openai(msgs)
    assert result[0]["role"] == "assistant"
    assert "tool_calls" in result[0]
    assert result[0]["tool_calls"][0]["id"] == "tu_001"
    assert result[0]["tool_calls"][0]["function"]["name"] == "web_search"
    assert result[0]["tool_calls"][0]["function"]["arguments"] == '{"query": "LangGraph"}'


def test_messages_tool_result_block():
    """Tool result block becomes separate tool message."""
    msgs = [{
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": "tu_001",
            "content": "Result text"
        }]
    }]
    result = _anthropic_messages_to_openai(msgs)
    assert len(result) == 1
    assert result[0]["role"] == "tool"
    assert result[0]["tool_call_id"] == "tu_001"
    assert result[0]["content"] == "Result text"


def test_messages_mixed_text_and_tool_blocks():
    """Mixed text and tool_use blocks create single message with both."""
    msgs = [{
        "role": "assistant",
        "content": [
            {"type": "text", "text": "I'll search for that."},
            {"type": "tool_use", "id": "tu_001", "name": "web_search", "input": {"query": "test"}}
        ]
    }]
    result = _anthropic_messages_to_openai(msgs)
    assert result[0]["content"] == "I'll search for that."
    assert len(result[0]["tool_calls"]) == 1


# ─── _openai_response_to_anthropic ──────────────────────────────────────

def test_response_empty_choices():
    """Empty choices returns empty text block and end_turn."""
    openai_resp = {"choices": []}
    result = _openai_response_to_anthropic(openai_resp)
    assert result["content"] == [{"type": "text", "text": ""}]
    assert result["stop_reason"] == "end_turn"
    assert result["usage"]["input_tokens"] == 0
    assert result["usage"]["output_tokens"] == 0


def test_response_text_content():
    """Text response maps to content text block."""
    openai_resp = {
        "choices": [{
            "message": {"content": "Hello there!"},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5}
    }
    result = _openai_response_to_anthropic(openai_resp)
    assert result["content"][0]["type"] == "text"
    assert result["content"][0]["text"] == "Hello there!"
    assert result["stop_reason"] == "end_turn"
    assert result["usage"]["input_tokens"] == 10
    assert result["usage"]["output_tokens"] == 5


def test_response_tool_calls():
    """Tool calls map to tool_use blocks with parsed input."""
    openai_resp = {
        "choices": [{
            "message": {
                "tool_calls": [{
                    "id": "call_123",
                    "function": {"name": "web_search", "arguments": '{"query": "test"}'}
                }]
            },
            "finish_reason": "tool_calls"
        }],
        "usage": {}
    }
    result = _openai_response_to_anthropic(openai_resp)
    assert result["content"][0]["type"] == "tool_use"
    assert result["content"][0]["name"] == "web_search"
    assert result["content"][0]["input"] == {"query": "test"}
    assert result["stop_reason"] == "tool_use"


def test_response_finish_reason_tool_calls():
    """finish_reason 'tool_calls' maps to stop_reason 'tool_use'."""
    openai_resp = {
        "choices": [{
            "message": {"tool_calls": [{"id": "c1", "function": {"name": "calc", "arguments": "{}"}}]},
            "finish_reason": "tool_calls"
        }],
        "usage": {}
    }
    result = _openai_response_to_anthropic(openai_resp)
    assert result["stop_reason"] == "tool_use"


def test_response_finish_reason_length():
    """finish_reason 'length' maps to stop_reason 'max_tokens'."""
    openai_resp = {
        "choices": [{
            "message": {"content": "...truncated"},
            "finish_reason": "length"
        }],
        "usage": {}
    }
    result = _openai_response_to_anthropic(openai_resp)
    assert result["stop_reason"] == "max_tokens"


def test_response_malformed_tool_arguments():
    """Malformed JSON in tool arguments falls back to empty dict."""
    openai_resp = {
        "choices": [{
            "message": {
                "tool_calls": [{
                    "id": "c1",
                    "function": {"name": "calc", "arguments": "not valid json"}
                }]
            },
            "finish_reason": "tool_calls"
        }],
        "usage": {}
    }
    result = _openai_response_to_anthropic(openai_resp)
    assert result["content"][0]["input"] == {}


# ─── GET /health ────────────────────────────────────────────────────────

def test_health():
    """Health endpoint returns 200 with ok status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ─── POST /api/chat ─────────────────────────────────────────────────────

VALID_PAYLOAD = {
    "model": "mistralai/devstral-2-123b-instruct-2512",
    "max_tokens": 100,
    "system": "You are helpful.",
    "messages": [{"role": "user", "content": "Hello"}]
}

MOCK_OPENAI_RESPONSE = {
    "choices": [{
        "message": {"content": "Hi there!"},
        "finish_reason": "stop"
    }],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5}
}


def test_chat_missing_nvidia_api_key(monkeypatch):
    """Missing NVIDIA_API_KEY returns 500 error."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    resp = client.post("/api/chat", json=VALID_PAYLOAD)
    assert resp.status_code == 500
    assert "NVIDIA_API_KEY not set" in resp.json()["detail"]


def test_chat_system_prompt_prepended(monkeypatch):
    """System prompt is prepended to messages at index 0."""
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    captured_payload = {}

    def capture_create(**kwargs):
        captured_payload.update(kwargs)
        mock_resp = MagicMock()
        mock_resp.model_dump.return_value = MOCK_OPENAI_RESPONSE
        return mock_resp

    with patch("main.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=capture_create)
        mock_cls.return_value = mock_client
        resp = client.post("/api/chat", json=VALID_PAYLOAD)

    messages = captured_payload["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "You are helpful."
    assert messages[1]["role"] == "user"


def test_chat_no_tools_omitted(monkeypatch):
    """When no tools provided, tools key is omitted from payload."""
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    captured_payload = {}

    def capture_create(**kwargs):
        captured_payload.update(kwargs)
        mock_resp = MagicMock()
        mock_resp.model_dump.return_value = MOCK_OPENAI_RESPONSE
        return mock_resp

    with patch("main.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=capture_create)
        mock_cls.return_value = mock_client
        resp = client.post("/api/chat", json=VALID_PAYLOAD)

    assert "tools" not in captured_payload


def test_chat_tools_included_when_provided(monkeypatch):
    """When tools provided, they are converted and included in payload."""
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    captured_payload = {}

    def capture_create(**kwargs):
        captured_payload.update(kwargs)
        mock_resp = MagicMock()
        mock_resp.model_dump.return_value = MOCK_OPENAI_RESPONSE
        return mock_resp

    with patch("main.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=capture_create)
        mock_cls.return_value = mock_client

        payload = {
            **VALID_PAYLOAD,
            "tools": [{
                "name": "web_search",
                "description": "Search",
                "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
            }]
        }
        resp = client.post("/api/chat", json=payload)

    assert "tools" in captured_payload
    assert captured_payload["tools"][0]["type"] == "function"
    assert captured_payload["tools"][0]["function"]["name"] == "web_search"


def test_chat_success(monkeypatch):
    """Successful chat request returns 200 with normalized response."""
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

    def create_mock(**kwargs):
        mock_resp = MagicMock()
        mock_resp.model_dump.return_value = MOCK_OPENAI_RESPONSE
        return mock_resp

    with patch("main.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=create_mock)
        mock_cls.return_value = mock_client
        resp = client.post("/api/chat", json=VALID_PAYLOAD)

    assert resp.status_code == 200
    data = resp.json()
    assert data["content"][0]["type"] == "text"
    assert data["content"][0]["text"] == "Hi there!"
    assert data["stop_reason"] == "end_turn"
    assert data["usage"]["input_tokens"] == 10


def test_chat_upstream_error(monkeypatch):
    """Exception from OpenAI client returns 502 with error message."""
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")

    with patch("main.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API rate limit exceeded")
        )
        mock_cls.return_value = mock_client
        resp = client.post("/api/chat", json=VALID_PAYLOAD)

    assert resp.status_code == 502
    assert "Upstream request error" in resp.json()["detail"]
    assert "rate limit" in resp.json()["detail"]
