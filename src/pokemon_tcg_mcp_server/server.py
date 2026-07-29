import logging
import sys

from dotenv import load_dotenv
from mcp.server import MCPServer

from pokemon_tcg_mcp_server.mongodb_client import create_mongodb_client

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(message)s",
)

mcp = MCPServer("Demo")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

@mcp.tool()
def get_card(card_id: str) -> str:
    """Retrieve card by card_id."""
    return "True"


def main():
    client = create_mongodb_client()
    print(client)


if __name__ == "__main__":
    main()
