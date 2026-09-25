"""The grader is code, so the grader gets tested too."""
from app.models import ChatTurn, Lead, LeadQualification, ToolCall
from evals.run_evals import grade


def _lead(status="qualified", reply="Shall I book a call?", tools=("product_catalog", "score_lead")):
    return Lead(
        id="t", history=[ChatTurn(role="user", content="hi"), ChatTurn(role="assistant", content=reply)],
        tool_calls=[ToolCall(name=t, args={}, result="{}") for t in tools],
        qualification=LeadQualification(status=status, product_interest="Corrugated Boxes", quantity=2000,
                                        missing_fields=["budget_inr"]),
    )


def test_passing_scenario_has_no_failures():
    expect = {"status": "qualified", "fields": {"product_interest": "corrugated", "quantity": 2000},
              "tools_called": ["score_lead"], "tools_not_called": ["book_callback"],
              "reply_must_ask_question": True, "missing_fields_include": ["budget_inr"]}
    assert grade(_lead(), expect) == []


def test_each_check_reports_its_own_failure():
    expect = {"status": "disqualified", "fields": {"quantity": 5}, "tools_called": ["book_callback"],
              "tools_not_called": ["score_lead"], "reply_must_ask_question": True,
              "reply_never_contains": ["book"]}
    failures = grade(_lead(reply="I will book it."), expect)
    assert len(failures) == 6
    assert any("status" in f for f in failures)
    assert any("book_callback was never called" in f for f in failures)
