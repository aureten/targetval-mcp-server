# mcp_server.py — TargetVal MCP Proxy (full file)
# Purpose: Serve ChatGPT Actions for Pack‑B by forwarding every HTTP request to the TargetVal Gateway.
# This keeps Actions' "distinct domains" requirement while avoiding code duplication.

import os
from typing import Dict
from fastapi import FastAPI, Request, Response
import httpx
import uvicorn

# Upstream TargetVal Gateway (override via env: TARGETVAL_GATEWAY)
TARGET = os.getenv("TARGETVAL_GATEWAY", "https://targetval-gateway.onrender.com").rstrip("/")

# Network settings
TIMEOUT_S = float(os.getenv("REQUEST_TIMEOUT_S", "30"))

# Hop-by-hop headers we should not forward
HOP_HEADERS = {"host", "content-length", "connection", "keep-alive", "transfer-encoding"}

app = FastAPI(
    title="TargetVal MCP Proxy",
    version="1.0.0",
    description="Forwards all routes to the TargetVal Gateway so Pack‑B Actions resolve."
)

@app.get("/healthz")
def healthz():
    """Simple liveness check that also reports the upstream."""
    return {"ok": True, "proxying_to": TARGET}

@app.get("/")
def root():
    return {"service": "targetval-mcp-proxy", "docs": "/docs", "upstream": TARGET}

@app.api_route("/{path:path}", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS","HEAD"])
async def proxy(path: str, request: Request):
    """
    Transparent reverse proxy:
      - Preserves method, path, query string, and body
      - Forwards most headers, excluding hop-by-hop ones
      - Returns upstream status code, body, and safe headers
    """
    # Build upstream URL
    url = f"{TARGET}/{path}"

    # Collect body and query params
    body = await request.body()
    params = dict(request.query_params)

    # Forward headers, minus hop-by-hop
    headers: Dict[str, str] = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}

    # Optional: propagate x-request-id if present
    if "x-request-id" not in {k.lower() for k in headers}:
        rid = request.headers.get("x-request-id")
        if rid:
            headers["x-request-id"] = rid

    # Call upstream
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        resp = await client.request(request.method, url, params=params, content=body, headers=headers)

    # Filter response headers
    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in HOP_HEADERS}

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
        media_type=resp.headers.get("content-type")
    )

if __name__ == "__main__":
    # Allow local run: python mcp_server.py
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("mcp_server:app", host=host, port=port)
