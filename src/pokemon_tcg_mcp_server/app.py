from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastmcp import FastMCP
from pymongo import AsyncMongoClient

from pokemon_tcg_mcp_server.mongodb_client import create_mongodb_client


@dataclass
class AppContext:
    client: AsyncMongoClient


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    client = await create_mongodb_client()
    try:
        yield AppContext(client=client)
    finally:
        # Awaited, unlike motor's synchronous close(): the pymongo async client
        # shuts its connection pool and monitoring tasks down as a coroutine.
        await client.close()


mcp = FastMCP("Pokemon TCG MCP Server", lifespan=app_lifespan)
