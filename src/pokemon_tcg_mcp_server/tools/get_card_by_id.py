from fastmcp import Context
from fastmcp.exceptions import ToolError

from ..app import mcp
from ..helpers.db_helper import get_db
from ..models import Card


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
            f"No card found with id {card_id!r}. "
            "Ids look like '<set>-<number>', e.g. 'baseset-11'."
        )

    return Card.model_validate(doc).model_dump_json(indent=1)
