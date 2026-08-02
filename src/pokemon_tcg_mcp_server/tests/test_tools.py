"""Tool behaviour end to end, over an in-memory MCP connection.

These go through the real server: tool registration, argument coercion into
the pydantic filter models, and result serialization all run. Only the Mongo
connection is faked (see the mcp_client fixture).
"""

import json
import re
from datetime import UTC, datetime

import pytest
from bson import ObjectId
from fastmcp.exceptions import ToolError

from pokemon_tcg_mcp_server.tools.get_card_by_id import (
    IMAGE_HOST,
    get_card_by_id,
    image_url_pattern,
)
from pokemon_tcg_mcp_server.tools.search_cards import HP_AS_INT

from .conftest import CHARIZARD


def payload(result):
    """The tool's JSON string, decoded."""

    return json.loads(result.content[0].text)


@pytest.mark.asyncio
class TestRegistration:
    async def test_every_tool_is_registered(self, mcp_client):
        names = {tool.name for tool in await mcp_client.list_tools()}

        assert names == {
            "search_cards",
            "get_card_by_id",
            "list_all_block_formats",
            "validate_deck",
        }

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
        cards = payload(await mcp_client.call_tool("search_cards", {"filters": {}}))[
            "cards"
        ]

        assert [card["id"] for card in cards] == ["baseset-4", "baseset-91"]
        assert cards[0]["name"] == "Charizard"
        assert cards[0]["hp_numeric"] == 120

    async def test_trainer_rules_survive_the_search(self, mcp_client):
        # The whole point: a Trainer's effect has to come back from the search
        # itself, or the caller has to fetch every Trainer one at a time.
        cards = payload(await mcp_client.call_tool("search_cards", {"filters": {}}))[
            "cards"
        ]
        bill = next(card for card in cards if card["id"] == "baseset-91")

        assert bill["rules"] == ["Draw 2 cards."]
        assert bill["legalities"] == {"unlimited": "Legal"}

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

        assert block_formats.queries == [
            {"$or": [{"_id": "base-fossil"}, {"name": "base-fossil"}]}
        ]
        assert cards.last_query == {"_id": {"$regex": "^(baseset|jungle|fossil)-"}}

    async def test_unknown_block_format_is_reported_to_the_caller(self, mcp_client):
        with pytest.raises(ToolError, match="Unknown block format"):
            await mcp_client.call_tool(
                "search_cards", {"filters": {"block_format": "nope"}}
            )

    async def test_no_matches_returns_an_empty_list(self, mcp_client, cards):
        cards.docs = []

        results = payload(await mcp_client.call_tool("search_cards", {"filters": {}}))

        assert results["cards"] == []
        assert results["total_count"] == 0
        assert results["returned"] == 0

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
        await get_card_by_id(ctx, "baseset-4")

        assert cards.last_query == {"_id": "baseset-4"}

    async def test_returns_the_raw_document(self, mcp_client):
        # No Card validation here by design; the stored document is returned
        # as-is, camelCase keys and unmapped fields and all.
        result = await mcp_client.call_tool("get_card_by_id", {"card_id": "baseset-4"})

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
                "_id": "baseset-4",
                "name": "Charizard",
                "set_ref": ObjectId("64b7f0c2e4b0a1a2b3c4d5e6"),
                "updated": datetime(2024, 5, 1, 12, 30, tzinfo=UTC),
            }
        ]

        result = await mcp_client.call_tool("get_card_by_id", {"card_id": "baseset-4"})

        assert payload(result) == {
            "_id": "baseset-4",
            "name": "Charizard",
            "set_ref": "64b7f0c2e4b0a1a2b3c4d5e6",
            "updated": "2024-05-01 12:30:00+00:00",
        }


