"""The queries search_cards builds, executed by a real MongoDB.

The rest of the suite asserts the *shape* of each query document. That cannot
tell you whether MongoDB agrees: whether $convert reads a string hp as a
number, whether a top-level $expr composes with the $exists guard, whether the
set-prefix regex anchors where it should. These run the queries and assert
which documents come back.

Opt-in — they need DB_URI and a reachable deployment:

    uv run pytest -m integration

Everything here is seeded into, and dropped from, a database named for testing.
The fixture refuses to run against the application's own database.

The seed mirrors the real collection: set ids are 'baseset'/'jungle'/'fossil',
hp is a plain numeric string, and non-Pokémon cards omit hp entirely.
"""

import os

import pytest
import pytest_asyncio

from pokemon_tcg_mcp_server.models import Card, CardFilters, HPFilter
from pokemon_tcg_mcp_server.tools.search_cards import build_query

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

APP_DB_NAME = "pokemon_tcg"
TEST_DB_NAME = os.getenv("TEST_DB_NAME", "pokemon_tcg_integration_test")

SEED_CARDS = [
    {
        "_id": "baseset-4",
        "name": "Charizard",
        "supertype": "Pokémon",
        "hp": "120",
        "types": ["Fire"],
        "attacks": [{"name": "Fire Spin", "cost": ["Fire"] * 4, "damage": "100"}],
        "weaknesses": [{"type": "Water", "value": "×2"}],
        "resistances": [{"type": "Fighting", "value": "-30"}],
        "rarity": "Rare Holo",
    },
    {
        "_id": "baseset-58",
        "name": "Pidgey",
        "supertype": "Pokémon",
        "hp": "40",
        "types": ["Colorless"],
        "attacks": [{"name": "Whirlwind", "cost": ["Colorless"], "damage": "10"}],
        "weaknesses": [{"type": "Lightning", "value": "×2"}],
        "rarity": "Common",
    },
    {
        "_id": "fossil-3",
        "name": "Articuno",
        "supertype": "Pokémon",
        "hp": "70",
        "types": ["Water"],
        "attacks": [{"name": "Freeze Dry", "cost": ["Water"] * 3, "damage": "30"}],
        "weaknesses": [{"type": "Lightning", "value": "×2"}],
        "rarity": "Rare Holo",
    },
    {
        "_id": "baseset-91",
        "name": "Bill",
        "supertype": "Trainer",  # no hp key, like every real Trainer
        "rarity": "Common",
    },
    {
        # Outside the seeded format, and its set id *contains* 'fossil' without
        # starting with it — so it also pins the regex anchor.
        "_id": "neofossil-1",
        "name": "Cleffa",
        "supertype": "Pokémon",
        "hp": "50",
        "types": ["Colorless"],
        "weaknesses": [{"type": "Fighting", "value": "×2"}],
        "rarity": "Common",
    },
]

# hp the $convert cannot parse. No card in the real collection looks like this
# today, but the code carries an explicit onError branch for it, so the
# behaviour is pinned rather than assumed. Kept in its own collection so it
# does not perturb the counts above.
SEED_ODD_HP = [
    {"_id": "x-1", "name": "Suffixed", "hp": "100+", "supertype": "Pokémon"},
    {"_id": "x-2", "name": "Blank", "hp": "", "supertype": "Pokémon"},
]

# The attack_cost filter binds every requested symbol to one attack. Proving
# that needs a card whose symbols are split across two attacks, which would
# perturb the counts above, so it gets its own collection too.
SEED_ATTACK_COSTS = [
    {
        # Fire on one attack, Colorless on another. The filter must not match
        # it for ['Fire', 'Colorless'] — the old $in rule did.
        "_id": "baseset-12",
        "name": "Ninetales",
        "supertype": "Pokémon",
        "attacks": [
            {"name": "Lure", "cost": ["Colorless", "Colorless"]},
            {"name": "Fire Blast", "cost": ["Fire"] * 4},
        ],
    },
    {
        # Both symbols on one attack, which is what the filter means.
        "_id": "baseset-23",
        "name": "Arcanine",
        "supertype": "Pokémon",
        "attacks": [{"name": "Flamethrower", "cost": ["Fire", "Fire", "Colorless"]}],
    },
]

