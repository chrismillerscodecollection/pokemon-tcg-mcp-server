import json
import re

from fastmcp import Context
from fastmcp.exceptions import ToolError

from ..app import mcp
from ..helpers.db_helper import get_db

# The trap this hint exists for: the set name in a card id is not the code in
# that card's image URL, and the image URL is the only one of the two the
# server ever shows you. 'base1-91' is the natural guess and it is wrong.
ID_HINT = (
    "Ids look like '<set>-<number>', e.g. 'baseset-4'. Set names come from "
    "list_all_block_formats ('baseset', 'jungle', 'fossil') and are not the "
    "codes in the image URLs: 'baseset-91' is served from "
    "'https://images.pokemontcg.io/base1/91.png'."
)


# Every images.small value is served from this one host. Anchoring the
# did-you-mean regex to it is what lets an index on 'images.small' answer the
# query -- see image_url_pattern.
IMAGE_HOST = "https://images.pokemontcg.io"


def image_url_pattern(card_id: str) -> str | None:
    """A regex matching the images.small URL an image-namespace id implies.

    'base1-91' becomes '^https://images\\.pokemontcg\\.io/base1/91\\.png$',
    which is how a caller who guessed the id from an image URL gets pointed at
    the real one. Split on the LAST hyphen: set names may contain one, card
    numbers do not. The trailing anchor is what stops '/base1/9.png' matching
    '/base1/91.png'.

    Anchored at BOTH ends on purpose. A pattern that only ends in '$' is a
    collection scan, because Mongo can only serve a regex from an index when it
    is a literal prefix match -- and the miss path this runs on is exactly what
    a caller guessing ids generates in bulk. The cost is that a document served
    from some other host stops resolving: the caller then gets the plain
    'no card with that id' message, which still names the id scheme, rather
    than a wrong answer.

    Returns None for an id with no usable '<prefix>-<number>' shape.
    """

    prefix, separator, number = card_id.rpartition("-")
    if not separator or not prefix or not number:
        return None

    return "^" + re.escape(f"{IMAGE_HOST}/{prefix}/{number}.png") + "$"


@mcp.tool
async def get_card_by_id(ctx: Context, card_id: str) -> str:
    """Retrieve a single card by its exact id, e.g. 'baseset-4'.

    Use search_cards to find cards by attributes when the id is unknown. When
    the user's intent includes seeing the actual card, return the URL inline as
    markdown for the 'large' version of the image.
    """

    db = get_db(ctx)
    cards = db["cards"]
    doc = await cards.find_one({"_id": card_id})

    if doc is None:
        # An id in the image-URL namespace is by far the most common near
        # miss, so resolve it and name the right id rather than reporting a
        # bare absence the caller cannot tell from a typo.
        pattern = image_url_pattern(card_id)
        if pattern is not None:
            alias = await cards.find_one({"images.small": {"$regex": pattern}})
            if alias is not None:
                raise ToolError(
                    f"unknown id {card_id!r}; did you mean {alias['_id']!r}? {ID_HINT}"
                )

        raise ToolError(
            f"No card with id {card_id!r}. {ID_HINT} "
            "Use search_cards to find the id from the card's attributes."
        )

    # Returned unvalidated, so the caller sees every stored field rather than
    # only the ones the Card model maps. That also means no pydantic pass
    # normalises the values, so default=str covers any BSON type (ObjectId,
    # datetime, Decimal128) that json cannot encode on its own. Today's
    # documents are all plain JSON types; this keeps a future one from
    # turning the tool into a TypeError.
    return json.dumps(doc, indent=1, default=str)
