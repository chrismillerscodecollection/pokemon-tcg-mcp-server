import asyncio
import json
from typing import Any

from fastmcp import Context

from ..app import mcp
from ..helpers.block_format_helper import (
    is_card_in_sets,
    load_block_format,
    promo_set_for,
)
from ..helpers.db_helper import get_db
from ..models import DeckList, DeckValidation
from .get_card_by_id import ID_HINT

DECK_SIZE = 60
MAX_COPIES = 4


def is_basic_energy(doc: dict[str, Any]) -> bool:
    """Basic Energy is exempt from the copy limit; Special Energy is not.

    supertype alone is the wrong test. Double Colorless Energy is supertype
    Energy with subtypes ["Special"], and its own rules text spells out that it
    does not count as a basic Energy card — so it is capped at four like any
    other card.
    """

    return doc.get("supertype") == "Energy" and "Basic" in (doc.get("subtypes") or [])


def is_basic_pokemon(doc: dict[str, Any]) -> bool:
    return doc.get("supertype") == "Pokémon" and "Basic" in (doc.get("subtypes") or [])


@mcp.tool
async def validate_deck(ctx: Context, deck: DeckList) -> str:
    """Check a decklist against a block format's construction rules.

    Verifies that the deck holds exactly 60 cards, that no card NAME appears
    more than 4 times (basic Energy is exempt, Special Energy is not), that
    every id exists, and that every card belongs to a set in the given format.

    Counting is by name, not by id: Moltres is printed twice in Fossil as
    'fossil-12' and 'fossil-27', and four of each is eight Moltres and illegal.

    Returns {"valid", "errors", "warnings", "total_cards"}. Warnings never
    make a deck invalid; they mark what this tool could not verify.

    Example: {"deck": {"block_format": "base-fossil", "cards": [
              {"card_id": "baseset-4", "count": 2},
              {"card_id": "baseset-98", "count": 20}]}}
    """

    db = get_db(ctx)
    errors: list[str] = []
    warnings: list[str] = []

    # Sum repeated entries rather than rejecting them: a list assembled in
    # pieces legitimately mentions an id twice, and silently keeping only one
    # would validate a deck the caller did not send.
    counts: dict[str, int] = {}
    for entry in deck.cards:
        if entry.card_id in counts:
            warnings.append(
                f"{entry.card_id!r} is listed more than once; the counts were "
                "added together"
            )
        counts[entry.card_id] = counts.get(entry.card_id, 0) + entry.count

    total = sum(counts.values())
    if total != DECK_SIZE:
        errors.append(f"deck has {total} cards; exactly {DECK_SIZE} are required")

    # Issued together: the format lookup and the card fetch need nothing from
    # each other, and running them in turn made every call pay both round trips
    # end to end. An unknown format still raises out of the gather; the card
    # query it races just goes to waste, which only happens on the error path.
    #
    # to_list is bounded by the id count rather than None: the query asks for
    # exactly these ids, so this is the true size of the answer, and it keeps a
    # future collection change from letting one request read unbounded memory.
    card_ids = list(counts)
    block_format, docs = await asyncio.gather(
        load_block_format(db, deck.block_format),
        db["cards"].find({"_id": {"$in": card_ids}}).to_list(len(card_ids)),
    )
    by_id = {doc["_id"]: doc for doc in docs}

    by_name: dict[str, int] = {}
    has_basic_pokemon = False

    for card_id, count in counts.items():
        doc = by_id.get(card_id)
        if doc is None:
            errors.append(f"unknown card id {card_id!r}. {ID_HINT}")
            continue

        if not is_basic_energy(doc):
            by_name[doc["name"]] = by_name.get(doc["name"], 0) + count

        has_basic_pokemon = has_basic_pokemon or is_basic_pokemon(doc)

        if is_card_in_sets(card_id, block_format.sets):
            continue

        promo = promo_set_for(card_id, block_format)
        if promo is not None:
            # Warn rather than reject: the format legalises only part of the
            # promo set and this tool cannot read that range, so calling the
            # card illegal would be a confident lie.
            warnings.append(
                f"{card_id!r} is from promo set {promo.name!r}, of which only "
                f"cards {promo.card_range} are legal in "
                f"{block_format.id!r}; this tool cannot verify that range"
            )
            continue

        errors.append(
            f"{card_id!r} ({doc['name']}) is not legal in {block_format.id!r}"
        )

    # Sorted so the same deck always reports its problems in the same order.
    for name, count in sorted(by_name.items()):
        if count > MAX_COPIES:
            errors.append(
                f"{count} copies of {name!r}; at most {MAX_COPIES} are allowed "
                "(basic Energy is exempt)"
            )

    if by_id and not has_basic_pokemon:
        warnings.append(
            "deck contains no Basic Pokémon, so it cannot put anything into "
            "play at the start of a game"
        )

    result = DeckValidation(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        total_cards=total,
    )

    return json.dumps(result.model_dump(), indent=1)