@pytest.mark.asyncio
class TestPagination:
    async def test_envelope_shape(self, mcp_client):
        results = payload(await mcp_client.call_tool("search_cards", {"filters": {}}))

        assert list(results) == [
            "total_count",
            "limit",
            "offset",
            "returned",
            "cards",
        ]

    async def test_total_count_is_the_whole_result_not_the_page(self, mcp_client):
        results = payload(
            await mcp_client.call_tool("search_cards", {"filters": {}, "limit": 1})
        )

        assert results["total_count"] == 2
        assert results["returned"] == 1
        assert len(results["cards"]) == 1

    async def test_defaults(self, mcp_client, cards):
        await mcp_client.call_tool("search_cards", {"filters": {}})

        assert cards.last_cursor.applied["limit"] == 25
        assert cards.last_cursor.applied["skip"] == 0

    async def test_results_are_sorted_before_being_paged(self, mcp_client, cards):
        # An unsorted find has no ordering guarantee, so paging over it would
        # repeat some cards and skip others.
        await mcp_client.call_tool(
            "search_cards", {"filters": {}, "limit": 1, "offset": 1}
        )

        assert cards.last_cursor.applied == {
            "sort": ("_id", 1),
            "skip": 1,
            "limit": 1,
        }

    async def test_pages_partition_the_results(self, mcp_client):
        async def page(offset):
            results = payload(
                await mcp_client.call_tool(
                    "search_cards", {"filters": {}, "limit": 1, "offset": offset}
                )
            )
            return [card["id"] for card in results["cards"]]

        assert await page(0) == ["baseset-4"]
        assert await page(1) == ["baseset-91"]
        assert await page(2) == []

    async def test_count_and_find_are_given_the_same_predicate(self, mcp_client, cards):
        # Filtering one but not the other is the classic paging bug: the page
        # is right and total_count describes a different result set.
        await mcp_client.call_tool(
            "search_cards", {"filters": {"supertype": "Trainer"}}
        )

        assert cards.count_queries[-1] == cards.last_query

    @pytest.mark.parametrize(
        "arguments",
        [
            {"filters": {}, "limit": 0},
            {"filters": {}, "limit": 101},
            {"filters": {}, "offset": -1},
        ],
    )
    async def test_out_of_range_paging_is_rejected(self, mcp_client, arguments):
        with pytest.raises(ToolError):
            await mcp_client.call_tool("search_cards", arguments)

    async def test_limit_inside_filters_is_ignored(self, mcp_client, cards):
        # CardFilters ignores extras, so a limit put in the wrong place is
        # silently dropped and the default applies. Pinned, and called out in
        # the tool's docstring, because it is invisible from the response.
        await mcp_client.call_tool("search_cards", {"filters": {"limit": 1}})

        assert cards.last_cursor.applied["limit"] == 25


class TestImageUrlPattern:
    """Resolving an id guessed from a card's image URL."""

    @pytest.mark.parametrize(
        ("card_id", "expected"),
        [
            ("base1-91", "^" + re.escape(f"{IMAGE_HOST}/base1/91.png") + "$"),
            # Set names may contain hyphens; card numbers do not, so the split
            # has to be on the last one.
            (
                "sm-black-star-promos-12",
                "^" + re.escape(f"{IMAGE_HOST}/sm-black-star-promos/12.png") + "$",
            ),
            ("charizard", None),  # nothing to split on
            ("-4", None),  # no prefix
            ("base1-", None),  # no number
        ],
    )
    def test_pattern(self, card_id, expected):
        assert image_url_pattern(card_id) == expected

    def test_pattern_is_anchored_against_longer_numbers(self):
        pattern = image_url_pattern("base1-9")

        assert re.search(pattern, "https://images.pokemontcg.io/base1/9.png")
        assert not re.search(pattern, "https://images.pokemontcg.io/base1/91.png")

    def test_pattern_is_a_literal_prefix_match(self):
        # The '^' is what lets an index on images.small serve this. Without it
        # the did-you-mean fallback is a collection scan, on exactly the miss
        # path a caller guessing ids hits repeatedly.
        pattern = image_url_pattern("base1-91")

        assert pattern.startswith("^" + re.escape("https://"))
        assert not re.search(pattern, "https://example.test/base1/91.png")


@pytest.mark.asyncio
class TestGetCardByIdNamespace:
    async def test_an_image_namespace_id_names_the_real_one(self, mcp_client):
        # The mistake this exists for: the server only ever shows you the
        # image URL, whose set code is not the one in the id.
        with pytest.raises(
            ToolError, match="unknown id 'base1-91'; did you mean 'baseset-91'"
        ):
            await mcp_client.call_tool("get_card_by_id", {"card_id": "base1-91"})

    async def test_a_genuinely_absent_id_gets_the_plain_message(self, mcp_client):
        with pytest.raises(ToolError, match="No card with id 'baseset-999'"):
            await mcp_client.call_tool("get_card_by_id", {"card_id": "baseset-999"})

    async def test_both_messages_name_the_id_scheme(self, mcp_client):
        for card_id in ("base1-91", "baseset-999"):
            with pytest.raises(ToolError, match="baseset-4"):
                await mcp_client.call_tool("get_card_by_id", {"card_id": card_id})

    async def test_the_fallback_is_only_tried_on_a_miss(self, mcp_client, cards):
        await mcp_client.call_tool("get_card_by_id", {"card_id": "baseset-4"})

        assert cards.queries == [{"_id": "baseset-4"}]


