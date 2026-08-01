from fastmcp import Context

from ..app import mcp
from ..helpers.db_helper import get_db


@mcp.tool
async def search_cards(ctx: Context, *args) -> str:
    """Search the Pokémon TCG card database by attributes.

    A card must match all provided filters to be returned. Use get_card_by_id
    instead if you already know the card's id.

    Example: {weakness: 'Water', set: 'baseset', hpMin: 70}
    """

    db = get_db(ctx)
    cards = db["cards"]
    doc = await cards.find({})
    return doc
