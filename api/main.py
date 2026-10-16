"""FastAPI app: the JSON API under /api and the static website (web/) at /.

uv run uvicorn api.main:app --reload
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from api.routes import ask, data, findings
from api.settings import get_settings

app = FastAPI(
    title="TransitPulse API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json"
)
app.include_router(data.router)
app.include_router(ask.router)
app.include_router(findings.router)
# text compression for the site and the JSON (Cloud Run sends what the app sends). Starlette leaves
# text/event-stream alone, so Ask's progress events still stream one by one.
app.add_middleware(GZipMiddleware, minimum_size=1024)

if origins := get_settings().cors_origin_list:
    # pages on another domain (braedynthompson.com/transitpulse/) read the API on Cloud Run; GET for the data,
    # POST for Ask (a JSON body, so browsers send a preflight)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Accept"],
        max_age=3600,
    )


# /healthz is for probes that reach the container directly (Cloud Run's startup probe, the smoke tests). On the public
# *.run.app URL, Google's front end answers paths ending in "z" itself (404), so checks from outside use /api/health.
@app.get("/healthz", include_in_schema=False)
@app.get("/api/health", include_in_schema=False)
def healthz() -> dict:
    return {"ok": True}


class CachedStatic(StaticFiles):
    """Static files with cache headers: map data for a day, code/styles revalidated, fonts for a year."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path: str = scope.get("path", "")

        async def send_with_cache(message):
            if message["type"] == "http.response.start":
                if path.startswith("/fonts/"):
                    value = "public, max-age=31536000, immutable"
                elif path.startswith("/data/"):
                    value = "public, max-age=86400"
                else:
                    value = "no-cache"
                message.setdefault("headers", []).append((b"cache-control", value.encode()))
            await send(message)

        await super().__call__(scope, receive, send_with_cache)


app.mount("/", CachedStatic(directory=get_settings().web_dir, html=True), name="web")
