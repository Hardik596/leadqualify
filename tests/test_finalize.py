"""Business rules for status live in code, not in the prompt, so they get plain unit tests."""
from app.agent import finalize
from app.models import LeadQualification


def test_all_required_fields_means_qualified_even_below_moq():
    q = LeadQualification(product_interest="corrugated boxes", quantity=100, budget_inr=1500,
                          timeline="next month", status="in_progress", missing_fields=["name"])
    out = finalize(q)
    assert out.status == "qualified" and out.missing_fields == []


def test_partial_fields_are_in_progress_with_exact_missing_list():
    out = finalize(LeadQualification(product_interest="bubble wrap", status="new"))
    assert out.status == "in_progress"
    assert out.missing_fields == ["quantity", "budget_inr", "timeline"]


def test_disqualified_is_preserved():
    out = finalize(LeadQualification(status="disqualified", missing_fields=["product_interest"]))
    assert out.status == "disqualified" and out.missing_fields == []
