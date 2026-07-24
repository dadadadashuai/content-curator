# content-curator/app/main.py
"""FastAPI main entry point."""
import os
import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

from .database import init_db
from .routers import creators, contents, process, obsidian, review, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Content Curator API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(creators.router, prefix="/api", tags=["creators"])
app.include_router(contents.router, prefix="/api", tags=["contents"])
app.include_router(process.router, prefix="/api", tags=["process"])
app.include_router(obsidian.router, prefix="/api", tags=["notes"])
app.include_router(review.router, prefix="/api", tags=["review"])
app.include_router(settings.router, prefix="/api", tags=["settings"])


@app.on_event("startup")
async def startup():
    init_db()
    logger.info("Database initialized")
    # Start scheduler
    from .scheduler.jobs import start_scheduler
    start_scheduler()
    logger.info("Scheduler started")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "3.0.0"}


@app.get("/")
def root():
    return RedirectResponse(url="/app", status_code=302)


# Serve frontend static files
import os
STATIC_DIR = Path(os.environ.get("STATIC_DIR", "/app/static"))
if STATIC_DIR.exists():
    app.mount("/app", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:
    @app.get("/app")
    def app_placeholder():
        return {"message": "Frontend not built. Static dir: " + str(STATIC_DIR)}
