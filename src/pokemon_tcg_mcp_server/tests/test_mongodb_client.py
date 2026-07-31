import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from pokemon_tcg_mcp_server.mongodb_client import create_mongodb_client


@pytest_asyncio.fixture
async def mongodb_client():
    client = await create_mongodb_client()
    yield client
    client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_connect_to_mongodb(mongodb_client):
    assert isinstance(mongodb_client, AsyncIOMotorClient)
