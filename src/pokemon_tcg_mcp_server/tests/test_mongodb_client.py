from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import ConnectionFailure

from pokemon_tcg_mcp_server import mongodb_client as mongodb_client_module
from pokemon_tcg_mcp_server.mongodb_client import create_mongodb_client


class FakeAdmin:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.commands: list[str] = []

    async def command(self, name: str):
        self.commands.append(name)
        if self.error is not None:
            raise self.error
        return {"ok": 1}


class FakeMotorClient:
    """Records the arguments motor was constructed with."""

    def __init__(self, uri, *, server_api=None, error: Exception | None = None):
        self.uri = uri
        self.server_api = server_api
        self.admin = FakeAdmin(error)


@pytest.fixture
def motor_factory(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Swaps in a fake motor client.

    Exposes `created` (every client built) and `state["error"]`, which a test
    sets to make the ping fail.
    """

    created: list[FakeMotorClient] = []
    state: dict[str, Exception | None] = {"error": None}

    def factory(uri: str, server_api: Any = None) -> FakeMotorClient:
        client = FakeMotorClient(uri, server_api=server_api, error=state["error"])
        created.append(client)
        return client

    monkeypatch.setattr(mongodb_client_module, "AsyncIOMotorClient", factory)
    return SimpleNamespace(created=created, state=state)


@pytest.mark.asyncio
async def test_requires_db_uri(monkeypatch):
    monkeypatch.delenv("DB_URI", raising=False)

    with pytest.raises(ValueError, match="DB_URI environment variable is not set"):
        await create_mongodb_client()


@pytest.mark.asyncio
async def test_empty_db_uri_is_treated_as_unset(monkeypatch):
    monkeypatch.setenv("DB_URI", "")

    with pytest.raises(ValueError):
        await create_mongodb_client()


@pytest.mark.asyncio
async def test_connects_with_the_configured_uri(monkeypatch, motor_factory):
    monkeypatch.setenv("DB_URI", "mongodb://example/test")

    client = await create_mongodb_client()

    assert client is motor_factory.created[0]
    assert client.uri == "mongodb://example/test"


@pytest.mark.asyncio
async def test_pins_the_stable_server_api(monkeypatch, motor_factory):
    monkeypatch.setenv("DB_URI", "mongodb://example/test")

    client = await create_mongodb_client()

    assert client.server_api.version == "1"


@pytest.mark.asyncio
async def test_pings_the_deployment(monkeypatch, motor_factory):
    monkeypatch.setenv("DB_URI", "mongodb://example/test")

    client = await create_mongodb_client()

    assert client.admin.commands == ["ping"]


@pytest.mark.asyncio
async def test_unreachable_deployment_raises_connection_error(
    monkeypatch, motor_factory
):
    monkeypatch.setenv("DB_URI", "mongodb://example/test")
    failure = ConnectionFailure("no route to host")
    motor_factory.state["error"] = failure

    with pytest.raises(
        ConnectionError, match="Failed to connect to MongoDB"
    ) as excinfo:
        await create_mongodb_client()

    assert excinfo.value.__cause__ is failure


@pytest.mark.asyncio
async def test_other_errors_are_not_swallowed(monkeypatch, motor_factory):
    monkeypatch.setenv("DB_URI", "mongodb://example/test")
    motor_factory.state["error"] = RuntimeError("something else")

    with pytest.raises(RuntimeError, match="something else"):
        await create_mongodb_client()


@pytest_asyncio.fixture
async def mongodb_client():
    client = await create_mongodb_client()
    yield client
    client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_connect_to_mongodb(mongodb_client):
    assert isinstance(mongodb_client, AsyncIOMotorClient)
