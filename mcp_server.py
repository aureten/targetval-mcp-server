# mcp_server.py  — TargetVal MCP + public HTTP pass-through
# - Public, no keys. One server, one port.
# - Exposes:
#     • /_http/{path}     → forwards to https://targetval-gateway.onrender.com/{path}
#     • /healthz          → simple health check
#     • {MCP_PATH}        → MCP transport endpoint (HTTP preferred; SSE fallback)
#
# ENV knobs:
#   TARGETVAL_BASE      default: https://targetval-gateway.onrender.com
#   TARGETVAL_LIMIT     default: 25
#   REQUEST_TIMEOUT_S   default: 20
#   MCP_TRANSPORT       default: http   (use "http" to mount into this FastAPI app; "sse" fallback supported)
#   MCP_PATH            default: /sse   (endpoint path for MCP transport)
#   PORT                default: 8000
#   HOST                default: 0.0.0.0

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
    # Return upstream content-type (default to JSON)
    return Response(
        content=r.content,
        status_code=r.status_code,
        headers={"content-type": r.headers.get("content-type", "application/json")}
    )

# ----------------------------------------------------------------------------
# MCP: tools & helpers (unchanged behavior)
# ----------------------------------------------------------------------------

mcp = FastMCP("TargetVal-MCP")

def _parse_query(q: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract (symbol, condition) from a free-form query.
    Heuristics: uppercase gene-like token + the rest as condition; also supports "X in Y" / "X for Y".
    """
    if not q or not isinstance(q, str):
        return None, None
    txt = q.strip()
    m = re.match(r"^\s*([A-Za-z0-9\-]+)\s+(?:in|for|->|→)\s+(.+)$", txt, flags=re.I)
    if m:
        sym = m.group(1).strip()
        cond = m.group(2).strip()
        return sym.upper(), cond

    tokens = txt.split()
    if not tokens:
        return None, None
    sym = None
    for t in tokens:
        up = t.strip().upper()
        if len(up) <= 12 and re.fullmatch(r"[A-Z0-9\-]+", up):
            sym = up
            break
    if sym:
        rest = txt.replace(sym, "", 1).strip(" ,;:")
        return sym, (rest or None)
    return None, txt

def _mk_result(id_: str, title: str, url: str) -> Dict[str, str]:
    return {"id": id_, "title": title, "url": url}

def _encode_get(url: str) -> str:
    return f"GET|{url}"

def _encode_post(url: str, body: Dict[str, Any]) -> str:
    return f"POST|{url}|{json.dumps(body, separators=(',',':'))}"

def _aggregate_body(symbol: Optional[str], condition: Optional[str]) -> Dict[str, Any]:
    # Keep payload light and focused on high-signal modules
    modules = ["mech_ppi", "mech_pathways", "tract_drugs", "clin_endpoints"]
    return {
        "symbol": symbol,
        "condition": condition,
        "modules": modules,
        "limit": DEFAULT_LIMIT
    }

def _results_for(symbol: Optional[str], condition: Optional[str]) -> List[Dict[str, str]]:
    """Return a small list of actionable results for the query."""
    out: List[Dict[str, str]] = []

    # 1) Aggregate (POST)
    agg_url = f"{TARGETVAL_BASE}/aggregate"
    agg_body = _aggregate_body(symbol, condition)
    out.append(_mk_result(
        _encode_post(agg_url, agg_body),
        f"TargetVal aggregate (symbol={symbol or 'NA'}, condition={condition or 'NA'})",
        agg_url
    ))

    # 2) Mechanistic PPI (GET)
    if symbol:
        ppi_url = f"{TARGETVAL_BASE}/mech/ppi?symbol={urllib.parse.quote(symbol)}&cutoff=0.9&limit={DEFAULT_LIMIT}"
        out.append(_mk_result(_encode_get(ppi_url), f"PPI (STRING)_
