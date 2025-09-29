# mcp_server.py — TargetVal MCP server (original logic; decorator fix only)

import os
import json
import re
import urllib.parse
from typing import Dict, List, Any, Optional, Tuple

import httpx
from fastmcp import FastMCP

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

TARGETVAL_BASE = os.getenv("TARGETVAL_BASE", "https://targetval-gateway.onrender.com").rstrip("/")
DEFAULT_LIMIT = int(os.getenv("TARGETVAL_LIMIT", "25"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT_S", "20"))
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "sse").lower()  # "sse" (ChatGPT docs) or "http" (recommended by FastMCP)
MCP_PATH = os.getenv("MCP_PATH", "/sse")  # Path segment for the transport
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")

mcp = FastMCP("TargetVal-MCP")

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _parse_query(q: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract (symbol, condition) from a free-form query.
    Heuristics: uppercase gene-like token + the rest as condition; also supports "X in Y" / "X for Y".
    """
    if not q or not isinstance(q, str):
        return None, None
    txt = q.strip()
    # Split patterns like "PCSK9 in hypercholesterolemia" or "PCSK9 for LDL lowering"
    m = re.match(r"^\s*([A-Za-z0-9\-]+)\s+(?:in|for|->|→)\s+(.+)$", txt, flags=re.I)
    if m:
        sym = m.group(1).strip()
        cond = m.group(2).strip()
        return sym.upper(), cond

    # Fallback: first ALLCAPS-ish token as symbol, rest as condition
    tokens = txt.split()
    if not tokens:
        return None, None
    # pick first token that looks like a gene-like symbol
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
    body = {
        "symbol": symbol,
        "condition": condition,
        "modules": modules,
        "limit": DEFAULT_LIMIT
    }
    # If your gateway supports a LITE/SCORE mode, you can add it here
    # body["mode"] = "LITE"
    return body

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
        out.append(_mk_result(_encode_get(ppi_url), f"PPI (STRING) for {symbol}", ppi_url))

        # 3) Pathways
        path_url = f"{TARGETVAL_BASE}/mech/pathways?symbol={urllib.parse.quote(symbol)}&limit={DEFAULT_LIMIT}"
        out.append(_mk_result(_encode_get(path_url), f"Pathways (Reactome) for {symbol}", path_url))

        # 4) Tractability: known drugs
        drugs_url = f"{TARGETVAL_BASE}/tract/drugs?symbol={urllib.parse.quote(symbol)}&limit={DEFAULT_LIMIT}"
        out.append(_mk_result(_encode_get(drugs_url), f"Known drugs / interactions for {symbol}", drugs_url))

    # 5) Clinical endpoints by condition
    if condition:
        clin_url = f"{TARGETVAL_BASE}/clin/endpoints?condition={urllib.parse.quote(condition)}&limit={DEFAULT_LIMIT}"
        out.append(_mk_result(_encode_get(clin_url), f"Clinical endpoints for {condition}", clin_url))

    return out

# ----------------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------------

@mcp.tool()  # ← add parentheses
def search(query: str) -> str:
    """
    Return a list of candidate results for a free-form query.
    The return value MUST be a JSON string with {"results":[{id,title,url}...]}
    """
    symbol, condition = _parse_query(query)
    results = _results_for(symbol, condition)
    payload = {"results": results}
    return json.dumps(payload, ensure_ascii=False)

@mcp.tool()  # ← add parentheses
def fetch(id: str) -> str:
    """
    Fetch full content for a given result id.
    The return value MUST be a JSON string of the form:
      {"id": "...", "title": "...", "text": "...", "url": "...", "metadata": {...}}
    """
    if not id or not isinstance(id, str):
        return json.dumps({"error": "invalid id"})

    method, *rest = id.split("|", 2)
    method = method.upper().strip()
    if method == "GET":
        url = rest[0] if rest else ""
        if not url:
            return json.dumps({"error": "missing URL"})
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            r = client.get(url)
            r.raise_for_status()
            js = r.json()
        doc = {
            "id": id,
            "title": f"GET {url}",
            "text": json.dumps(js, ensure_ascii=False),
            "url": url,
            "metadata": {"method": "GET"}
        }
        return json.dumps(doc, ensure_ascii=False)

    if method == "POST":
        if len(rest) < 2:
            return json.dumps({"error": "missing URL or body"})
        url, body_str = rest[0], rest[1]
        try:
            body = json.loads(body_str)
        except Exception:
            body = {}
        with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
            r = client.post(url, json=body)
            r.raise_for_status()
            js = r.json()
        doc = {
            "id": id,
            "title": f"POST {url}",
            "text": json.dumps(js, ensure_ascii=False),
            "url": url,
            "metadata": {"method": "POST", "body": body}
        }
        return json.dumps(doc, ensure_ascii=False)

    return json.dumps({"error": f"unsupported method in id: {method}"})

# ----------------------------------------------------------------------------
# Entrypoint
# ----------------------------------------------------------------------------

if __name__ == "__main__":
    # Choose transport. SSE is commonly used by ChatGPT connectors; FastMCP also supports HTTP.
    if MCP_TRANSPORT == "http":
        mcp.run(transport="http", host=HOST, port=PORT, path=MCP_PATH)
    else:
        # SSE (legacy, widely supported by ChatGPT connectors)
        try:
            mcp.run(transport="sse", host=HOST, port=PORT, path=MCP_PATH)
        except TypeError:
            # Some FastMCP builds don't accept 'path' for SSE; fall back to default root.
            mcp.run(transport="sse", host=HOST, port=PORT)
