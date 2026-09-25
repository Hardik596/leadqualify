"""The sales agent: a tool-calling loop over MCP tools, followed by a
structured-output extraction that updates the lead's qualification state."""
from __future__ import annotations

import json

from fastmcp import Client

from app.llm import BaseLLM
from app.models import ChatTurn, Lead, LeadQualification, MessageResponse, ToolCall
from app.tools_server import mcp as default_tool_server

SYSTEM_PROMPT = """You are Priya, a sales assistant for Sharma Packaging, an Indian SME that sells
corrugated boxes, bubble wrap and custom printed cartons. You reply on WhatsApp, so keep
messages short (max 3 sentences), warm and professional. Never invent prices or lead times:
always call `product_catalog` first. Your goal is to QUALIFY the lead by learning, one or two
questions at a time: product interest, quantity, budget, timeline, and city.
Once you know product, quantity, budget and timeline, call `score_lead`. If the tier is
"hot" or "warm", offer a callback and, only if they agree and give a time, call `book_callback`.
If the lead is clearly not a fit (e.g. wants something we don't sell), say so politely."""

EXTRACT_PROMPT = """Read the conversation between a sales assistant and a lead. Fill the schema
with only what the LEAD explicitly said. Leave unknown fields null.

Exactly four fields are REQUIRED to qualify: product_interest, quantity, budget_inr, timeline.
name, company and city are optional: never list them in missing_fields.

status rules, apply the first that matches:
- "disqualified": the lead wants something the business does not sell, or declined to continue.
- "qualified": all four required fields are known (even if the quantity is below minimum order
  or the budget is low; scoring is a separate step).
- "in_progress": anything else. Never return "new" once the lead has sent a message.

missing_fields = the required fields (from the four above) that are still unknown, else []."""


REQUIRED_FIELDS = ("product_interest", "quantity", "budget_inr", "timeline")


def finalize(q: LeadQualification) -> LeadQualification:
    """Derive status and missing_fields in code. The LLM is good at extracting facts and at
    spotting a disqualifying intent; it is unreliable at applying a fixed business rule
    (it kept marking below-minimum-order leads as in_progress). Rules belong in code."""
    if q.status == "disqualified":
        return q.model_copy(update={"missing_fields": []})
    missing = [f for f in REQUIRED_FIELDS if getattr(q, f) is None]
    return q.model_copy(update={"status": "qualified" if not missing else "in_progress", "missing_fields": missing})


def _history_to_messages(lead: Lead) -> list[dict]:
    return [{"role": t.role, "text": t.content} for t in lead.history]


class SalesAgent:
    def __init__(self, llm: BaseLLM, tool_server=default_tool_server, max_tool_rounds: int = 5):
        self.llm = llm
        self.tool_server = tool_server
        self.max_tool_rounds = max_tool_rounds

    async def respond(self, lead: Lead, user_message: str) -> MessageResponse:
        lead.history.append(ChatTurn(role="user", content=user_message))
        messages = _history_to_messages(lead)
        turn_tool_calls: list[ToolCall] = []
        reply = "Sorry, I could not process that. Could you rephrase?"

        # In-memory MCP client: same protocol as a remote server, zero network in tests.
        async with Client(self.tool_server) as client:
            tools = [
                {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
                for t in await client.list_tools()
            ]
            for _ in range(self.max_tool_rounds):
                resp = self.llm.chat(SYSTEM_PROMPT, messages, tools)
                if not resp.function_calls:
                    reply = resp.text or reply
                    break
                messages.append({"role": "assistant", "function_calls": resp.function_calls, "raw": resp.raw})
                results = []
                for call in resp.function_calls:
                    result = await client.call_tool(call["name"], call["args"], raise_on_error=False)
                    payload = result.data if result.data is not None else "".join(
                        getattr(c, "text", "") for c in result.content
                    )
                    results.append({"name": call["name"], "response": payload})
                    turn_tool_calls.append(ToolCall(name=call["name"], args=call["args"], result=json.dumps(payload)))
                messages.append({"role": "tool", "results": results})
            else:  # loop exhausted without a text reply
                reply = "Let me get a colleague to help with that. Can I have your number?"

        lead.history.append(ChatTurn(role="assistant", content=reply))
        lead.tool_calls.extend(turn_tool_calls)
        transcript = "\n".join(f"{t.role.upper()}: {t.content}" for t in lead.history)
        lead.qualification = finalize(self.llm.extract(EXTRACT_PROMPT, transcript, LeadQualification))
        return MessageResponse(reply=reply, qualification=lead.qualification, tool_calls=turn_tool_calls)
