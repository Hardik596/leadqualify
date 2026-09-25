"""LLM adapters. The agent talks to `BaseLLM`, never to a vendor SDK directly,
so tests can swap in `ScriptedLLM` and production uses `GeminiLLM`.

Message format shared by all adapters (a plain list of dicts):
  {"role": "user", "text": "..."}
  {"role": "assistant", "text": "..."}
  {"role": "assistant", "function_calls": [{"name": .., "args": {..}}], "raw": <vendor object or None>}
  {"role": "tool", "results": [{"name": .., "response": {..}}]}
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResponse:
    text: str | None = None
    function_calls: list[dict] = field(default_factory=list)
    raw: Any = None  # vendor-native content, replayed verbatim on the next call


class BaseLLM:
    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        raise NotImplementedError

    def extract(self, system: str, text: str, schema: Type[T]) -> T:
        raise NotImplementedError


# --------------------------------------------------------------------------- #
class GeminiLLM(BaseLLM):
    """Gemini via google-genai: native function calling + JSON-schema structured output."""

    def __init__(self, model: str | None = None):
        from google import genai  # imported lazily so tests never need the SDK key

        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    def _to_contents(self, messages: list[dict]):
        from google.genai import types

        contents = []
        for m in messages:
            if m["role"] == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=m["text"])]))
            elif m["role"] == "assistant" and "function_calls" in m:
                if m.get("raw") is not None:
                    contents.append(m["raw"])  # keeps Gemini's thought_signature intact
                else:
                    parts = [types.Part(function_call=types.FunctionCall(name=c["name"], args=c["args"]))
                             for c in m["function_calls"]]
                    contents.append(types.Content(role="model", parts=parts))
            elif m["role"] == "assistant":
                contents.append(types.Content(role="model", parts=[types.Part(text=m["text"])]))
            elif m["role"] == "tool":
                parts = [types.Part.from_function_response(name=r["name"], response={"result": r["response"]})
                         for r in m["results"]]
                contents.append(types.Content(role="user", parts=parts))
        return contents

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        from google.genai import types

        declarations = [
            types.FunctionDeclaration(
                name=t["name"], description=t["description"], parameters_json_schema=t["input_schema"]
            )
            for t in tools
        ]
        resp = self.client.models.generate_content(
            model=self.model,
            contents=self._to_contents(messages),
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=[types.Tool(function_declarations=declarations)] if declarations else None,
                temperature=0.3,
            ),
        )
        content = resp.candidates[0].content
        calls = [
            {"name": p.function_call.name, "args": dict(p.function_call.args or {})}
            for p in (content.parts or [])
            if p.function_call
        ]
        return LLMResponse(text=None if calls else resp.text, function_calls=calls, raw=content if calls else None)

    def extract(self, system: str, text: str, schema: Type[T]) -> T:
        from google.genai import types

        resp = self.client.models.generate_content(
            model=self.model,
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,  # Gemini constrains decoding to this Pydantic schema
                temperature=0.0,
            ),
        )
        return resp.parsed if isinstance(resp.parsed, schema) else schema.model_validate_json(resp.text)


# --------------------------------------------------------------------------- #
class ScriptedLLM(BaseLLM):
    """Deterministic stand-in for tests: replays pre-written responses in order.
    `chat_steps`: list of str (final reply) or list[dict] (function calls).
    `extract_steps`: list of dicts validated against the requested schema."""

    def __init__(self, chat_steps: list, extract_steps: list[dict] | None = None):
        self.chat_steps = list(chat_steps)
        self.extract_steps = list(extract_steps or [])
        self.calls: list[dict] = []  # everything the agent sent us, for assertions

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        self.calls.append({"system": system, "messages": messages, "tools": [t["name"] for t in tools]})
        if not self.chat_steps:
            return LLMResponse(text="(script exhausted)")
        step = self.chat_steps.pop(0)
        if isinstance(step, str):
            return LLMResponse(text=step)
        return LLMResponse(function_calls=step)

    def extract(self, system: str, text: str, schema: Type[T]) -> T:
        data = self.extract_steps.pop(0) if self.extract_steps else {}
        return schema.model_validate(data)
