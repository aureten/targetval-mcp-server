import httpx
from openai_agents.mcp.server import MCPServer, Tool

async def fetch_evidence(symbol: str, condition: str, modules: list[str] | None = None) -> dict:
    params = {"symbol": symbol, "condition": condition}
    if modules:
        params["modules"] = ",".join(modules)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get("https://targetval-gateway.onrender.com/v1/targetval", params=params)
        resp.raise_for_status()
        return resp.json()

fetch_tool = Tool(
    name="fetch_targetval_evidence",
    description="Fetch aggregated target‑validation evidence for a gene and condition.",
    input_schema={
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Gene symbol (e.g., TP53)"},
            "condition": {"type": "string", "description": "Disease or condition (e.g., breast cancer)"},
            "modules": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of module names to call"
            }
        },
        "required": ["symbol", "condition"]
    },
    output_schema={"type": "object"},
    coroutine=fetch_evidence,
)

server = MCPServer(tools=[fetch_tool])

if __name__ == "__main__":
    server.run(host="0.0.0.0", port=8080)
