"""FastAPI service. Run with:  uvicorn app.main:app --reload --env-file .env
Sales desk UI at http://127.0.0.1:8000/, API docs at http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.agent import SalesAgent
from app.llm import GeminiLLM
from app.models import CreateLeadRequest, Lead, MessageRequest, MessageResponse
from app.store import LeadStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Built once per process; tests overwrite app.state.agent with a ScriptedLLM agent.
    if not hasattr(app.state, "agent"):
        if not os.environ.get("GEMINI_API_KEY"):
            raise RuntimeError("Set GEMINI_API_KEY (see .env.example)")
        app.state.agent = SalesAgent(GeminiLLM())
    if not hasattr(app.state, "store"):
        app.state.store = LeadStore()
    yield


app = FastAPI(title="LeadQualify Agent", version="0.1.0", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def get_store(request: Request) -> LeadStore:
    return request.app.state.store


def get_agent(request: Request) -> SalesAgent:
    return request.app.state.agent


async def respond_or_502(agent: SalesAgent, lead: Lead, content: str) -> MessageResponse:
    mark = len(lead.history)
    try:
        return await agent.respond(lead, content)
    except Exception as exc:
        # Roll back the lead's turn so a manual resend doesn't duplicate it in the history.
        del lead.history[mark:]
        code = getattr(exc, "code", None)
        message = getattr(exc, "message", None) or str(exc)
        raise HTTPException(502, f"Model call failed ({code}): {message}" if code else f"Model call failed: {message}")


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/leads", response_model=Lead, status_code=201)
async def create_lead(body: CreateLeadRequest, store: LeadStore = Depends(get_store),
                      agent: SalesAgent = Depends(get_agent)):
    lead = store.create(body.source)
    if body.first_message:
        await respond_or_502(agent, lead, body.first_message)
    return lead


@app.get("/leads", response_model=list[Lead])
def list_leads(store: LeadStore = Depends(get_store)):
    return store.list()


@app.get("/leads/{lead_id}", response_model=Lead)
def get_lead(lead_id: str, store: LeadStore = Depends(get_store)):
    lead = store.get(lead_id)
    if not lead:
        raise HTTPException(404, "lead not found")
    return lead


@app.post("/leads/{lead_id}/messages", response_model=MessageResponse)
async def send_message(lead_id: str, body: MessageRequest, store: LeadStore = Depends(get_store),
                       agent: SalesAgent = Depends(get_agent)):
    lead = store.get(lead_id)
    if not lead:
        raise HTTPException(404, "lead not found")
    return await respond_or_502(agent, lead, body.content)
