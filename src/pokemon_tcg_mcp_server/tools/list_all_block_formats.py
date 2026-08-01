from fastmcp import Context

from ..app import mcp
from ..helpers.db_helper import get_db


@mcp.tool
async def list_all_block_formats(ctx: Context) -> str:
    """List all block formats in the database.

    Useful for discovering valid values for the 'block format' filter in
    search_cards.
    """

    db = get_db(ctx)
    formats = db["block_formats"]
    doc = await formats.find({})
    return doc
