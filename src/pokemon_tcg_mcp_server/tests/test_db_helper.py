from types import SimpleNamespace

import pytest

from pokemon_tcg_mcp_server.helpers.db_helper import get_db


def test_returns_the_pokemon_tcg_database(ctx, db):
    assert get_db(ctx) is db


def test_requires_a_request_context():
    ctx = SimpleNamespace(request_context=None)

    with pytest.raises(AssertionError):
        get_db(ctx)
