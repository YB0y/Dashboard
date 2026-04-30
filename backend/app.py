import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.config import Settings
from backend.database import Database
from backend.github_client import GitHubClient
from backend.websocket_manager import WebSocketManager
from backend.poller import Poller
from backend.routers import repos, issues, notifications, ws, settings as settings_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    db = Database(settings.db_url)
    await db.init()

    # Create one GitHubClient per PAT
    gh_clients = [GitHubClient(pat=pat) for pat in settings.github_pats]
    logging.getLogger(__name__).info("Created %d GitHub API clients", len(gh_clients))

    ws_manager = WebSocketManager()
    poller = Poller(db, gh_clients, ws_manager, settings)

    app.state.db = db
    app.state.gh_clients = gh_clients
    app.state.ws_manager = ws_manager
    app.state.settings = settings

    poller_task = asyncio.create_task(poller.start())

    yield

    await poller.stop()
    poller_task.cancel()
    try:
        await poller_task
    except asyncio.CancelledError:
        pass
    for gh in gh_clients:
        await gh.close()
    await db.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Gittensor Dashboard", version="3.0.0", lifespan=lifespan)

    app.include_router(repos.router)
    app.include_router(issues.router)
    app.include_router(notifications.router)
    app.include_router(ws.router)
    app.include_router(settings_router.router)

    app.mount("/static", StaticFiles(directory="frontend"), name="static")

    @app.get("/")
    async def serve_index():
        return FileResponse("frontend/index.html")

    return app
