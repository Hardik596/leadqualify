"""Pydantic models: the single source of truth for API payloads, agent state
and the LLM's structured output schema."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ToolCall(BaseModel):
    name: str
    args: dict
    result: str


class LeadQualification(BaseModel):
    """Structured output the LLM must fill after every turn.
    Passed to Gemini as `response_schema`, so the model can only answer in this shape."""

    name: Optional[str] = Field(None, description="Lead's name")
    company: Optional[str] = Field(None, description="Lead's company")
    product_interest: Optional[str] = Field(None, description="Product or service the lead wants")
    quantity: Optional[int] = Field(None, description="Units per order, if stated")
    budget_inr: Optional[int] = Field(None, description="Budget in INR, if stated")
    timeline: Optional[str] = Field(None, description="When they need it, e.g. 'this week', '2 months'")
    city: Optional[str] = None
    status: Literal["new", "in_progress", "qualified", "disqualified"] = "new"
    missing_fields: list[str] = Field(default_factory=list, description="Fields still needed to qualify")


class Lead(BaseModel):
    id: str
    source: Literal["whatsapp", "indiamart", "email", "web"] = "web"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    history: list[ChatTurn] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    qualification: LeadQualification = Field(default_factory=LeadQualification)


# ---- API request / response schemas ----

class CreateLeadRequest(BaseModel):
    source: Literal["whatsapp", "indiamart", "email", "web"] = "web"
    first_message: Optional[str] = Field(None, description="Optional opening message from the lead")


class MessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


class MessageResponse(BaseModel):
    reply: str
    qualification: LeadQualification
    tool_calls: list[ToolCall]
