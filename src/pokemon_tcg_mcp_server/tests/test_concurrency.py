"""The independent queries in a tool are issued together, not in turn.

Both tools await two queries that need nothing from each other. Written
sequentially they still return the right answer, so ordinary behaviour tests
cannot tell the two apart — the only difference is that every call pays both
round trips end to end instead of one.

These pin it by making each query block until the other has also started. A
sequential implementation never reaches the second one and times out; a
concurrent one sails through. The barrier is what does the work here, so a
failure means the awaits were serialised, not that anything was slow.
"""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from pokemon_tcg_mcp_server.models import CardFilters, DeckEntry, DeckList
from pokemon_tcg_mcp_server.tools.search_cards import search_cards
from pokemon_tcg_mcp_server.tools.validate_deck import validate_deck

from .conftest import BASE_FOSSIL, BILLS, CHARIZARD, FakeCollection, FakeCursor

# Generous: a passing run clears the barrier immediately, and only a serialised
# implementation ever waits at all.
TIMEOUT_SECONDS = 2.0


class Rendezvous:
    """Two operations that each block until the other has started."""

    def __init__(self, parties: int = 2) -> None:
        self.barrier = asyncio.Barrier(parties)
        self.arrivals: list[str] = []

    async def arrive(self, name: str) -> None:
        self.arrivals.append(name)
        await self.barrier.wait()


class RendezvousCursor(FakeCursor):
    def __init__(
        self, docs: Any, query: dict[str, Any], rendezvous: Rendezvous
    ) -> None:
        super().__init__(docs, query)
        self._rendezvous = rendezvous

    async def to_list(self, length: int | None = None) -> list[dict[str, Any]]:
        await self._rendezvous.arrive("find")
        return await super().to_list(length)


class RendezvousCollection(FakeCollection):
    """A collection whose reads wait for the tool's other read to begin."""

    def __init__(self, docs: Any, rendezvous: Rendezvous) -> None:
        super().__init__(docs)
        self._rendezvous = rendezvous

    def find(self, query: dict[str, Any]) -> RendezvousCursor:
        self.queries.append(query)
        cursor = RendezvousCursor(self.docs, query, self._rendezvous)
        self.cursors.append(cursor)
        return cursor

    async def count_documents(self, query: dict[str, Any]) -> int:
        await self._rendezvous.arrive("count_documents")
        return await super().count_documents(query)

    async def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        await self._rendezvous.arrive("find_one")
        return await super().find_one(query)


def context(**collections: FakeCollection) -> SimpleNamespace:
    return SimpleNamespace(
        request_context=SimpleNamespace(
            lifespan_context=SimpleNamespace(client={"pokemon_tcg": collections})
        )
    )


async def within_timeout(coro):
    try:
        return await asyncio.wait_for(coro, TIMEOUT_SECONDS)
    except TimeoutError:  # pragma: no cover - only on a regression
        pytest.fail(
            "the two queries were awaited one after the other; neither reached "
            "the barrier the other was waiting on"
        )


@pytest.mark.asyncio
async def test_search_counts_and_pages_at_the_same_time():
    rendezvous = Rendezvous()
    cards = RendezvousCollection([CHARIZARD, BILLS], rendezvous)

    result = await within_timeout(
        search_cards(context(cards=cards), CardFilters(), limit=25, offset=0)
    )

    assert sorted(rendezvous.arrivals) == ["count_documents", "find"]
    assert '"total_count": 2' in result


@pytest.mark.asyncio
async def test_deck_loads_the_format_while_fetching_its_cards():
    rendezvous = Rendezvous()
    cards = RendezvousCollection([CHARIZARD], rendezvous)
    block_formats = RendezvousCollection([BASE_FOSSIL], rendezvous)

    result = await within_timeout(
        validate_deck(
            context(cards=cards, block_formats=block_formats),
            DeckList(
                cards=[DeckEntry(card_id="baseset-4", count=60)],
                block_format="base-fossil",
            ),
        )
    )

    assert sorted(rendezvous.arrivals) == ["find", "find_one"]
    # 60 Charizard breaks the copy limit, which proves both results were used:
    # the count came from the card fetch, the legality from the format lookup.
    assert '"valid": false' in result
    assert "60 copies of 'Charizard'" in result
