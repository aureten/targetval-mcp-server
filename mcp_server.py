# mcp_server.py  — TargetVal MCP + public HTTP pass-through (no auth)
# Exposes:
#   • /_http/{path}  → forwards to https://targetval-gateway.onrender.com/{path}
#   • /healthz
#   • {MCP_PATH}     → MCP transport endpoint (HTTP preferred; SSE fallback)
#
# ENV:
#   TARGETVAL_BASE (default https://targetval-gateway.onrender.com)
#   TARGETVAL_LIMIT (default 25)
#   REQUEST_TIMEOUT_S (default 20)
#   MCP_TRANSPORT (default http; use "sse" to force SSE)
#   MCP_PATH (default /sse)
#   PORT (default 8000), HOST (default 0.0.0.0)

import os
import json
import re
import urllib.parse
from typing import Dict, List, Any, Optional, Tuple

import httpx
from fastapi import FastAPI, Request, Response
from fastmcp import FastMCP

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

TARGETVAL_BASE = os.getenv("TARGETVAL_BASE", "https://targetval-gateway.onrender.com").rstrip("/")
DEFAULT_LIMIT = int(os.getenv("TARGETVAL_LIMIT", "25"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT_S", "20"))
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "http").lower()  # "http" preferred, "sse" supported as fallback
MCP_PATH = os.getenv("MCP_PATH", "/sse")
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")

# ----------------------------------------------------------------------------
# FastAPI app (for /_http/* and /healthz, and to host HTTP-transport MCP)
# ----------------------------------------------------------------------------

app = FastAPI(title="TargetVal MCP Server (public)")

HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
    "trailers", "transfer-encoding", "upgrade", "host", "content-length", "accept-encoding"
}

_http_client = httpx.AsyncClient(follow_redirects=True, timeout=REQUEST_TIMEOUT)

@app.get("/healthz")
async def healthz():
    return {"ok": True, "upstream": TARGETVAL_BASE, "mcp_path": MCP_PATH, "transport": MCP_TRANSPORT}

@app.api_route("/_http/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def http_pass_through(path: str, request: Request):
    """
    Public, no-auth forwarder to the TargetVal Gateway.
    Example:  /_http/comp/freedom?symbol=TP53&mode=live
           -> https://targetval-gateway.onrender.com/comp/freedom?symbol=TP53&mode=live
    """
    upstream = f"{TARGETVAL_BASE}/{path}"
    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
    r = await _http_client.request(
        request.method, upstream, params=request.query_params,
        content=(body or None), headers=headers
    )
    return Response(
        content=r.content,
        status_code=r.status_code,
        headers={"content-type": r.headers.get("content-type", "application/json")}
    )

# ----------------------------------------------------------------------------
# MCP: tools & helpers
# ----------------------------------------------------------------------------

mcp = FastMCP("TargetVal-MCP")

def _parse_query(q: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract (symbol, condition) from a free-form query.
    Heuristics: uppercase gene-like token + the rest as condition; supports "X in Y" / "X for Y".
    """
    if not q or not isinstance(q, str):
        ret
