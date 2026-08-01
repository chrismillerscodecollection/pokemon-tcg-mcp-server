"""Tool behaviour end to end, over an in-memory MCP connection.

These go through the real server: tool registration, argument coercion into
the pydantic filter models, and result serialization all run. Only the Mongo
connection is faked (see the mcp_client fixture).
"""

import json
from datetime import UTC, datetime

import pytest
from bson import ObjectId
from fastmcp.exceptions import ToolError

from pokemon_tcg_mcp_server.tools.get_card_by_id import get_card_by_id
from pokemon_tcg_mcp_server.tools.search_cards import HP_AS_INT

from .conftest import CHARIZARD


def payload(result):
    """The tool's JSON string, decoded."""

    return json.loads(result.content[0].text)


@pytest.mark.asyncio
class TestRegistration:
    async def test_every_tool_is_registered(self, mcp_client):
        names = {tool.name for tool in await mcp_client.list_tools()}

        assert names == {"search_cards", "get_card_by_id", "list_all_block_formats"}

    async def test_tools_are_documented(self, mcp_client):
        for tool in await mcp_client.list_tools():
            assert tool.description, f"{tool.name} has no description"


@pytest.mark.asyncio
class TestListAllBlockFormats:
    async def test_returns_every_format(self, mcp_client):
        results = payload(await mcp_client.call_tool("list_all_block_formats", {}))

        assert [item["id"] for item in results] == ["base-fossil", "team-rocket"]

    async def test_uses_field_names_not_mongo_aliases(self, mcp_client):
        results = payload(await mcp_client.call_tool("list_all_block_formats", {}))

        assert results[0]["blog_label_year"] == 1999
        assert results[0]["promo_sets"][0]["card_range"] == "1-9"
        assert "_id" not in results[0]

    async def test_unfiltered_query(self, mcp_client, block_formats):
        await mcp_client.call_tool("list_all_block_formats", {})

        assert block_formats.last_query == {}

    async def test_empty_collection(self, mcp_client, block_formats):
        block_formats.docs = []

        assert payload(await mcp_client.call_tool("list_all_block_formats", {})) == []


@pytest.mark.asyncio
class TestSearchCards:
    async def test_returns_validated_cards(self, mcp_client):
        results = payload(await mcp_client.call_tool("search_cards", {"filters": {}}))

        assert [card["id"] for card in results] == ["base1-4", "base1-91"]
        assert results[0]["name"] == "Charizard"
        assert results[0]["hp_numeric"] == 120

    async def test_no_filters_queries_everything(self, mcp_client, cards):
        await mcp_client.call_tool("search_cards", {"filters": {}})

        assert cards.last_query == {}

    async def test_filters_are_translated_into_the_query(self, mcp_client, cards):
        await mcp_client.call_tool(
            "search_cards",
            {"filters": {"hp": {"gte": 70}, "types": ["Fire"], "weakness": "Water"}},
        )

        assert cards.last_query == {
            "$expr": {"$and": [{"$gte": [HP_AS_INT, 70]}]},
            "hp": {"$exists": True},
            "types": {"$in": ["Fire"]},
            "weaknesses.type": "Water",
        }

    async def test_block_format_is_resolved_before_the_card_query(
        self, mcp_client, cards, block_formats
    ):
        await mcp_client.call_tool(
            "search_cards", {"filters": {"block_format": "base-fossil"}}
        )

        assert block_formats.queries == [{"_id": "base-fossil"}]
        assert cards.last_query == {"_id": {"$regex": "^(base1|basep|base2|base3)-"}}

    async def test_unknown_block_format_is_reported_to_the_caller(self, mcp_client):
        with pytest.raises(ToolError, match="Unknown block format"):
            await mcp_client.call_tool(
                "search_cards", {"filters": {"block_format": "nope"}}
            )

    async def test_no_matches_returns_an_empty_list(self, mcp_client, cards):
        cards.docs = []

        assert (
            payload(await mcp_client.call_tool("search_cards", {"filters": {}})) == []
        )

    async def test_result_is_a_json_string(self, mcp_client):
        result = await mcp_client.call_tool("search_cards", {"filters": {}})
        text = result.content[0].text

        assert isinstance(text, str)
        assert json.loads(text)  # parses, and is non-empty

    async def test_unknown_filter_field_is_ignored(self, mcp_client, cards):
        # CardFilters ignores extras rather than rejecting them, so a typo'd
        # filter silently widens the search. Pinned so a change is noticed.
        await mcp_client.call_tool("search_cards", {"filters": {"weaknesses": "Water"}})

        assert cards.last_query == {}


@pytest.mark.asyncio
class TestGetCardById:
    async def test_queries_by_exact_id(self, ctx, cards):
        await get_card_by_id(ctx, "base1-4")

        assert cards.last_query == {"_id": "base1-4"}

    async def test_returns_the_raw_document(self, mcp_client):
        # No Card validation here by design; the stored document is returned
        # as-is, camelCase keys and unmapped fields and all.
        result = await mcp_client.call_tool("get_card_by_id", {"card_id": "base1-4"})

        assert payload(result) == CHARIZARD

    async def test_missing_card_is_reported_to_the_caller(self, mcp_client):
        with pytest.raises(ToolError, match="No card with id 'no-such-card'"):
            await mcp_client.call_tool("get_card_by_id", {"card_id": "no-such-card"})

    async def test_missing_card_points_at_the_search_tool(self, mcp_client):
        with pytest.raises(ToolError, match="search_cards"):
            await mcp_client.call_tool("get_card_by_id", {"card_id": "no-such-card"})

    async def test_bson_values_are_serialized(self, mcp_client, cards):
        # Nothing validates this document, so a BSON type that json cannot
        # encode would otherwise take the tool down with a TypeError.
        cards.docs = [
            {
                "_id": "base1-4",
                "name": "Charizard",
                "set_ref": ObjectId("64b7f0c2e4b0a1a2b3c4d5e6"),
                "updated": datetime(2024, 5, 1, 12, 30, tzinfo=UTC),
            }
        ]

        result = await mcp_client.call_tool("get_card_by_id", {"card_id": "base1-4"})

        assert payload(result) == {
            "_id": "base1-4",
            "name": "Charizard",
            "set_ref": "64b7f0c2e4b0a1a2b3c4d5e6",
            "updated": "2024-05-01 12:30:00+00:00",
        }
