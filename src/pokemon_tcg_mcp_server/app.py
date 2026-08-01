from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastmcp import FastMCP
from motor.motor_asyncio import AsyncIOMotorClient

from pokemon_tcg_mcp_server.mongodb_client import create_mongodb_client


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
