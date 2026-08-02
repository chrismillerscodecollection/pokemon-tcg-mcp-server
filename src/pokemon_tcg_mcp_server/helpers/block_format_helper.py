"""Which sets a block format contains, and whether a card is one of them.

Two callers need this from opposite directions: search_cards wants a query
fragment, validate_deck wants a predicate. Keeping both here means they cannot
drift apart — and it keeps validate_deck from importing search_cards, which
would run a @mcp.tool registration as an import side effect and make the
registration order depend on import order.
"""

import re
from typing import Any

from fastmcp.exceptions import ToolError

from ..models import BlockFormat, PromoSet


async def load_block_format(db, block_format: str) -> BlockFormat:
    """Look up a format by id or name; raise if neither hits.

    One round trip rather than a find_one on '_id' followed by a find_one on
    'name'. Every caller awaits this before it can build its card query, so the
    trip it saves is on the critical path of both search_cards and
    validate_deck.

    The tradeoff: '$or' gives no precedence, where the sequential form let a
    match on '_id' win. That only differs if one document's 'name' equals a
    *different* document's '_id' — ids are slugs ('base-fossil') and names are
    titles ('Base - Fossil'), so no such pair exists. If one is ever added,
    this returns whichever document Mongo reaches first.
    """

    formats = db["block_formats"]
    doc = await formats.find_one(
        {"$or": [{"_id": block_format}, {"name": block_format}]}
    )
    if doc is None:
        raise ToolError(
            f"Unknown block format {block_format!r}. "
            "Call list_all_block_formats for the valid values."
        )

    return BlockFormat.model_validate(doc)


def set_prefix_pattern(set_ids: list[str]) -> str:
    """A regex matching any card id from one of these sets.

    Cards carry no set field; the set is the '<set>-<number>' id prefix.
    """

    return "^(" + "|".join(re.escape(s) for s in set_ids) + ")-"


def is_card_in_sets(card_id: str, set_ids: list[str]) -> bool:
    """The string-level equivalent of set_prefix_pattern, for one card id.

    Prefix-testing against the known set list rather than splitting card_id on
    '-' — splitting picks the wrong boundary for any set id that itself
    contains a hyphen, whereas this agrees with the regex by construction.

    An empty set list means the format declares no sets, which produces no
    filter in search_cards, so it must not reject anything here either.
    """

    if not set_ids:
        return True
    return any(card_id.startswith(f"{s}-") for s in set_ids)


def promo_set_for(card_id: str, block_format: BlockFormat) -> PromoSet | None:
    """The format's promo set this card belongs to, if any.

    A format's promoSets are deliberately excluded from the search filter: each
    carries a cardRange ('1-9' for wizardsblackstarpromos in base-fossil)
    because only part of the promo set is legal, and a prefix regex cannot
    express that bound. Search under-reports rather than returning illegal
    cards. Deck validation has to invert that: silently applying the same rule
    would reject a legal promo card, so callers use this to warn instead.

    No promo cards are in the collection yet. To match them properly, OR in a
    per-promo-set clause of prefix plus a numeric range on 'number'. Write it
    against real data: cardRange is free text (later formats may use '1-9, 12'
    or 'SWSH001-SWSH050') and 'number' is a string that is all-digits today but
    often alphanumeric in promo sets, so the comparison needs $convert with an
    onError fallback rather than $toInt.
    """

    return next(
        (p for p in block_format.promo_sets if card_id.startswith(f"{p.name}-")),
        None,
    )


def block_format_query(block_format: BlockFormat) -> dict[str, Any]:
    """The card-query fragment restricting results to this format's sets."""

    if not block_format.sets:
        return {}
    return {"_id": {"$regex": set_prefix_pattern(block_format.sets)}}
