"""Query construction for search_cards.

These assert the exact Mongo query documents produced, which is where the
non-obvious behaviour lives: the string-to-int hp conversion, the guard that
keeps hp-less cards out of bounded results, and the set-prefix regex that
stands in for a set field the cards do not have.
"""

import re
import unicodedata

import pytest
from fastmcp.exceptions import ToolError

from pokemon_tcg_mcp_server.models import CardFilters, HPFilter
from pokemon_tcg_mcp_server.tools.search_cards import (
    HP_AS_INT,
    build_block_format_stage,
    build_hp_stage,
    build_query,
)

from .conftest import FakeCollection


class TestBuildHPStage:
    def test_no_filter(self):
        assert build_hp_stage(None) == {}

    def test_empty_filter(self):
        assert build_hp_stage(HPFilter()) == {}

    def test_eq_matches_the_raw_string(self):
        # hp is stored as a string, so equality needs no conversion.
        assert build_hp_stage(HPFilter(eq="90")) == {"hp": "90"}

    def test_gte_converts_server_side(self):
        assert build_hp_stage(HPFilter(gte=70)) == {
            "$expr": {"$and": [{"$gte": [HP_AS_INT, 70]}]},
            "hp": {"$exists": True},
        }

    def test_lte_converts_server_side(self):
        assert build_hp_stage(HPFilter(lte=70)) == {
            "$expr": {"$and": [{"$lte": [HP_AS_INT, 70]}]},
            "hp": {"$exists": True},
        }

    def test_both_bounds(self):
        stage = build_hp_stage(HPFilter(gte=70, lte=120))

        assert stage["$expr"] == {
            "$and": [{"$gte": [HP_AS_INT, 70]}, {"$lte": [HP_AS_INT, 120]}]
        }

    def test_bounds_require_hp_to_exist(self):
        # Energy and Trainer cards have no hp; $convert would turn the missing
        # value into 0, which satisfies any lte bound.
        assert build_hp_stage(HPFilter(lte=50))["hp"] == {"$exists": True}

    def test_eq_is_not_clobbered_by_the_exists_guard(self):
        stage = build_hp_stage(HPFilter(eq="90", gte=70))

        assert stage["hp"] == "90"
        assert "$expr" in stage

    def test_zero_is_a_real_bound(self):
        # 0 is falsy but explicitly requested; it must not be dropped.
        assert build_hp_stage(HPFilter(gte=0))["$expr"] == {
            "$and": [{"$gte": [HP_AS_INT, 0]}]
        }


@pytest.mark.asyncio
class TestBuildBlockFormatStage:
    async def test_matches_set_id_prefixes(self, db, block_formats):
        # Cards carry no set field; the set is the '<set>-<number>' id prefix.
        stage = await build_block_format_stage(db, "base-fossil")

        assert stage == {"_id": {"$regex": "^(baseset|jungle|fossil)-"}}

    async def test_id_and_name_are_looked_up_in_one_round_trip(self, db, block_formats):
        # Every caller awaits this before it can build its card query, so the
        # sequential id-then-name form put an extra trip on the critical path.
        await build_block_format_stage(db, "base-fossil")

        assert block_formats.queries == [
            {"$or": [{"_id": "base-fossil"}, {"name": "base-fossil"}]}
        ]

    async def test_resolves_by_name(self, db, block_formats):
        stage = await build_block_format_stage(db, "Base - Fossil")

        assert block_formats.queries == [
            {"$or": [{"_id": "Base - Fossil"}, {"name": "Base - Fossil"}]}
        ]
        assert stage == {"_id": {"$regex": "^(baseset|jungle|fossil)-"}}

    async def test_unknown_format_raises_tool_error(self, db):
        with pytest.raises(ToolError, match="Unknown block format 'nope'"):
            await build_block_format_stage(db, "nope")

    async def test_unknown_format_points_at_the_discovery_tool(self, db):
        with pytest.raises(ToolError, match="list_all_block_formats"):
            await build_block_format_stage(db, "nope")

    async def test_format_without_sets_does_not_filter(self):
        db = {
            "block_formats": FakeCollection([{"_id": "empty", "name": "E", "sets": []}])
        }

        assert await build_block_format_stage(db, "empty") == {}

    async def test_set_ids_are_regex_escaped(self):
        db = {
            "block_formats": FakeCollection(
                [{"_id": "f", "name": "F", "sets": ["sv3.5", "a+b"]}]
            )
        }

        stage = await build_block_format_stage(db, "f")

        assert stage == {"_id": {"$regex": r"^(sv3\.5|a\+b)-"}}


