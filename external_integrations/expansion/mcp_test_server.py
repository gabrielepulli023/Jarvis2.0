from fastmcp import FastMCP

mcp = FastMCP("JARVIS MCP Test Server")


@mcp.tool
def ping() -> str:
    """Verifica che il server MCP sia raggiungibile."""
    return "JARVIS_MCP_OK"


@mcp.tool
def somma(a: int, b: int) -> int:
    """Somma due numeri interi."""
    return a + b


if __name__ == "__main__":
    mcp.run(transport="stdio")
