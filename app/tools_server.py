"""FastMCP tool server. Every tool the sales agent can use lives here, exposed
over the Model Context Protocol so any MCP client (our agent, Claude Desktop,
Cursor...) can call them. Run standalone with:  python -m app.tools_server
"""
from __future__ import annotations

from typing import Optional

from fastmcp import FastMCP

mcp = FastMCP("lead-tools")

# Tiny stand-ins for a CRM and a product catalogue. In production these become
# Postgres queries / HTTP calls; the tool signatures stay the same.
PRODUCT_CATALOG = {
    "corrugated boxes": {"min_order": 500, "unit_price_inr": 18, "lead_time_days": 7},
    "bubble wrap": {"min_order": 50, "unit_price_inr": 220, "lead_time_days": 3},
    "custom printed cartons": {"min_order": 1000, "unit_price_inr": 32, "lead_time_days": 14},
}
CRM = {
    "9876543210": {"name": "Rahul Mehta", "company": "Mehta Foods", "past_orders": 3},
}
CALLBACKS: list[dict] = []


@mcp.tool
def product_catalog(query: str) -> dict:
    """Look up a product by name. Returns minimum order quantity, unit price (INR)
    and lead time. Use before quoting anything to the lead."""
    q = query.lower()
    matches = {k: v for k, v in PRODUCT_CATALOG.items() if q in k or k in q}
    return matches or {"error": f"No product matching '{query}'. Available: {list(PRODUCT_CATALOG)}"}


@mcp.tool
def crm_lookup(phone: str) -> dict:
    """Fetch an existing customer's record by phone number. Returns {} if unknown."""
    return CRM.get(phone.strip(), {})


@mcp.tool
def score_lead(
    product_interest: Optional[str] = None,
    quantity: Optional[int] = None,
    budget_inr: Optional[int] = None,
    timeline: Optional[str] = None,
) -> dict:
    """Score a lead 0-100 from what is known so far. Call once product, quantity,
    budget and timeline are all known. Returns score, tier (hot/warm/cold) and reason."""
    score, reasons = 0, []
    product = PRODUCT_CATALOG.get((product_interest or "").lower())
    if product:
        score += 25
        reasons.append("known product")
        if quantity and quantity >= product["min_order"]:
            score += 25
            reasons.append("meets minimum order")
        if budget_inr and quantity and budget_inr >= quantity * product["unit_price_inr"] * 0.8:
            score += 30
            reasons.append("budget covers ~80%+ of list price")
    if timeline and any(w in timeline.lower() for w in ("week", "urgent", "asap", "immediately", "days")):
        score += 20
        reasons.append("short timeline")
    tier = "hot" if score >= 70 else "warm" if score >= 40 else "cold"
    return {"score": score, "tier": tier, "reason": ", ".join(reasons) or "insufficient info"}


@mcp.tool
def book_callback(name: str, phone: str, preferred_time: str) -> dict:
    """Book a callback from a human sales rep. Only call after the lead agrees to a call."""
    entry = {"name": name, "phone": phone, "preferred_time": preferred_time}
    CALLBACKS.append(entry)
    return {"booked": True, "id": len(CALLBACKS), **entry}


if __name__ == "__main__":
    mcp.run()  # stdio transport; add transport="http", port=8001 for HTTP
