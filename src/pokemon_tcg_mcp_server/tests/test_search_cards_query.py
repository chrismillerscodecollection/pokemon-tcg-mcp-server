"""Query construction for search_cards.

These assert the exact Mongo query documents produced, which is where the
non-obvious behaviour lives: the string-to-int hp conversion, the guard that
keeps hp-less cards out of bounded results, and the set-prefix regex that
stands in for a set field the cards do not have.
"""

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

        assert stage == {"_id": {"$regex": "^(base1|basep|base2|base3)-"}}

    async def test_looked_up_by_id_first(self, db, block_formats):
        await build_block_format_stage(db, "base-fossil")

        assert block_formats.queries[0] == {"_id": "base-fossil"}

    async def test_falls_back_to_name(self, db, block_formats):
        stage = await build_block_format_stage(db, "Base - Fossil")

        assert block_formats.queries == [
            {"_id": "Base - Fossil"},
            {"name": "Base - Fossil"},
        ]
        assert stage == {"_id": {"$regex": "^(base1|basep|base2|base3)-"}}

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

    async def test_attack_cost(self, db):
        query = await build_query(db, CardFilters(attack_cost=["Fire"]))

        assert query == {"attacks.cost": {"$in": ["Fire"]}}

    async def test_empty_attack_cost_does_not_filter(self, db):
        assert await build_query(db, CardFilters(attack_cost=[])) == {}

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
                weakness="Water",
                attack_cost=["Fire"],
                rarity="Rare Holo",
                block_format="base-fossil",
            ),
        )

        assert query == {
            "$expr": {"$and": [{"$gte": [HP_AS_INT, 70]}]},
            "hp": {"$exists": True},
            "types": {"$in": ["Fire"]},
            "weaknesses.type": "Water",
            "attacks.cost": {"$in": ["Fire"]},
            "rarity": "Rare Holo",
            "_id": {"$regex": "^(base1|basep|base2|base3)-"},
        }
