"""
LangGraph Config Runner — FastAPI Backend
Proxies requests to the NVIDIA API endpoint (OpenAI-compatible) so the key stays server-side.

NVIDIA API uses OpenAI-compatible format:
  Base URL: https://integrate.api.nvidia.com/v1
  Models: minimaxai/minimax-m2.7, etc.

Request body (OpenAI format):
  {
    "model": "minimaxai/minimax-m2.7",
    "messages": [{ "role": "user"|"assistant", "content": "..." }],
    "tools": [{ "type": "function", "function": {...} }],    # optional
    "max_tokens": 1000
  }

Response body (normalized to Anthropic-compatible format for the frontend):
  {
    "content": [
      { "type": "text", "text": "..." }           # for text parts
      | { "type": "tool_use", "id": "...", "name": "...", "input": {...} }
    ],
    "stop_reason": "end_turn" | "tool_use",
    "usage": { "input_tokens": N, "output_tokens": N }
  }

Tool results sent from the frontend follow the Anthropic format:
  { "type": "tool_result", "tool_use_id": "...", "content": "..." }
"""

import os
import json
from openai import AsyncOpenAI
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="LangGraph Runner API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

NVIDIA_BASE = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "mistralai/devstral-2-123b-instruct-2512"


# ─── Pydantic models ──────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    model: str = DEFAULT_MODEL
    max_tokens: int = 1000
    system: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None


# ─── Format converters ────────────────────────────────────────────────────────

def _anthropic_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool schema → OpenAI function tools."""
    openai_tools = []
    for t in tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            }
        })
    return openai_tools


def _anthropic_messages_to_openai(messages: list[dict]) -> list[dict]:
    """
    Convert Anthropic-style messages → OpenAI messages array.

    Both use "user" | "assistant" roles.
    Anthropic content may be a string or a list of blocks:
      { "type": "text", "text": "..." }
      { "type": "tool_use", "id": "...", "name": "...", "input": {...} }
      { "type": "tool_result", "tool_use_id": "...", "content": "..." }

    OpenAI uses string content or tool_calls list.
    """
    openai_messages = []
    for msg in messages:
        role = msg["role"]  # "user" or "assistant"
        raw = msg["content"]

        if isinstance(raw, str):
            openai_messages.append({"role": role, "content": raw})
            continue

        # Handle Anthropic content blocks
        text_parts = []
        tool_calls = []

        for block in raw:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block.get("input", {})),
                    }
                })
            elif btype == "tool_result":
                # Convert tool_result to tool message (OpenAI format)
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": block.get("content", ""),
                })

        # If there's text content or tool calls, add as assistant message
        if text_parts or tool_calls:
            msg_content = "\n".join(text_parts) if text_parts else None
            openai_msg = {"role": role}
            if msg_content:
                openai_msg["content"] = msg_content
            if tool_calls:
                openai_msg["tool_calls"] = tool_calls
            openai_messages.append(openai_msg)

    return openai_messages


def _openai_response_to_anthropic(openai_resp: dict) -> dict:
    """Normalize OpenAI chat completion response → Anthropic-compatible shape."""
    choices = openai_resp.get("choices", [])
    if not choices:
        return {
            "content": [{"type": "text", "text": ""}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }

    choice = choices[0]
    finish_reason = choice.get("finish_reason", "stop")
    message = choice.get("message", {})

    content_blocks = []
    has_tool_use = False

    # Handle text content
    if message.get("content"):
        content_blocks.append({"type": "text", "text": message["content"]})

    # Handle tool calls
    if message.get("tool_calls"):
        has_tool_use = True
        for tool_call in message["tool_calls"]:
            try:
                input_obj = json.loads(tool_call.get("function", {}).get("arguments", "{}"))
            except json.JSONDecodeError:
                input_obj = {}

            content_blocks.append({
                "type": "tool_use",
                "id": tool_call.get("id", ""),
                "name": tool_call.get("function", {}).get("name", ""),
                "input": input_obj,
            })

    # Map finish_reason
    stop_reason = "end_turn"
    if has_tool_use or finish_reason == "tool_calls":
        stop_reason = "tool_use"
    elif finish_reason == "length":
        stop_reason = "max_tokens"

    usage_meta = openai_resp.get("usage", {})
    return {
        "content": content_blocks,
        "stop_reason": stop_reason,
        "usage": {
            "input_tokens": usage_meta.get("prompt_tokens", 0),
            "output_tokens": usage_meta.get("completion_tokens", 0),
        },
    }


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/chat")
async def proxy_chat(req: ChatRequest):
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="NVIDIA_API_KEY not set")

    # Use provided model or default
    model = req.model

    client = AsyncOpenAI(
        base_url=NVIDIA_BASE,
        api_key=api_key,
    )

    try:
        # Build messages array, prepending system prompt if provided
        messages = _anthropic_messages_to_openai(req.messages)
        if req.system:
            messages.insert(0, {"role": "system", "content": req.system})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": req.max_tokens,
        }
        if req.tools:
            payload["tools"] = _anthropic_tools_to_openai(req.tools)

        completion = await client.chat.completions.create(**payload)

        # Convert the response to dict format
        resp_dict = completion.model_dump()
        normalized = _openai_response_to_anthropic(resp_dict)
        return JSONResponse(content=normalized)

    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream request error: {str(e)}")
