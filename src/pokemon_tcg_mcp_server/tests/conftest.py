"""Shared fakes and fixtures.

The fake collection records the queries it is handed and replays canned
documents; it deliberately does not implement Mongo's query language. Query
*construction* is the interesting logic here and is asserted directly against
`build_query` in test_search_cards_query.py, so the tool tests only need a
collection that reports what it was asked for and hands back documents.

Three deliberate exceptions to that rule:

* `sort`/`skip`/`limit` are honoured for real. They are list operations rather
  than query semantics, so the fake can implement them exactly — and paging is
  precisely the thing that would go unnoticed if it were faked loosely.
* `find_one` understands dotted paths, `$regex` and `$or`, which get_card_by_id's
  did-you-mean fallback and load_block_format's one-trip lookup need. Anything
  beyond those raises NotImplementedError rather than quietly returning a wrong
  answer, which is what stops this from growing into a bad MongoDB emulator.
* `find` filters on `{'_id': {'$in': [...]}}`, and only that shape. validate_deck
  bounds its `to_list` by the number of ids it asked for; a cursor that returned
  documents the query excluded would hit that bound and drop real answers, so
  the fake has to be honest about this one form.

Documents use the real id namespace: '<set>-<number>' with the set spelled the
way block_formats spells it ('baseset'), which is *not* the code that appears
in the card's image URL ('base1'). That mismatch is real, and get_card_by_id
exists to soften it, so the fixtures have to reproduce it faithfully.
"""

import re
from collections.abc import AsyncIterator, Iterable
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from pokemon_tcg_mcp_server import app as app_module
from pokemon_tcg_mcp_server import tools  # noqa: F401  (registers the tools)

# --- documents, shaped the way Mongo stores them (camelCase, '_id') ----------

CHARIZARD: dict[str, Any] = {
    "_id": "baseset-4",
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
    "legalities": {"unlimited": "Legal"},
    "images": {
        "small": "https://images.pokemontcg.io/base1/4.png",
        "large": "https://images.pokemontcg.io/base1/4_hires.png",
    },
    # Mongo documents carry fields the model does not map.
    "set": {"id": "base1", "name": "Base"},
}

BILLS: dict[str, Any] = {
    "_id": "baseset-91",
    "name": "Bill",
    "supertype": "Trainer",
    # A Trainer's whole function lives in 'rules'.
    "rules": ["Draw 2 cards."],
    "number": "91",
    "rarity": "Common",
    "artist": "Keiji Kinebuchi",
    "legalities": {"unlimited": "Legal"},
    "images": {
        "small": "https://images.pokemontcg.io/base1/91.png",
        "large": "https://images.pokemontcg.io/base1/91_hires.png",
    },
}

BASE_FOSSIL: dict[str, Any] = {
    "_id": "base-fossil",
    "name": "Base - Fossil",
    "category": "Block",
    "blogLabelYear": 1999,
    "eraYearsCovered": "1999-2000",
    "setRangeLabel": "Base through Fossil",
    "sets": ["baseset", "jungle", "fossil"],
    "promoSets": [{"name": "wizardsblackstarpromos", "cardRange": "1-9"}],
}

TEAM_ROCKET: dict[str, Any] = {
    "_id": "team-rocket",
    "name": "Team Rocket",
    "category": "Block",
    "sets": ["base5"],
}

# --- extra documents, for validate_deck only --------------------------------
# Kept out of the shared `cards` fixture so the existing exact-list assertions
# do not churn; the `deck_cards` fixture wires them in where they are wanted.

FIRE_ENERGY: dict[str, Any] = {
    "_id": "baseset-98",
    "name": "Fire Energy",
    "supertype": "Energy",
    "subtypes": ["Basic"],  # exempt from the copy limit
    "number": "98",
    "images": {"small": "https://images.pokemontcg.io/base1/98.png", "large": ""},
}

DOUBLE_COLORLESS: dict[str, Any] = {
    "_id": "baseset-96",
    "name": "Double Colorless Energy",
    "supertype": "Energy",
    "subtypes": ["Special"],  # NOT exempt: its own rules say so
    "rules": ["Doesn't count as a basic Energy card."],
    "number": "96",
}

# One name, two ids, inside one set. The copy limit counts names, so four of
# each is eight Moltres and illegal.
MOLTRES_12: dict[str, Any] = {
    "_id": "fossil-12",
    "name": "Moltres",
    "supertype": "Pokémon",
    "subtypes": ["Basic"],
    "hp": "70",
    "types": ["Fire"],
}

MOLTRES_27: dict[str, Any] = {
    "_id": "fossil-27",
    "name": "Moltres",
    "supertype": "Pokémon",
    "subtypes": ["Basic"],
    "hp": "70",
    "types": ["Fire"],
}

OUT_OF_FORMAT: dict[str, Any] = {
    "_id": "neogenesis-1",
    "name": "Feraligatr",
    "supertype": "Pokémon",
    "subtypes": ["Stage 2"],
    "hp": "100",
    "types": ["Water"],
}

PROMO: dict[str, Any] = {
    # base-fossil declares wizardsblackstarpromos with cardRange '1-9', which
    # the set-prefix logic cannot express — so legality here is unverifiable.
    "_id": "wizardsblackstarpromos-4",
    "name": "Pikachu",
    "supertype": "Pokémon",
    "subtypes": ["Basic"],
    "hp": "40",
    "types": ["Lightning"],
}


# --- fakes ------------------------------------------------------------------


