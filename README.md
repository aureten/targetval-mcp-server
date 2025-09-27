# TargetVal MCP Server (remote)

This is a minimal **remote MCP server** that wraps your TargetVal Gateway and exposes the two tools required by ChatGPT connectors and Deep Research:

- `search(query: str)` → returns a JSON string `{"results":[{"id","title","url"}...]}`
- `fetch(id: str)` → returns a JSON string `{"id","title","text","url","metadata"}`

It maps free-form queries like `PCSK9 in hypercholesterolemia` to a handful of **TargetVal** endpoints (aggregate, PPI, pathways, known drugs, clinical endpoints), and lets ChatGPT retrieve the full JSON via `fetch`.

## Deploy on Render

1. Create a **new Web Service** in Render, connect this repo/folder, or upload the ZIP.
2. **Build command:** `pip install -r requirements.txt`
3. **Start command:** (from Procfile) `web: python mcp_server.py`
4. Set env vars (optional):
   - `TARGETVAL_BASE=https://targetval-gateway.onrender.com` (default)
   - `TARGETVAL_LIMIT=25`
   - `MCP_TRANSPORT=sse` (or `http`)
   - `MCP_PATH=/sse`
5. Visit `https://<your-app>.onrender.com/sse` (or `/mcp`) to verify the endpoint is reachable.

## Connect in ChatGPT (Developer mode)

1. Open **Settings → Connectors → Advanced → Developer mode** and enable it.
2. Add a new **Remote MCP server**:
   - **Server URL:** `https://<your-app>.onrender.com/sse`  (or `/mcp` if you used HTTP transport)
   - **Allowed tools:** `search`, `fetch`
   - **Require approval:** `never`
3. In a chat, choose **Use Connectors** and select your server.
4. Ask: `PCSK9 in hypercholesterolemia`

## API (Deep Research / Responses API)

Use the Responses API with an MCP tool config like:

```bash
curl https://api.openai.com/v1/responses   -H "Content-Type: application/json"   -H "Authorization: Bearer $OPENAI_API_KEY"   -d '{
    "model": "o4-mini-deep-research",
    "input": [{"role":"user","content":[{"type":"input_text","text":"PCSK9 in hypercholesterolemia — summarize evidence"}]}],
    "tools": [{"type":"mcp","server_label":"targetval","server_url":"https://<your-app>.onrender.com/sse","allowed_tools":["search","fetch"],"require_approval":"never"}]
  }'
```

## How IDs work

`search()` returns **opaque IDs** that encode the HTTP method and request target:

- `GET|https://.../mech/ppi?symbol=PCSK9&cutoff=0.9&limit=25`
- `POST|https://.../aggregate|{"symbol":"PCSK9","condition":"hypercholesterolemia","modules":["mech_ppi","mech_pathways","tract_drugs","clin_endpoints"],"limit":25}`

`fetch(id)` parses these and performs the HTTP call to your TargetVal Gateway, then wraps the JSON payload into the expected MCP shape.

## Notes

- Keep limits modest to avoid oversized tool responses.
- You can extend `_results_for()` to add more modules or tweak defaults.
- If `/aggregate` is heavy in your deployment, stick to per-module GETs.
