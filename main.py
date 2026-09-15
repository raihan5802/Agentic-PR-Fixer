"""FastAPI application launcher for AutoPatch-Agent."""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

# Ensure `src` is on the import path when running directly
SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from autopatch_agent.api.routes import router  # noqa: E402
from autopatch_agent.config import get_settings  # noqa: E402
from autopatch_agent.graph import get_compiled_graph, shutdown_checkpointer  # noqa: E402


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _configure_logging(settings.log_level)
    Path("data").mkdir(exist_ok=True)
    app.state.graph = get_compiled_graph()
    yield
    shutdown_checkpointer()


def create_app() -> FastAPI:
    app = FastAPI(
        title="AutoPatch-Agent",
        description="Agentic workflow orchestrator for automated PR fixes",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(router, prefix="/api/v1")
    return app


app = create_app()


def run() -> None:
    load_dotenv()
    settings = get_settings()
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=not settings.is_production,
    )


if __name__ == "__main__":
    run()
