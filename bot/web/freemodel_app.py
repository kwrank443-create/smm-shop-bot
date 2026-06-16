"""FastAPI app: admin API and freemodel proxy."""
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import httpx

# Import admin API
from bot.web.api_admin import router as admin_router
from bot.web.freemodel_admin import router as fm_router, init_tables

app = FastAPI(title="SMM Bot Admin + Freemodel API")

# Include routers
app.include_router(admin_router, prefix="/api/admin")
app.include_router(fm_router)  # Already has /freemodel prefix


# ─── Freemodel proxy passthrough ────────────────────────────────────────

PROXY_BASE = "http://127.0.0.1:8765"

@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_v1(path: str, request: Request):
    """Proxy requests to freemodel."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        url = f"{PROXY_BASE}/v1/{path}"
        body = await request.body()
        headers = dict(request.headers)
        headers.pop("host", None)
        
        resp = await client.request(
            method=request.method,
            url=url,
            content=body,
            headers=headers,
        )
        
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            headers=dict(resp.headers),
        )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.on_event("startup")
async def startup():
    """Initialize tables on startup."""
    await init_tables()
