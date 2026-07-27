from mcp.server import MCPServer  # type: ignore[import-not-found]

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
    print("Starting MCP Server")
   
if __name__ == "__main__":
    main()