@pytest.mark.asyncio
class TestBuildQuery:
    async def test_no_filters_matches_everything(self, db):
        assert await build_query(db, CardFilters()) == {}

    async def test_types(self, db):
        query = await build_query(db, CardFilters(types=["Fire", "Water"]))

        assert query == {"types": {"$in": ["Fire", "Water"]}}

    async def test_weakness_reaches_into_the_subdocument(self, db):
        query = await build_query(db, CardFilters(weakness="Water"))

        assert query == {"weaknesses.type": "Water"}

    async def test_attack_cost_binds_every_symbol_to_one_attack(self, db):
        # $elemMatch is what stops the symbols being spread across two attacks.
        query = await build_query(db, CardFilters(attack_cost=["Fire", "Colorless"]))

        assert query == {
            "attacks": {"$elemMatch": {"cost": {"$all": ["Fire", "Colorless"]}}}
        }

    async def test_empty_attack_cost_does_not_filter(self, db):
        # {'$all': []} matches nothing, so the guard is what keeps an empty
        # list a no-op rather than a query that returns zero cards.
        assert await build_query(db, CardFilters(attack_cost=[])) == {}

    async def test_supertype_is_an_exact_match(self, db):
        query = await build_query(db, CardFilters(supertype="Trainer"))

        assert query == {"supertype": "Trainer"}

    async def test_supertype_is_normalised_to_the_stored_form(self, db):
        # 'Pokémon' decomposed: 'e' + U+0301 renders identically but is a
        # different string, and every document stores the composed form.
        decomposed = unicodedata.normalize("NFD", "Pokémon")
        assert decomposed != "Pokémon"

        query = await build_query(db, CardFilters(supertype=decomposed))

        assert query == {"supertype": "Pokémon"}

    async def test_name_is_a_case_insensitive_substring(self, db):
        query = await build_query(db, CardFilters(name="char"))

        assert query == {"name": {"$regex": "char", "$options": "i"}}

    async def test_name_escapes_regex_metacharacters(self, db):
        # Unescaped, the '.' in 'Mr. Mime' would match any character.
        query = await build_query(db, CardFilters(name="Mr. Mime"))

        assert query["name"]["$regex"] == re.escape("Mr. Mime")

    async def test_empty_name_does_not_filter(self, db):
        assert await build_query(db, CardFilters(name="")) == {}

    async def test_resistance_reaches_into_the_subdocument(self, db):
        query = await build_query(db, CardFilters(resistance="Fighting"))

        assert query == {"resistances.type": "Fighting"}

    async def test_rarity(self, db):
        query = await build_query(db, CardFilters(rarity="Rare Holo"))

        assert query == {"rarity": "Rare Holo"}

    async def test_block_format(self, db):
        query = await build_query(db, CardFilters(block_format="team-rocket"))

        assert query == {"_id": {"$regex": "^(base5)-"}}

    async def test_filters_are_combined(self, db):
        query = await build_query(
            db,
            CardFilters(
                hp=HPFilter(gte=70),
                types=["Fire"],
                supertype="Pokémon",
                name="char",
                weakness="Water",
                resistance="Fighting",
                attack_cost=["Fire"],
                rarity="Rare Holo",
                block_format="base-fossil",
            ),
        )

        assert query == {
            "$expr": {"$and": [{"$gte": [HP_AS_INT, 70]}]},
            "hp": {"$exists": True},
            "types": {"$in": ["Fire"]},
            "supertype": "Pokémon",
            "name": {"$regex": "char", "$options": "i"},
            "weaknesses.type": "Water",
            "resistances.type": "Fighting",
            "attacks": {"$elemMatch": {"cost": {"$all": ["Fire"]}}},
            "rarity": "Rare Holo",
            "_id": {"$regex": "^(baseset|jungle|fossil)-"},
        }
