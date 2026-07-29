import os

from dotenv import load_dotenv
from mcp.server import MCPServer
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from pymongo.server_api import ServerApi

load_dotenv()

db_password = os.getenv("DB_PASSWORD")
uri = f"mongodb+srv://cm_dev:{db_password}@pokemon-tcg-cluster.ufxy8d9.mongodb.net/?appName=pokemon-tcg-cluster"
client: MongoClient = MongoClient(uri, server_api=ServerApi("1"))

mcp = MCPServer("Demo")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@mcp.resource("greeting://{name}")
def greeting(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}"


@mcp.tool()
def get_card(card_id: str) -> str:
    """Retrieve card by card_id."""
    return "True"


def main():
    try:
        client.admin.command("ping")
        print("Pinged your deployment. You successfully connected to MongoDB!")
    except ConnectionFailure as e:
        print(f"Failed to connect to MongoDB: {e}")


if __name__ == "__main__":
    main()
