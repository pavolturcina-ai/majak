"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from majak.api.routers import routers
from majak.db import dispose_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await dispose_engine()


app = FastAPI(
    title="MAJÁK API",
    version="0.1.0",
    description="Personal CEO assistant — daily evaluation, lifecycle, people & dossiers.",
    lifespan=lifespan,
)

# The Phase-1 HTML frontend is a thin client on the same origin or localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in routers:
    app.include_router(r, prefix="/api")


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok", "service": "majak"}
