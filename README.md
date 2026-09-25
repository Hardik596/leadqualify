# LeadQualify — an agentic lead-qualification service

A WhatsApp-style sales agent for an Indian SME that qualifies inbound leads end to end:
it asks the right questions, looks up real product data through **MCP tools**, scores the
lead, books a callback, and keeps a **typed qualification record** up to date after every turn.
It ships with a **multi-turn evaluation harness** that grades the agent against scripted
conversations before it ever talks to a real lead.

```
lead message ──> FastAPI ──> SalesAgent ──┬─> Gemini (function calling) ──> FastMCP tools
                                          │      product_catalog · crm_lookup · score_lead · book_callback
                                          └─> Gemini (JSON-schema structured output) ──> LeadQualification
```

## Stack

| Layer | Tech | File |
|---|---|---|
| HTTP API | FastAPI + Pydantic v2 | `app/main.py`, `app/models.py` |
| Tools | FastMCP server, consumed over MCP by the agent | `app/tools_server.py` |
| Agent loop | tool-calling loop, max-rounds guard | `app/agent.py` |
| LLM | Gemini via `google-genai` (function calling + `response_schema`) | `app/llm.py` |
| Tests | pytest, deterministic `ScriptedLLM`, no API key needed | `tests/` |
| Evals | YAML conversation scripts + code grader, real model | `evals/` |

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env          # add your GEMINI_API_KEY
uvicorn app.main:app --reload --env-file .env  # UI at http://127.0.0.1:8000/, API docs at /docs
```

```bash
curl -X POST localhost:8000/leads -H "content-type: application/json" \
  -d '{"source":"whatsapp","first_message":"I need corrugated boxes for my food business"}'

curl -X POST localhost:8000/leads/<id>/messages -H "content-type: application/json" \
  -d '{"content":"2000 per month, budget 40000, need in 2 weeks"}'
```

The response carries the reply, the tool calls made on that turn, and the current
`LeadQualification` (product, quantity, budget, timeline, status, missing fields).

## Test and evaluate

```bash
pytest                         # 14 tests, ~5s, offline
python -m evals.run_evals      # plays 4 scripted leads against Gemini, exits 1 on failure
python -m evals.run_evals --only wrong_product_is_disqualified
```

Each eval scenario grades the **end state** of a whole conversation: extracted fields,
qualification status, which tools were and were not called, and reply constraints
(must ask a question, must never say "as an AI"...). Full transcripts land in
`evals/results.json` for debugging a failing prompt.

## Design notes

- **Tools live behind MCP, not inside the agent.** `python -m app.tools_server` serves the same
  tools to Claude Desktop, Cursor or any MCP client. The agent uses FastMCP's in-memory client,
  so tests hit the real tool code with zero network.
- **The LLM is an interface.** `GeminiLLM` for production, `ScriptedLLM` for tests. The agent
  never imports a vendor SDK, so swapping to Claude or an open model is one class.
- **Structured output is enforced, not requested.** `LeadQualification` is passed to Gemini as
  `response_schema`, so the model cannot return a malformed record.
- **Business rules live in code, not in the prompt.** The LLM extracts facts and flags a
  disqualifying intent; `finalize()` in `app/agent.py` derives `status` and `missing_fields`
  deterministically. The first eval run showed the model marking a below-minimum-order lead as
  `in_progress` even with every field known; moving the rule into code fixed it permanently.
- **Transient API errors are retried.** `GeminiLLM._generate` backs off on 429 (free tier is
  15 requests/min/model) and 503 (model overloaded), honouring the server's retry hint.
- **Loops are bounded.** A model that keeps calling tools is cut off after `max_tool_rounds` and
  the lead is handed to a human, instead of hanging the request.
- **Storage is a repository.** `LeadStore` is in-memory here; the interface is what a Postgres
  repository would expose.

## Next steps

- WhatsApp Business Cloud API webhook -> `POST /leads/{id}/messages`
- Postgres-backed `LeadStore` (SQLModel) and per-lead conversation memory summarisation
- LLM-as-judge grader for tone, alongside the deterministic checks
