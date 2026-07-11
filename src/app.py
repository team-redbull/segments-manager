from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .config.settings import setup_logging, SITES, validate_site_prefixes
from .api.routes import router
from .database import init_storage, close_storage
from .auth.auth import is_authenticated
import os

# Setup logging
logger = setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    try:
        # Validate site prefixes configuration before anything else
        logger.info("Validating site prefixes configuration...")
        validate_site_prefixes()
        logger.info("Site prefixes validation passed")

        await init_storage()
        logger.info(f"MongoDB storage initialized. Managing sites: {SITES}")
    except Exception as e:
        logger.error(f"Failed to initialize application: {e}")
        raise

    yield

    # Shutdown
    await close_storage()

# FastAPI app - used by uvicorn server
app = FastAPI(title="Segments Manager API", lifespan=lifespan)

# Custom StaticFiles class with caching headers
class CachedStaticFiles(StaticFiles):
    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        
        # Convert to Path object and get file extension
        path = Path(full_path)
        file_extension = path.suffix.lower()
        
        # Add cache headers for static assets. Filenames aren't content-hashed,
        # so assets must always revalidate (via the ETag/Last-Modified above) —
        # long max-age/immutable caching would let browsers run stale JS/CSS
        # for up to a year after a deploy.
        if file_extension in ['.css', '.js', '.html', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg']:
            response.headers["Cache-Control"] = "no-cache"
        else:
            # Default cache for other files
            response.headers["Cache-Control"] = "public, max-age=86400"  # 1 day
            
        return response

# Mount static files with caching
app.mount("/static", CachedStaticFiles(directory="static"), name="static")

# Read (GET/HEAD) API calls stay open so the web UI needs no authentication;
# every mutating call must present a valid API token via the Authorization
# header. There is no username/password login — the token is the only credential.
_PUBLIC_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@app.middleware("http")
async def enforce_api_auth(request: Request, call_next):
    """Require a valid API token for all mutating /api/* requests.

    Enforced centrally (fail-closed) so any new write endpoint is protected by
    default. Clients send an `Authorization: Bearer <API_TOKEN>` header.
    """
    if (
        request.url.path.startswith("/api/")
        and request.method not in _PUBLIC_METHODS
        and not is_authenticated(request)
    ):
        return JSONResponse(
            status_code=401,
            content={
                "detail": "Authentication required. Provide a valid API token via "
                "'Authorization: Bearer <token>'."
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await call_next(request)


# CORS middleware — added last so it stays the outermost layer and applies its
# headers to every response, including preflight and the 401s above.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, prefix="/api")

# HTML UI - Serve static HTML file
@app.get("/", response_class=HTMLResponse)
async def read_root():
    try:
        with open("static/html/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read(), headers={"Cache-Control": "no-cache"})
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Error: index.html not found</h1>", status_code=500)