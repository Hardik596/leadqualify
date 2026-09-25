"""Multi-turn evaluation harness.

Plays every scenario in scenarios.yaml against the real agent (Gemini), grades
the final lead state with deterministic checks, prints a report and exits 1 if
the pass rate is below --min-pass. Run:  python -m evals.run_evals
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml

from app.agent import SalesAgent
from app.models import Lead

SCENARIOS = Path(__file__).with_name("scenarios.yaml")
RESULTS = Path(__file__).with_name("results.json")


def grade(lead: Lead, expect: dict) -> list[str]:
    """Return a list of failure messages (empty list == pass). Pure function: easy to unit test."""
    failures: list[str] = []
    q = lead.qualification
    called = {t.name for t in lead.tool_calls}
    last_reply = lead.history[-1].content if lead.history else ""

    if "status" in expect and q.status != expect["status"]:
        failures.append(f"status: expected {expect['status']}, got {q.status}")
    for field, want in expect.get("fields", {}).items():
        got = getattr(q, field, None)
        if isinstance(want, str) and isinstance(got, str):
            if want.lower() not in got.lower():
                failures.append(f"{field}: expected ~'{want}', got '{got}'")
        elif got != want:
            failures.append(f"{field}: expected {want!r}, got {got!r}")
    for tool in expect.get("tools_called", []):
        if tool not in called:
            failures.append(f"tool {tool} was never called")
    for tool in expect.get("tools_not_called", []):
        if tool in called:
            failures.append(f"tool {tool} should not have been called")
    if expect.get("reply_must_ask_question") and "?" not in last_reply:
        failures.append("last reply did not ask a question")
    if (opts := expect.get("reply_contains_any")) and not any(o.lower() in last_reply.lower() for o in opts):
        failures.append(f"last reply contains none of {opts}")
    for bad in expect.get("reply_never_contains", []):
        if any(bad.lower() in t.content.lower() for t in lead.history if t.role == "assistant"):
            failures.append(f"an assistant reply contained forbidden text '{bad}'")
    for f in expect.get("missing_fields_include", []):
        if f not in q.missing_fields:
            failures.append(f"missing_fields should include {f}, got {q.missing_fields}")
    return failures


async def run_scenario(agent: SalesAgent, scenario: dict) -> dict:
    lead = Lead(id=scenario["name"][:8], source=scenario.get("source", "web"))
    for turn in scenario["turns"]:
        await agent.respond(lead, turn)
    failures = grade(lead, scenario.get("expect", {}))
    return {
        "name": scenario["name"],
        "passed": not failures,
        "failures": failures,
        "transcript": [t.model_dump() for t in lead.history],
        "tool_calls": [t.name for t in lead.tool_calls],
        "qualification": lead.qualification.model_dump(),
    }


async def main(agent: SalesAgent, only: str | None, min_pass: float) -> int:
    scenarios = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))
    if only:
        scenarios = [s for s in scenarios if s["name"] == only]
    results = [await run_scenario(agent, s) for s in scenarios]

    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}")
        for f in r["failures"]:
            print(f"        - {f}")
    rate = sum(r["passed"] for r in results) / max(len(results), 1)
    print(f"\n{sum(r['passed'] for r in results)}/{len(results)} passed ({rate:.0%})")
    RESULTS.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"Full transcripts written to {RESULTS}")
    return 0 if rate >= min_pass else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="run a single scenario by name")
    parser.add_argument("--min-pass", type=float, default=1.0, help="required pass rate, 0-1")
    args = parser.parse_args()

    from app.llm import GeminiLLM  # real model: needs GEMINI_API_KEY

    sys.exit(asyncio.run(main(SalesAgent(GeminiLLM()), args.only, args.min_pass)))
