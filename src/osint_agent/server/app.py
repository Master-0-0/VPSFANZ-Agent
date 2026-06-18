import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .dependencies import init_store, close_store
from .routes import router
from .events import bus


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_store()
    yield
    close_store()
    bus.cleanup_project("")


app = FastAPI(lifespan=lifespan, title="osint-agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(router)
