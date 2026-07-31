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


@mcp.tool()
async def get_card(ctx: Context, card_id: str):
    """Retrieve card by card_id."""
    assert ctx.request_context is not None
    client = ctx.request_context.lifespan_context.client
    db = client["pokemon_tcg"]
    cards = db["cards"]
    doc = await cards.find_one({"_id": card_id})
    return doc


def main():
   mcp.run(transport="http", host="0.0.0.0", port=8000)
  

if __name__ == "__main__":
    main()
