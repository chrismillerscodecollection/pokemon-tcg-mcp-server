import json

from fastmcp import Context
from fastmcp.exceptions import ToolError

from ..app import mcp
from ..helpers.db_helper import get_db


@mcp.tool
async def get_card_by_id(ctx: Context, card_id: str) -> str:
    """Retrieve a single card by its exact id.

    Use search_cards to find cards by attributes when the id is unknown. When
    the user's intent includes seeing the actual card, return the URL inline as
    markdown for the 'large' version of the image.
    """

    db = get_db(ctx)
    cards = db["cards"]
    doc = await cards.find_one({"_id": card_id})

    if doc is None:
        raise ToolError(
            f"No card with id {card_id!r}. "
            "Ids look like '<set>-<number>', e.g. 'base1-4'. "
            "Use search_cards to find the id from the card's attributes."
        )

    # Returned unvalidated, so the caller sees every stored field rather than
    # only the ones the Card model maps. That also means no pydantic pass
    # normalises the values, so default=str covers any BSON type (ObjectId,
    # datetime, Decimal128) that json cannot encode on its own. Today's
    # documents are all plain JSON types; this keeps a future one from
    # turning the tool into a TypeError.
    return json.dumps(doc, indent=1, default=str)
