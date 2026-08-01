import json

from fastmcp import Context

from ..app import mcp
from ..helpers.db_helper import get_db
from ..models import BlockFormat


@mcp.tool
async def list_all_block_formats(ctx: Context) -> str:
    """List all block formats in the database.

    Useful for discovering valid values for the 'block_format' filter in
    search_cards. Match on the returned 'id'.
    """

    db = get_db(ctx)
    formats = db["block_formats"]
    docs = await formats.find({}).to_list(length=None)
    results = [BlockFormat.model_validate(doc).model_dump() for doc in docs]

    return json.dumps(results, indent=1)
