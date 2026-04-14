# API Patterns (FastAPI Web Viewer)

## App Factory

The web viewer uses a factory function — no global app instance:

```python
def create_app(graph: CallGraph, index: ProjectIndex, project_name: str) -> FastAPI:
    app = FastAPI(title=f"Cartograph — {project_name}")
    # Set module-level state
    # Mount static files
    # Return app
```

Called by CLI `serve` command. State is module-level (`_graph`, `_index`, etc.).

## Endpoint Structure

All API endpoints under `/api/`:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serve SPA (`index.html`) |
| GET | `/api/overview` | Project stats, entry points by type |
| GET | `/api/graph/{qname}` | Call graph trace for function |
| GET | `/api/callers/{qname}` | Reverse dependency lookup |
| GET | `/api/search?q=` | Search functions by name |
| GET | `/api/narrate/{qname}` | LLM-powered flow narration |

## Query Parameters

```python
@app.get("/api/graph/{qname:path}")
async def get_graph(qname: str, depth: int = 5):
    # depth: 1-10, default 5
```

```python
@app.get("/api/search")
async def search(q: str, limit: int = 20):
    # limit: max 100
```

## Response Serialization

Responses built via dedicated serializer functions in `cartograph/web/serializers.py`:

```python
serialize_overview(index, graph, entry_point_ids)
serialize_graph_trace(graph, qname, depth)
serialize_callers(graph, qname)
serialize_search(graph, query, limit)
```

## No Auth

Web viewer is local-only. No authentication, no CORS restrictions. Runs on `localhost:3333` by default.

## Adding New Endpoints

1. Add endpoint function in `cartograph/web/app.py` inside `create_app()`
2. Add serializer in `cartograph/web/serializers.py`
3. Use module-level `_graph` / `_index` for data access
