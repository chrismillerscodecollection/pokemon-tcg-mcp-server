import pytest
from pymongo import MongoClient

from pokemon_tcg_mcp_server.mongodb_client import create_mongodb_client


@pytest.fixture
def mongodb_client():
    client = create_mongodb_client()
    yield client
    client.close()


@pytest.mark.integration
def test_connect_to_mongodb(mongodb_client):
    assert isinstance(mongodb_client, MongoClient)
