import asyncio
import json
import re
import unicodedata
from typing import Annotated, Any

from fastmcp import Context
from pydantic import Field

from ..app import mcp
from ..helpers.block_format_helper import block_format_query, load_block_format
from ..helpers.db_helper import get_db
from ..models import Card, CardFilters, HPFilter, SearchResults

# hp is stored as a string ('90') and cards without hp omit the key entirely,
# so numeric comparisons have to convert server-side rather than read a
# precomputed hp_numeric field, which no document carries.
HP_AS_INT = {"$convert": {"input": "$hp", "to": "int", "onError": 0, "onNull": 0}}

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


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
    """The set-prefix rationale lives in helpers/block_format_helper.py."""

    return block_format_query(await load_block_format(db, block_format))


def _nfc(value: str) -> str:
    """Normalise to the composed form the database stores.

    'Pokémon' is written with a precomposed U+00E9 in every document. A caller
    that sends the decomposed 'e' + U+0301 renders an identical string and
    would match nothing at all, with no way to see why.
    """

    return unicodedata.normalize("NFC", value)


async def build_query(db, filters: CardFilters) -> dict[str, Any]:
    query: dict[str, Any] = {}
    query.update(build_hp_stage(filters.hp))

    if filters.types:
        query["types"] = {"$in": filters.types}

    if filters.supertype is not None:
        query["supertype"] = _nfc(filters.supertype)

    if filters.name:
        # Escaped: card names contain regex metacharacters ('Mr. Mime'), where
        # an unescaped '.' would quietly match any character.
        query["name"] = {"$regex": re.escape(_nfc(filters.name)), "$options": "i"}

    if filters.weakness is not None:
        query["weaknesses.type"] = filters.weakness

    if filters.resistance is not None:
        query["resistances.type"] = filters.resistance

    if filters.attack_cost:
        # $elemMatch pins the $all to a single attack, so 'Fire' and 'Colorless'
        # must appear on the *same* attack rather than being spread across two.
        # The empty-list guard above matters: {'$all': []} matches nothing, so
        # dropping it would turn a no-op filter into a zero-result query.
        query["attacks"] = {"$elemMatch": {"cost": {"$all": filters.attack_cost}}}

    if filters.rarity is not None:
        query["rarity"] = filters.rarity

    if filters.block_format is not None:
        query.update(await build_block_format_stage(db, filters.block_format))

    return query


@mcp.tool
async def search_cards(
    ctx: Context,
    filters: CardFilters,
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> str:
    """Search the Pokémon TCG card database by attributes.

    A card must match every filter provided. Use get_card_by_id instead if you
    already know the card's id. Call list_all_block_formats for the valid
    values of block_format.

    Filters, all optional and all ANDed together:

      supertype    Exact match on one of "Pokémon", "Trainer", "Energy".
                   {"supertype": "Trainer"} returns only Trainers.
      name         Case-insensitive substring. {"name": "char"} matches both
                   Charizard and Charmeleon.
      types        Matches a card carrying ANY of the listed types, not all of
                   them. {"types": ["Fire", "Water"]} returns Fire cards and
                   Water cards.
      hp           {"eq": "90"} compares against the raw stored string, so
                   "090" will not match. {"gte": 70, "lte": 120} converts
                   server-side and excludes cards that have no hp at all,
                   i.e. every Trainer and Energy card.
      weakness     The weakness TYPE only; the multiplier is ignored.
                   {"weakness": "Water"} matches a card weak to Water ×2.
      resistance   The resistance TYPE only; the value is ignored.
                   {"resistance": "Psychic"} matches a card resisting
                   Psychic -30.
      attack_cost  ONE single attack must contain ALL the listed symbols. This
                   is set containment, not multiset, so ["Fire", "Fire"]
                   behaves exactly like ["Fire"]. {"attack_cost": ["Fire",
                   "Colorless"]} matches Arcanine, whose Flamethrower costs
                   Fire Fire Colorless, but not Ninetales, whose Fire and
                   Colorless costs sit on two different attacks.
      rarity       Exact match. {"rarity": "Rare Holo"}.
      block_format Restricts to the sets in that format.
                   {"block_format": "base-fossil"}.

    limit (1-100, default 25) and offset (default 0) are TOP-LEVEL arguments,
    not filters; a limit placed inside "filters" is ignored. The response is
    {"total_count", "limit", "offset", "returned", "cards"}. Page by raising
    offset until offset + returned reaches total_count.

    Example: {"filters": {"supertype": "Pokémon", "weakness": "Water",
              "block_format": "base-fossil", "hp": {"gte": 70}}, "limit": 10}
    """

    db = get_db(ctx)
    cards = db["cards"]

    query = await build_query(db, filters)

    # Sorted because an unsorted find has no ordering guarantee — this
    # collection demonstrably returns cards out of _id order — and paging over
    # an unstable order silently repeats some cards and drops others.
    cursor = cards.find(query).sort("_id", 1).skip(offset).limit(limit)

    # Issued together: the count and the page are independent queries, and
    # awaiting them in turn made every search pay two round trips end to end.
    # They are still two round trips, so the pair is not one snapshot — this is
    # read-only reference data, so nothing can change between them.
    total_count, docs = await asyncio.gather(
        cards.count_documents(query),
        cursor.to_list(limit),
    )

    page = [Card.model_validate(doc) for doc in docs]
    results = SearchResults(
        total_count=total_count,
        limit=limit,
        offset=offset,
        returned=len(page),
        cards=page,
    )

    return json.dumps(results.model_dump(), indent=1)
