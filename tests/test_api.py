"""End-to-end API tests with a scripted LLM: exercise FastAPI -> agent loop ->
MCP tools -> structured extraction without any network or API key."""
import pytest
from fastapi.testclient import TestClient

from app.agent import SalesAgent
from app.llm import ScriptedLLM
from app.main import app
from app.store import LeadStore


@pytest.fixture
def client():
    llm = ScriptedLLM(
        chat_steps=[
            # turn 1: model decides to call a tool, then answers
            [{"name": "product_catalog", "args": {"query": "corrugated boxes"}}],
            "Corrugated boxes start at Rs 18/unit with a 500 MOQ. How many do you need per month?",
            # turn 2: plain answer
            "Great, 2000 boxes fits. What budget and timeline are you working with?",
        ],
        extract_steps=[
            {"product_interest": "corrugated boxes", "status": "in_progress",
             "missing_fields": ["quantity", "budget_inr", "timeline"]},
            {"product_interest": "corrugated boxes", "quantity": 2000, "status": "in_progress",
             "missing_fields": ["budget_inr", "timeline"]},
        ],
    )
    app.state.agent = SalesAgent(llm)
    app.state.store = LeadStore()
    with TestClient(app) as c:
        c.llm = llm
        yield c


def test_full_conversation_flow(client):
    r = client.post("/leads", json={"source": "whatsapp", "first_message": "I need corrugated boxes"})
    assert r.status_code == 201
    lead = r.json()
    assert lead["qualification"]["product_interest"] == "corrugated boxes"
    assert [t["name"] for t in lead["tool_calls"]] == ["product_catalog"]
    assert "corrugated boxes" in lead["tool_calls"][0]["result"]  # real MCP result, not a mock
    assert len(lead["history"]) == 2

    r = client.post(f"/leads/{lead['id']}/messages", json={"content": "2000 per month"})
    assert r.status_code == 200
    body = r.json()
    assert body["qualification"]["quantity"] == 2000
    assert body["tool_calls"] == []

    # the LLM saw the whole history on turn 2, and the tool list came from MCP
    last_call = client.llm.calls[-1]
    assert len(last_call["messages"]) == 3
    assert "score_lead" in last_call["tools"]

    assert len(client.get(f"/leads/{lead['id']}").json()["history"]) == 4


def test_validation_and_404(client):
    assert client.get("/leads/nope").status_code == 404
    r = client.post("/leads", json={"source": "web"})
    assert client.post(f"/leads/{r.json()['id']}/messages", json={"content": ""}).status_code == 422
    assert client.post("/leads", json={"source": "carrier-pigeon"}).status_code == 422


def test_agent_stops_after_max_tool_rounds():
    """A model that loops on tool calls forever must be cut off, not hang the request."""
    llm = ScriptedLLM(chat_steps=[[{"name": "crm_lookup", "args": {"phone": "1"}}]] * 10)
    app.state.agent = SalesAgent(llm, max_tool_rounds=3)
    app.state.store = LeadStore()
    with TestClient(app) as c:
        body = c.post("/leads", json={"first_message": "hi"}).json()
    assert len(body["tool_calls"]) == 3
    assert "colleague" in body["history"][-1]["content"]


def test_model_failure_returns_502_and_rolls_back_turn():
    """A provider outage must not leave a dangling user turn that a resend would duplicate."""
    class DownLLM(ScriptedLLM):
        def chat(self, system, messages, tools):
            raise RuntimeError("503 UNAVAILABLE")

    app.state.agent = SalesAgent(DownLLM(chat_steps=[]))
    app.state.store = LeadStore()
    with TestClient(app) as c:
        lead_id = c.post("/leads", json={"source": "whatsapp"}).json()["id"]
        r = c.post(f"/leads/{lead_id}/messages", json={"content": "need boxes"})
        assert r.status_code == 502
        assert "503 UNAVAILABLE" in r.json()["detail"]
        assert c.get(f"/leads/{lead_id}").json()["history"] == []


def test_ui_is_served():
    app.state.agent = SalesAgent(ScriptedLLM(chat_steps=[]))
    app.state.store = LeadStore()
    with TestClient(app) as c:
        assert "Sales desk" in c.get("/").text
        assert c.get("/static/app.js").status_code == 200