# A legal base-fossil deck, used as the baseline the failure cases deviate
# from: 4 Charizard, 4 Bill, 4 Moltres, 4 Double Colorless, 44 Fire Energy.
LEGAL_DECK = [
    {"card_id": "baseset-4", "count": 4},
    {"card_id": "baseset-91", "count": 4},
    {"card_id": "fossil-12", "count": 4},
    {"card_id": "baseset-96", "count": 4},
    {"card_id": "baseset-98", "count": 44},
]


def deck(entries, block_format="base-fossil"):
    return {"deck": {"cards": entries, "block_format": block_format}}


@pytest.mark.asyncio
class TestValidateDeck:
    async def test_a_legal_deck_passes_cleanly(self, mcp_client, deck_cards):
        result = payload(await mcp_client.call_tool("validate_deck", deck(LEGAL_DECK)))

        assert result == {
            "valid": True,
            "errors": [],
            "warnings": [],
            "total_cards": 60,
        }

    @pytest.mark.parametrize(("energy", "total"), [(43, 59), (45, 61)])
    async def test_the_deck_must_hold_exactly_sixty(
        self, mcp_client, deck_cards, energy, total
    ):
        entries = LEGAL_DECK[:-1] + [{"card_id": "baseset-98", "count": energy}]

        result = payload(await mcp_client.call_tool("validate_deck", deck(entries)))

        assert result["valid"] is False
        assert result["total_cards"] == total
        assert f"deck has {total} cards" in result["errors"][0]

    async def test_five_copies_of_one_card(self, mcp_client, deck_cards):
        entries = [
            {"card_id": "baseset-4", "count": 5},
            {"card_id": "fossil-12", "count": 4},
            {"card_id": "baseset-98", "count": 51},
        ]

        result = payload(await mcp_client.call_tool("validate_deck", deck(entries)))

        assert result["valid"] is False
        assert "5 copies of 'Charizard'" in result["errors"][0]

    async def test_the_limit_counts_names_not_ids(self, mcp_client, deck_cards):
        # Moltres is printed twice in Fossil, so four of each is eight Moltres.
        entries = [
            {"card_id": "fossil-12", "count": 4},
            {"card_id": "fossil-27", "count": 4},
            {"card_id": "baseset-98", "count": 52},
        ]

        result = payload(await mcp_client.call_tool("validate_deck", deck(entries)))

        assert result["valid"] is False
        assert result["errors"] == [
            "8 copies of 'Moltres'; at most 4 are allowed (basic Energy is exempt)"
        ]

    async def test_basic_energy_is_exempt_from_the_limit(self, mcp_client, deck_cards):
        # 44 Fire Energy is legal; the limit does not apply to basic Energy.
        result = payload(await mcp_client.call_tool("validate_deck", deck(LEGAL_DECK)))

        assert result["valid"] is True

    async def test_special_energy_is_not_exempt(self, mcp_client, deck_cards):
        # Double Colorless is supertype Energy but subtypes ['Special'].
        entries = [
            {"card_id": "baseset-96", "count": 5},
            {"card_id": "fossil-12", "count": 4},
            {"card_id": "baseset-98", "count": 51},
        ]

        result = payload(await mcp_client.call_tool("validate_deck", deck(entries)))

        assert result["valid"] is False
        assert "5 copies of 'Double Colorless Energy'" in result["errors"][0]

    async def test_unknown_card_id(self, mcp_client, deck_cards):
        entries = [
            {"card_id": "baseset-9999", "count": 4},
            {"card_id": "fossil-12", "count": 4},
            {"card_id": "baseset-98", "count": 52},
        ]

        result = payload(await mcp_client.call_tool("validate_deck", deck(entries)))

        assert result["valid"] is False
        assert "unknown card id 'baseset-9999'" in result["errors"][0]

    async def test_out_of_format_card(self, mcp_client, deck_cards):
        entries = [
            {"card_id": "neogenesis-1", "count": 4},
            {"card_id": "fossil-12", "count": 4},
            {"card_id": "baseset-98", "count": 52},
        ]

        result = payload(await mcp_client.call_tool("validate_deck", deck(entries)))

        assert result["valid"] is False
        assert result["errors"] == [
            "'neogenesis-1' (Feraligatr) is not legal in 'base-fossil'"
        ]

    async def test_a_promo_card_warns_rather_than_failing(self, mcp_client, deck_cards):
        # Only part of the promo set is legal and the set-prefix logic cannot
        # read that range, so rejecting the card would be a confident lie.
        entries = [
            {"card_id": "wizardsblackstarpromos-4", "count": 4},
            {"card_id": "fossil-12", "count": 4},
            {"card_id": "baseset-98", "count": 52},
        ]

        result = payload(await mcp_client.call_tool("validate_deck", deck(entries)))

        assert result["valid"] is True
        assert "cards 1-9 are legal" in result["warnings"][0]

    async def test_duplicate_entries_are_summed_with_a_warning(
        self, mcp_client, deck_cards
    ):
        entries = [
            {"card_id": "baseset-4", "count": 2},
            {"card_id": "baseset-4", "count": 2},
            {"card_id": "fossil-12", "count": 4},
            {"card_id": "baseset-98", "count": 52},
        ]

        result = payload(await mcp_client.call_tool("validate_deck", deck(entries)))

        assert result["total_cards"] == 60
        assert result["valid"] is True
        assert "listed more than once" in result["warnings"][0]

    async def test_summed_duplicates_can_break_the_copy_limit(
        self, mcp_client, deck_cards
    ):
        # Splitting a card across two entries must not sneak past the limit.
        entries = [
            {"card_id": "baseset-4", "count": 3},
            {"card_id": "baseset-4", "count": 3},
            {"card_id": "fossil-12", "count": 4},
            {"card_id": "baseset-98", "count": 50},
        ]

        result = payload(await mcp_client.call_tool("validate_deck", deck(entries)))

        assert result["valid"] is False
        assert "6 copies of 'Charizard'" in result["errors"][0]

    async def test_a_deck_with_no_basic_pokemon_warns(self, mcp_client, deck_cards):
        entries = [
            {"card_id": "baseset-4", "count": 4},
            {"card_id": "baseset-91", "count": 4},
            {"card_id": "baseset-98", "count": 52},
        ]

        result = payload(await mcp_client.call_tool("validate_deck", deck(entries)))

        assert result["valid"] is True
        assert "no Basic Pokémon" in result["warnings"][0]

    async def test_warnings_alone_do_not_invalidate(self, mcp_client, deck_cards):
        entries = [
            {"card_id": "baseset-4", "count": 2},
            {"card_id": "baseset-4", "count": 2},
            {"card_id": "baseset-91", "count": 4},
            {"card_id": "baseset-98", "count": 52},
        ]

        result = payload(await mcp_client.call_tool("validate_deck", deck(entries)))

        assert result["valid"] is True
        assert len(result["warnings"]) == 2

    async def test_unknown_block_format_is_reported_to_the_caller(
        self, mcp_client, deck_cards
    ):
        with pytest.raises(ToolError, match="Unknown block format 'nope'"):
            await mcp_client.call_tool("validate_deck", deck(LEGAL_DECK, "nope"))

    async def test_every_card_is_fetched_in_one_query(self, mcp_client, deck_cards):
        await mcp_client.call_tool("validate_deck", deck(LEGAL_DECK))

        assert deck_cards.last_query == {
            "_id": {
                "$in": [
                    "baseset-4",
                    "baseset-91",
                    "fossil-12",
                    "baseset-96",
                    "baseset-98",
                ]
            }
        }

    async def test_a_missing_count_is_rejected(self, mcp_client, deck_cards):
        # Input models forbid extras and require count, so a decklist written
        # with the wrong key fails loudly instead of validating a different
        # deck than the one that was sent.
        with pytest.raises(ToolError):
            await mcp_client.call_tool(
                "validate_deck", deck([{"card_id": "baseset-4", "qty": 4}])
            )
