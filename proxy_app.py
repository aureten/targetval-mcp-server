# proxy_app.py
import os, httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

GATEWAY = os.getenv("GATEWAY_BASE", "https://targetval-gateway.onrender.com")
API_KEY = os.getenv("TARGETVAL_API_KEY", "")

app = FastAPI(title="TargetVal MCP Proxy")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.api_route("/http/{path:path}", methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS","HEAD"])
async def http_passthrough(path: str, request: Request):
    url = f"{GATEWAY.rstrip('/')}/{path}"
    qs = request.url.query
    if qs:
        url = f"{url}?{qs}"
    body = await request.body() if request.method in ("POST","PUT","PATCH") else None

    headers = dict(request.headers)
    headers["host"] = ""
    if API_KEY:
        headers["x-api-key"] = API_KEY
    headers["user-agent"] = "TargetVal-MCP/2.0"

    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.request(request.method, url, headers=headers, content=body)
    return Response(content=r.content, status_code=r.status_code, headers=dict(r.headers))
