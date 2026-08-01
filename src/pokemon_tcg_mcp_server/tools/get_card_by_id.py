from fastmcp import Context

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
    return doc
