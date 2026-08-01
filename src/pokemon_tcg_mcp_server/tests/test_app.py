import pytest

from pokemon_tcg_mcp_server import app as app_module
from pokemon_tcg_mcp_server.app import AppContext, app_lifespan, mcp

from .conftest import FakeMongoClient


@pytest.fixture
def patched_connect(monkeypatch, mongo_client):
    async def fake_create_mongodb_client() -> FakeMongoClient:
        return mongo_client

    monkeypatch.setattr(app_module, "create_mongodb_client", fake_create_mongodb_client)
    return mongo_client


def test_server_is_named():
    assert mcp.name == "Pokemon TCG MCP Server"


@pytest.mark.asyncio
async def test_lifespan_exposes_the_client(patched_connect):
    async with app_lifespan(mcp) as context:
        assert isinstance(context, AppContext)
        assert context.client is patched_connect


@pytest.mark.asyncio
async def test_lifespan_closes_the_client(patched_connect):
    async with app_lifespan(mcp):
        assert not patched_connect.closed

    assert patched_connect.closed


@pytest.mark.asyncio
async def test_client_is_closed_when_the_body_raises(patched_connect):
    with pytest.raises(RuntimeError):
        async with app_lifespan(mcp):
            raise RuntimeError("boom")

    assert patched_connect.closed