SEED_BLOCK_FORMATS = [
    {
        "_id": "base-fossil",
        "name": "Base-Fossil",
        "category": "block",
        "blogLabelYear": 1999,
        "sets": ["baseset", "jungle", "fossil"],
        "promoSets": [{"name": "wizardsblackstarpromos", "cardRange": "1-9"}],
    }
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def live_db():
    """A seeded scratch database, dropped on the way out."""

    assert TEST_DB_NAME != APP_DB_NAME, (
        f"refusing to seed the application database {APP_DB_NAME!r}; "
        "set TEST_DB_NAME to something else"
    )

    from pokemon_tcg_mcp_server.mongodb_client import create_mongodb_client

    client = await create_mongodb_client()
    try:
        await client.drop_database(TEST_DB_NAME)
        db = client[TEST_DB_NAME]
        await db["cards"].insert_many(SEED_CARDS)
        await db["cards_odd_hp"].insert_many(SEED_ODD_HP)
        await db["cards_attack_cost"].insert_many(SEED_ATTACK_COSTS)
        await db["block_formats"].insert_many(SEED_BLOCK_FORMATS)
        yield db
    finally:
        await client.drop_database(TEST_DB_NAME)
        client.close()


async def matching_ids(db, filters: CardFilters, collection: str = "cards") -> set[str]:
    """Run the real query and return the ids it selects."""

    query = await build_query(db, filters)
    docs = await db[collection].find(query).to_list(length=None)
    return {doc["_id"] for doc in docs}


class TestHPQueries:
    async def test_gte_compares_numerically_not_lexically(self, live_db):
        # As strings '40' sorts above '120'; only $convert gets this right.
        assert await matching_ids(live_db, CardFilters(hp=HPFilter(gte=100))) == {
            "baseset-4"
        }

    async def test_lte_excludes_cards_without_hp(self, live_db):
        # The bug the $exists guard prevents: without it Bill converts to 0
        # and satisfies every upper bound.
        assert await matching_ids(live_db, CardFilters(hp=HPFilter(lte=50))) == {
            "baseset-58",
            "neofossil-1",
        }

    async def test_gte_zero_still_excludes_cards_without_hp(self, live_db):
        assert "baseset-91" not in await matching_ids(
            live_db, CardFilters(hp=HPFilter(gte=0))
        )

    async def test_range_selects_between_the_bounds(self, live_db):
        assert await matching_ids(
            live_db, CardFilters(hp=HPFilter(gte=60, lte=110))
        ) == {"fossil-3"}

    async def test_bounds_are_inclusive(self, live_db):
        assert await matching_ids(
            live_db, CardFilters(hp=HPFilter(gte=70, lte=70))
        ) == {"fossil-3"}

    async def test_eq_matches_the_raw_string(self, live_db):
        assert await matching_ids(live_db, CardFilters(hp=HPFilter(eq="120"))) == {
            "baseset-4"
        }

    async def test_eq_does_not_coerce(self, live_db):
        # '120' is stored; the numerically equal '0120' must not match.
        assert await matching_ids(live_db, CardFilters(hp=HPFilter(eq="0120"))) == set()


class TestUnparseableHP:
    """What $convert's onError fallback does to hp it cannot read."""

    async def test_unparseable_hp_is_treated_as_zero(self, live_db):
        # onError keeps the query running instead of aborting it, but the
        # card lands at 0 rather than at the number its digits suggest.
        assert await matching_ids(
            live_db, CardFilters(hp=HPFilter(lte=10)), collection="cards_odd_hp"
        ) == {"x-1", "x-2"}

    async def test_unparseable_hp_is_missed_by_lower_bounds(self, live_db):
        assert (
            await matching_ids(
                live_db, CardFilters(hp=HPFilter(gte=90)), collection="cards_odd_hp"
            )
            == set()
        )

    async def test_query_and_model_disagree_about_suffixed_hp(self, live_db):
        # Worth knowing: the query scores '100+' as 0 while the Card model
        # strips the suffix and scores it as 100. A card the hp search excluded
        # would therefore report hp_numeric 100 if it turned up another way.
        excluded = await matching_ids(
            live_db, CardFilters(hp=HPFilter(gte=90)), collection="cards_odd_hp"
        )

        assert "x-1" not in excluded
        assert Card.model_validate(SEED_ODD_HP[0]).hp_numeric == 100


class TestBlockFormatQueries:
    async def test_regex_selects_only_the_formats_sets(self, live_db):
        assert await matching_ids(live_db, CardFilters(block_format="base-fossil")) == {
            "baseset-4",
            "baseset-58",
            "fossil-3",
            "baseset-91",
        }

    async def test_regex_is_anchored_at_the_start(self, live_db):
        # 'neofossil' contains 'fossil' but the format does not include it.
        assert "neofossil-1" not in await matching_ids(
            live_db, CardFilters(block_format="base-fossil")
        )

    async def test_lookup_by_name_selects_the_same_cards(self, live_db):
        by_id = await matching_ids(live_db, CardFilters(block_format="base-fossil"))
        by_name = await matching_ids(live_db, CardFilters(block_format="Base-Fossil"))

        assert by_id == by_name


class TestAttributeQueries:
    async def test_types_matches_any_of_them(self, live_db):
        assert await matching_ids(live_db, CardFilters(types=["Fire", "Water"])) == {
            "baseset-4",
            "fossil-3",
        }

    async def test_weakness_matches_inside_the_subdocument_array(self, live_db):
        assert await matching_ids(live_db, CardFilters(weakness="Lightning")) == {
            "baseset-58",
            "fossil-3",
        }

    async def test_attack_cost_matches_inside_the_nested_array(self, live_db):
        assert await matching_ids(live_db, CardFilters(attack_cost=["Water"])) == {
            "fossil-3"
        }

    async def test_supertype_is_exact(self, live_db):
        assert await matching_ids(live_db, CardFilters(supertype="Trainer")) == {
            "baseset-91"
        }

    async def test_supertype_matches_the_accented_string(self, live_db):
        # Every document spells it with a precomposed U+00E9.
        assert "baseset-91" not in await matching_ids(
            live_db, CardFilters(supertype="Pokémon")
        )

    async def test_name_is_a_case_insensitive_substring(self, live_db):
        assert await matching_ids(live_db, CardFilters(name="char")) == {"baseset-4"}
        assert await matching_ids(live_db, CardFilters(name="CHARIZ")) == {"baseset-4"}

    async def test_name_matches_a_substring_anywhere(self, live_db):
        assert await matching_ids(live_db, CardFilters(name="uno")) == {"fossil-3"}

    async def test_resistance_matches_inside_the_subdocument_array(self, live_db):
        assert await matching_ids(live_db, CardFilters(resistance="Fighting")) == {
            "baseset-4"
        }

    async def test_rarity(self, live_db):
        assert await matching_ids(live_db, CardFilters(rarity="Rare Holo")) == {
            "baseset-4",
            "fossil-3",
        }

    async def test_no_filters_selects_everything(self, live_db):
        assert len(await matching_ids(live_db, CardFilters())) == len(SEED_CARDS)


class TestCombinedQueries:
    async def test_every_filter_must_match(self, live_db):
        assert await matching_ids(
            live_db,
            CardFilters(
                hp=HPFilter(gte=70),
                types=["Water"],
                weakness="Lightning",
                rarity="Rare Holo",
                block_format="base-fossil",
            ),
        ) == {"fossil-3"}

    async def test_contradictory_filters_select_nothing(self, live_db):
        assert (
            await matching_ids(
                live_db, CardFilters(types=["Fire"], weakness="Lightning")
            )
            == set()
        )

    async def test_hp_bound_composes_with_the_block_format_regex(self, live_db):
        # $expr, the $exists guard and an _id regex in one query document.
        assert await matching_ids(
            live_db,
            CardFilters(hp=HPFilter(lte=100), block_format="base-fossil"),
        ) == {"baseset-58", "fossil-3"}


class TestAttackCostSemantics:
    """Every requested symbol has to sit on ONE attack, not be spread around."""

    async def test_symbols_split_across_two_attacks_do_not_match(self, live_db):
        # Ninetales pays Colorless on Lure and Fire on Fire Blast. Reading that
        # as a match for ['Fire', 'Colorless'] is the bug $elemMatch fixes.
        assert await matching_ids(
            live_db,
            CardFilters(attack_cost=["Fire", "Colorless"]),
            collection="cards_attack_cost",
        ) == {"baseset-23"}

    async def test_a_single_symbol_still_matches_either_card(self, live_db):
        assert await matching_ids(
            live_db,
            CardFilters(attack_cost=["Fire"]),
            collection="cards_attack_cost",
        ) == {"baseset-12", "baseset-23"}

    async def test_matching_is_set_containment_not_multiset(self, live_db):
        # $all does not count duplicates, so asking for two Fire is the same
        # as asking for one. Documented rather than fixed.
        one = await matching_ids(
            live_db, CardFilters(attack_cost=["Fire"]), collection="cards_attack_cost"
        )
        two = await matching_ids(
            live_db,
            CardFilters(attack_cost=["Fire", "Fire"]),
            collection="cards_attack_cost",
        )

        assert one == two

    async def test_the_cost_may_carry_extra_symbols(self, live_db):
        # Containment, not equality: Flamethrower costs Fire Fire Colorless.
        assert await matching_ids(
            live_db,
            CardFilters(attack_cost=["Colorless"]),
            collection="cards_attack_cost",
        ) == {"baseset-12", "baseset-23"}


class TestPaging:
    """Paging is only coherent because the query sorts first."""

    async def test_pages_partition_the_result_set(self, live_db):
        query = await build_query(live_db, CardFilters())
        total = await live_db["cards"].count_documents(query)

        async def page(offset, limit=2):
            docs = (
                await live_db["cards"]
                .find(query)
                .sort("_id", 1)
                .skip(offset)
                .limit(limit)
                .to_list(None)
            )
            return [doc["_id"] for doc in docs]

        pages = [await page(offset) for offset in range(0, total, 2)]
        seen = [card_id for page_ids in pages for card_id in page_ids]

        assert len(seen) == total
        assert len(set(seen)) == total  # no card appears on two pages
        assert seen == sorted(seen)

    async def test_an_offset_past_the_end_is_empty(self, live_db):
        query = await build_query(live_db, CardFilters())
        docs = (
            await live_db["cards"]
            .find(query)
            .sort("_id", 1)
            .skip(len(SEED_CARDS))
            .limit(25)
            .to_list(None)
        )

        assert docs == []

    async def test_count_ignores_paging(self, live_db):
        # total_count has to describe the whole result, not the page.
        query = await build_query(live_db, CardFilters(supertype="Pokémon"))

        assert await live_db["cards"].count_documents(query) == len(SEED_CARDS) - 1
