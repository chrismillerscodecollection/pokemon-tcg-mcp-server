import json

from fastmcp import Context

from ..app import mcp
from ..helpers.db_helper import get_db
from ..models import BlockFormat

# There are a few dozen block formats in the history of the game and the
# collection is hand-curated, so this cannot truncate a real answer. It is here
# because the tool serialises every document it reads into one response: an
# unbounded to_list would let a mistakenly-seeded collection turn each
# concurrent call into an arbitrarily large allocation.
MAX_BLOCK_FORMATS = 500


@mcp.tool
async def list_all_block_formats(ctx: Context) -> str:
    """List all block formats in the database.

    Useful for discovering valid values for the 'block_format' filter in
    search_cards. Match on the returned 'id'.
    """

    db = get_db(ctx)
    formats = db["block_formats"]
    docs = await formats.find({}).to_list(length=MAX_BLOCK_FORMATS)
    results = [BlockFormat.model_validate(doc).model_dump() for doc in docs]

    return json.dumps(results, indent=1)
