import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from pymongo import AsyncMongoClient
from pymongo.errors import ConnectionFailure

from pokemon_tcg_mcp_server import mongodb_client as mongodb_client_module
from pokemon_tcg_mcp_server.mongodb_client import (
    MAX_POOL_SIZE,
    MIN_POOL_SIZE,
    SERVER_SELECTION_TIMEOUT_MS,
    WAIT_QUEUE_TIMEOUT_MS,
    create_mongodb_client,
)


class FakeAdmin:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.commands: list[str] = []

    async def command(self, name: str):
        self.commands.append(name)
        if self.error is not None:
            raise self.error
        return {"ok": 1}


class FakeAsyncMongoClient:
    """Records the arguments the driver was constructed with, and its close."""

    def __init__(self, uri, *, error: Exception | None = None, **options: Any):
        self.uri = uri
        self.options = options
        self.server_api = options.get("server_api")
        self.admin = FakeAdmin(error)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def driver_factory(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Swaps in a fake AsyncMongoClient.

    Exposes `created` (every client built) and `state["error"]`, which a test
    sets to make the ping fail.
    """

    created: list[FakeAsyncMongoClient] = []
    state: dict[str, Exception | None] = {"error": None}

    def factory(uri: str, **options: Any) -> FakeAsyncMongoClient:
        client = FakeAsyncMongoClient(uri, error=state["error"], **options)
        created.append(client)
        return client

    monkeypatch.setattr(mongodb_client_module, "AsyncMongoClient", factory)
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
async def test_connects_with_the_configured_uri(monkeypatch, driver_factory):
    monkeypatch.setenv("DB_URI", "mongodb://example/test")

    client = await create_mongodb_client()

    assert client is driver_factory.created[0]
    assert client.uri == "mongodb://example/test"


@pytest.mark.asyncio
async def test_pins_the_stable_server_api(monkeypatch, driver_factory):
    monkeypatch.setenv("DB_URI", "mongodb://example/test")

    client = await create_mongodb_client()

    assert client.server_api.version == "1"


@pytest.mark.asyncio
async def test_pool_is_prewarmed_and_bounded(monkeypatch, driver_factory):
    # The pool is shared by every request, so these are the server's real
    # concurrency limits. minPoolSize is what keeps the first burst of callers
    # from each paying a handshake before its query starts.
    monkeypatch.setenv("DB_URI", "mongodb://example/test")

    client = await create_mongodb_client()

    assert client.options["minPoolSize"] == MIN_POOL_SIZE
    assert client.options["maxPoolSize"] == MAX_POOL_SIZE


@pytest.mark.asyncio
async def test_waiting_on_the_database_is_bounded(monkeypatch, driver_factory):
    # Both default to waiting far longer than a caller will, and a hung request
    # holds its MCP session open the whole time.
    monkeypatch.setenv("DB_URI", "mongodb://example/test")

    client = await create_mongodb_client()

    assert client.options["waitQueueTimeoutMS"] == WAIT_QUEUE_TIMEOUT_MS
    assert client.options["serverSelectionTimeoutMS"] == SERVER_SELECTION_TIMEOUT_MS


@pytest.mark.asyncio
async def test_pings_the_deployment(monkeypatch, driver_factory):
    monkeypatch.setenv("DB_URI", "mongodb://example/test")

    client = await create_mongodb_client()

    assert client.admin.commands == ["ping"]


@pytest.mark.asyncio
async def test_unreachable_deployment_raises_connection_error(
    monkeypatch, driver_factory
):
    monkeypatch.setenv("DB_URI", "mongodb://example/test")
    failure = ConnectionFailure("no route to host")
    driver_factory.state["error"] = failure

    with pytest.raises(
        ConnectionError, match="Failed to connect to MongoDB"
    ) as excinfo:
        await create_mongodb_client()

    assert excinfo.value.__cause__ is failure


@pytest.mark.asyncio
async def test_other_errors_are_not_swallowed(monkeypatch, driver_factory):
    monkeypatch.setenv("DB_URI", "mongodb://example/test")
    driver_factory.state["error"] = RuntimeError("something else")

    with pytest.raises(RuntimeError, match="something else"):
        await create_mongodb_client()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        ConnectionFailure("no route to host"),
        RuntimeError("something else"),
        asyncio.CancelledError(),
    ],
    ids=["connection-failure", "other-error", "cancellation"],
)
async def test_a_failed_ping_closes_the_client(monkeypatch, driver_factory, error):
    # The client holds a pool and topology-monitoring tasks from construction,
    # so raising without closing leaks them: nothing else has a reference.
    monkeypatch.setenv("DB_URI", "mongodb://example/test")
    driver_factory.state["error"] = error

    with pytest.raises(BaseException):  # noqa: B017 - the type varies by case
        await create_mongodb_client()

    assert driver_factory.created[0].closed


@pytest.mark.asyncio
async def test_a_successful_connection_is_left_open(monkeypatch, driver_factory):
    # The caller owns it from here; app_lifespan is what closes it.
    monkeypatch.setenv("DB_URI", "mongodb://example/test")

    client = await create_mongodb_client()

    assert not client.closed


@pytest_asyncio.fixture
async def mongodb_client():
    client = await create_mongodb_client()
    yield client
    await client.close()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_connect_to_mongodb(mongodb_client):
    assert isinstance(mongodb_client, AsyncMongoClient)
