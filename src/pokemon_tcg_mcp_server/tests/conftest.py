"""Shared fakes and fixtures.

The fake collection records the queries it is handed and replays canned
documents; it deliberately does not implement Mongo's query language. Query
*construction* is the interesting logic here and is asserted directly against
`build_query` in test_search_cards_query.py, so the tool tests only need a
collection that reports what it was asked for and hands back documents.
"""

from collections.abc import AsyncIterator, Iterable
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from pokemon_tcg_mcp_server import app as app_module
from pokemon_tcg_mcp_server import tools  # noqa: F401  (registers the tools)

# --- documents, shaped the way Mongo stores them (camelCase, '_id') ----------

CHARIZARD: dict[str, Any] = {
    "_id": "base1-4",
    "name": "Charizard",
    "supertype": "Pokémon",
    "subtypes": ["Stage 2"],
    "number": "4",
    "hp": "120",
    "types": ["Fire"],
    "attacks": [
        {
            "name": "Fire Spin",
            "cost": ["Fire", "Fire", "Fire", "Fire"],
            "convertedEnergyCost": 4,
            "damage": "100",
            "text": "Discard 2 Energy cards attached to Charizard.",
        }
    ],
    "weaknesses": [{"type": "Water", "value": "×2"}],
    "resistances": [{"type": "Fighting", "value": "-30"}],
    "retreatCost": ["Colorless", "Colorless", "Colorless"],
    "rarity": "Rare Holo",
    "artist": "Mitsuhiro Arita",
    "images": {
        "small": "https://images.pokemontcg.io/base1/4.png",
        "large": "https://images.pokemontcg.io/base1/4_hires.png",
    },
    # Mongo documents carry fields the model does not map.
    "set": {"id": "base1", "name": "Base"},
}

BILLS: dict[str, Any] = {
    "_id": "base1-91",
    "name": "Bill",
    "supertype": "Trainer",
    "number": "91",
    "rarity": "Common",
    "artist": "Keiji Kinebuchi",
    "images": {"small": "s", "large": "l"},
}

BASE_FOSSIL: dict[str, Any] = {
    "_id": "base-fossil",
    "name": "Base - Fossil",
    "category": "Block",
    "blogLabelYear": 1999,
    "eraYearsCovered": "1999-2000",
    "setRangeLabel": "Base through Fossil",
    "sets": ["base1", "basep", "base2", "base3"],
    "promoSets": [{"name": "Wizards Black Star Promos", "cardRange": "1-9"}],
}

TEAM_ROCKET: dict[str, Any] = {
    "_id": "team-rocket",
    "name": "Team Rocket",
    "category": "Block",
    "sets": ["base5"],
}


# --- fakes ------------------------------------------------------------------


class FakeCursor:
    def __init__(self, docs: Iterable[dict[str, Any]]) -> None:
        self._docs = list(docs)

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        return list(self._docs) if length is None else list(self._docs[:length])


class FakeCollection:
    """Stand-in for a motor collection that records every query it receives."""

    def __init__(self, docs: Iterable[dict[str, Any]] = ()) -> None:
        self.docs = list(docs)
        self.queries: list[dict[str, Any]] = []

    @property
    def last_query(self) -> dict[str, Any]:
        return self.queries[-1]

    def find(self, query: dict[str, Any]) -> FakeCursor:
        self.queries.append(query)
        return FakeCursor(self.docs)

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        """Flat equality only — the only form find_one is called with here."""

        self.queries.append(query)
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                return doc
        return None


class FakeMongoClient(dict):
    """Mapping of database name -> database, with motor's close()."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.closed = False

    def close(self) -> None:
        self.closed = True


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def cards() -> FakeCollection:
    return FakeCollection([CHARIZARD, BILLS])


@pytest.fixture
def block_formats() -> FakeCollection:
    return FakeCollection([BASE_FOSSIL, TEAM_ROCKET])


@pytest.fixture
def db(
    cards: FakeCollection, block_formats: FakeCollection
) -> dict[str, FakeCollection]:
    return {"cards": cards, "block_formats": block_formats}


@pytest.fixture
def mongo_client(db: dict[str, FakeCollection]) -> FakeMongoClient:
    return FakeMongoClient({"pokemon_tcg": db})


@pytest.fixture
def ctx(mongo_client: FakeMongoClient) -> SimpleNamespace:
    """Minimal stand-in for fastmcp's Context, for calling tools directly.

    get_db only reaches through request_context.lifespan_context.client.
    """

    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=SimpleNamespace(client=mongo_client)
        )
    )


@pytest_asyncio.fixture
async def mcp_client(
    monkeypatch: pytest.MonkeyPatch, mongo_client: FakeMongoClient
) -> AsyncIterator[Any]:
    """A connected in-memory MCP client, backed by the fake Mongo client.

    Patching the lifespan's connect step is what keeps these tests off the
    network while still exercising the real server: registration, argument
    coercion, and result serialization all run for real.
    """

    from fastmcp import Client

    async def fake_create_mongodb_client() -> FakeMongoClient:
        return mongo_client

    monkeypatch.setattr(app_module, "create_mongodb_client", fake_create_mongodb_client)

    async with Client(app_module.mcp) as client:
        yield client