def _in_filter(query: dict[str, Any]) -> list[str] | None:
    """The id list from a `{'_id': {'$in': [...]}}` query, if that is the shape.

    The one query form the cursor filters on. validate_deck bounds its to_list
    by the number of ids it asked for, which is exact against real Mongo but
    would truncate a non-filtering fake into dropping documents it should have
    returned -- so the fake has to be faithful here or the bound is untestable.
    """

    criterion = query.get("_id")
    if len(query) != 1 or not isinstance(criterion, dict):
        return None
    if set(criterion) != {"$in"}:
        return None
    return list(criterion["$in"])


class FakeCursor:
    """Records the modifiers it was chained with, and applies them for real."""

    def __init__(
        self, docs: Iterable[dict[str, Any]], query: dict[str, Any] | None = None
    ) -> None:
        ids = _in_filter(query or {})
        if ids is not None:
            docs = [doc for doc in docs if doc.get("_id") in ids]
        self._docs = list(docs)
        self.applied: dict[str, Any] = {"sort": None, "skip": None, "limit": None}

    def sort(self, key: str, direction: int = 1) -> "FakeCursor":
        if not isinstance(key, str):
            # The multi-key form would need a different comparison; refuse it
            # rather than let the fake report an order it did not produce.
            raise NotImplementedError("FakeCursor.sort takes (field, direction) only")
        self.applied["sort"] = (key, direction)
        return self

    def skip(self, count: int) -> "FakeCursor":
        self.applied["skip"] = count
        return self

    def limit(self, count: int) -> "FakeCursor":
        self.applied["limit"] = count
        return self

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        docs = list(self._docs)

        sort = self.applied["sort"]
        if sort is not None:
            # Compared as strings: the only field the tools sort on is _id,
            # which is always a string, and a missing key sorts first rather
            # than blowing up the comparison.
            field, direction = sort
            docs.sort(key=lambda doc: str(doc.get(field, "")), reverse=direction < 0)

        start = self.applied["skip"] or 0
        stop = None if self.applied["limit"] is None else start + self.applied["limit"]
        docs = docs[start:stop]

        return docs if length is None else docs[:length]


def _resolve(doc: dict[str, Any], path: str) -> Any:
    """Read a possibly dotted path out of a document."""

    value: Any = doc
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _matches(value: Any, criterion: Any) -> bool:
    if isinstance(criterion, dict):
        unsupported = set(criterion) - {"$regex"}
        if unsupported:
            raise NotImplementedError(
                f"FakeCollection does not implement {sorted(unsupported)}"
            )
        return (
            isinstance(value, str) and re.search(criterion["$regex"], value) is not None
        )
    return value == criterion


def _matches_query(doc: dict[str, Any], query: dict[str, Any]) -> bool:
    """Field predicates ANDed together, plus a top-level '$or'.

    '$or' is a query operator rather than a field path, so it cannot go through
    _resolve like the rest. load_block_format uses it to look a format up by id
    or name in one round trip.
    """

    for key, value in query.items():
        if key == "$or":
            if not any(_matches_query(doc, branch) for branch in value):
                return False
        elif key.startswith("$"):
            raise NotImplementedError(f"FakeCollection does not implement {key!r}")
        elif not _matches(_resolve(doc, key), value):
            return False
    return True


class FakeCollection:
    """Stand-in for an async collection that records every query it receives."""

    def __init__(self, docs: Iterable[dict[str, Any]] = ()) -> None:
        self.docs = list(docs)
        self.queries: list[dict[str, Any]] = []
        self.count_queries: list[dict[str, Any]] = []
        self.cursors: list[FakeCursor] = []

    @property
    def last_query(self) -> dict[str, Any]:
        return self.queries[-1]

    @property
    def last_cursor(self) -> FakeCursor:
        return self.cursors[-1]

    def find(self, query: dict[str, Any]) -> FakeCursor:
        self.queries.append(query)
        cursor = FakeCursor(self.docs, query)
        self.cursors.append(cursor)
        return cursor

    async def count_documents(self, query: dict[str, Any]) -> int:
        """Recorded separately so a test can prove find and count agree.

        Handing the two calls different predicates is the classic paging bug,
        and it is invisible unless the queries are kept apart. The fake does
        not filter, so the count is simply the corpus size.
        """

        self.count_queries.append(query)
        return len(self.docs)

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        """Equality, dotted paths, $regex and $or — the forms the tools use."""

        self.queries.append(query)
        for doc in self.docs:
            if _matches_query(doc, query):
                return doc
        return None


class FakeMongoClient(dict):
    """Mapping of database name -> database, with the driver's close().

    close() is a coroutine: pymongo's AsyncMongoClient shuts down as an await,
    where motor's client closed synchronously.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def cards() -> FakeCollection:
    return FakeCollection([CHARIZARD, BILLS])


@pytest.fixture
def deck_cards(cards: FakeCollection) -> FakeCollection:
    """The `cards` collection widened with the documents deck tests need.

    validate_deck asks for {'_id': {'$in': [...]}}, which the fake cursor
    filters on for real, so an id absent from these docs comes back missing and
    is reported unknown, as it should be.
    """

    cards.docs = [
        CHARIZARD,
        BILLS,
        FIRE_ENERGY,
        DOUBLE_COLORLESS,
        MOLTRES_12,
        MOLTRES_27,
        OUT_OF_FORMAT,
        PROMO,
    ]
    return cards


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
