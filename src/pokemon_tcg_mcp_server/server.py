import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from dotenv import load_dotenv
from fastmcp import Context, FastMCP
from motor.motor_asyncio import AsyncIOMotorClient

from pokemon_tcg_mcp_server.mongodb_client import create_mongodb_client

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(message)s",
)


@dataclass
class AppContext:
    client: AsyncIOMotorClient


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    client = await create_mongodb_client()
    try:
        yield AppContext(client=client)
    finally:
        client.close()


mcp = FastMCP("Pokemon TCG MCP Server", lifespan=app_lifespan)


def get_db(ctx: Context):
    assert ctx.request_context is not None
    client = ctx.request_context.lifespan_context.client
    db = client["pokemon_tcg"]
    return db


@mcp.tool()
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


@mcp.tool()
async def list_all_block_formats(ctx: Context) -> str:
    """List all block formats in the database.

    Useful for discovering valid values for the 'block format' filter in
    search_cards.
    """

    db = get_db(ctx)
    formats = db["block_formats"]
    doc = await formats.find({})
    return doc


@mcp.tool()
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


def main():
    mcp.run(transport="http", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
