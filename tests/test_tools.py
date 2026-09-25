"""MCP tool server tests: talk to the tools through a real MCP client, not by
importing the functions, so the schema exposure is tested too."""
import pytest
from fastmcp import Client

from app.tools_server import mcp


@pytest.mark.asyncio
async def test_tools_are_exposed_with_schemas():
    async with Client(mcp) as c:
        tools = {t.name: t for t in await c.list_tools()}
    assert set(tools) == {"product_catalog", "crm_lookup", "score_lead", "book_callback"}
    assert tools["book_callback"].input_schema["required"] == ["name", "phone", "preferred_time"]


@pytest.mark.asyncio
async def test_product_catalog_fuzzy_match_and_miss():
    async with Client(mcp) as c:
        hit = (await c.call_tool("product_catalog", {"query": "Corrugated"})).data
        miss = (await c.call_tool("product_catalog", {"query": "water bottles"})).data
    assert "corrugated boxes" in hit
    assert "error" in miss


@pytest.mark.asyncio
async def test_score_lead_tiers():
    async with Client(mcp) as c:
        hot = (await c.call_tool("score_lead", {
            "product_interest": "corrugated boxes", "quantity": 2000, "budget_inr": 40000, "timeline": "2 weeks",
        })).data
        cold = (await c.call_tool("score_lead", {"product_interest": "unknown thing"})).data
    assert hot["tier"] == "hot" and hot["score"] == 100
    assert cold["tier"] == "cold"


@pytest.mark.asyncio
async def test_book_callback_records_entry():
    async with Client(mcp) as c:
        r = (await c.call_tool("book_callback", {"name": "A", "phone": "1", "preferred_time": "11am"})).data
    assert r["booked"] is True and r["id"] >= 1
