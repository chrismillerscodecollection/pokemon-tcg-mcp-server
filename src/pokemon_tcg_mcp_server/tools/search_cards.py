import json
import re
from typing import Any

from fastmcp import Context
from fastmcp.exceptions import ToolError

from ..app import mcp
from ..helpers.db_helper import get_db
from ..models import BlockFormat, Card, CardFilters, HPFilter

# hp is stored as a string ('90') and cards without hp omit the key entirely,
# so numeric comparisons have to convert server-side rather than read a
# precomputed hp_numeric field, which no document carries.
HP_AS_INT = {"$convert": {"input": "$hp", "to": "int", "onError": 0, "onNull": 0}}


def build_hp_stage(hp_filter: HPFilter | None) -> dict[str, Any]:
    if hp_filter is None:
        return {}

    conditions: dict[str, Any] = {}
    if hp_filter.eq is not None:
        conditions["hp"] = hp_filter.eq

    bounds: list[dict[str, Any]] = []
    if hp_filter.gte is not None:
        bounds.append({"$gte": [HP_AS_INT, hp_filter.gte]})
    if hp_filter.lte is not None:
        bounds.append({"$lte": [HP_AS_INT, hp_filter.lte]})

    if bounds:
        conditions["$expr"] = {"$and": bounds}
        # Without this, Energy and Trainer cards convert to 0 and match any
        # lte bound.
        conditions.setdefault("hp", {"$exists": True})

    return conditions


async def build_block_format_stage(db, block_format: str) -> dict[str, Any]:
    """Cards carry no set field; the set is the '<set>-<number>' id prefix.

    Only whole sets are matched. A format's promoSets are deliberately skipped:
    each carries a cardRange ('1-9' for wizardsblackstarpromos in base-fossil)
    because only part of the promo set is legal in the format, and a prefix
    regex cannot express that bound. Matching the promo set wholesale would
    return illegal cards, so the filter under-reports rather than lies.

    No promo cards are in the collection yet, so this is currently a no-op. To
    support them, OR in a per-promo-set clause of prefix + numeric range on
    'number'. Write it against real data: cardRange is free text (later formats
    may use '1-9, 12' or 'SWSH001-SWSH050') and 'number' is a string that is
    all-digits today but often alphanumeric in promo sets, so the comparison
    needs $convert with an onError fallback rather than $toInt.
    """

    formats = db["block_formats"]
    doc = await formats.find_one({"_id": block_format})
    if doc is None:
        doc = await formats.find_one({"name": block_format})
    if doc is None:
        raise ToolError(
            f"Unknown block format {block_format!r}. "
            "Call list_all_block_formats for the valid values."
        )

    set_ids = BlockFormat.model_validate(doc).sets
    if not set_ids:
        return {}

    pattern = "^(" + "|".join(re.escape(s) for s in set_ids) + ")-"
    return {"_id": {"$regex": pattern}}


async def build_query(db, filters: CardFilters) -> dict[str, Any]:
    query: dict[str, Any] = {}
    query.update(build_hp_stage(filters.hp))

    if filters.types:
        query["types"] = {"$in": filters.types}

    if filters.weakness is not None:
        query["weaknesses.type"] = filters.weakness

    if filters.attack_cost:
        query["attacks.cost"] = {"$in": filters.attack_cost}

    if filters.rarity is not None:
        query["rarity"] = filters.rarity

    if filters.block_format is not None:
        query.update(await build_block_format_stage(db, filters.block_format))

    return query


@mcp.tool
async def search_cards(ctx: Context, filters: CardFilters) -> str:
    """Search the Pokémon TCG card database by attributes.

    A card must match all provided filters to be returned. Use get_card_by_id
    instead if you already know the card's id. Call list_all_block_formats for
    the valid values of the block_format filter.

    Example: {"weakness": "Water", "block_format": "base-fossil",
              "hp": {"gte": 70}}
    """

    db = get_db(ctx)
    cards = db["cards"]

    query = await build_query(db, filters)
    docs = await cards.find(query).to_list(length=None)
    results = [Card.model_validate(doc).model_dump() for doc in docs]

    return json.dumps(results, indent=1)
