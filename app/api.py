"""FastAPI entrypoint for the NIRA Browser Service."""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.agent import browse

app = FastAPI(title="NIRA Browser Service")


@app.get("/")
def root():
    return {"status": "ok", "service": "NIRA Browser"}


@app.head("/")
def root_head():
    # UptimeRobot probes `HEAD /`; FastAPI does not auto-derive HEAD here,
    # so respond 200 with no body to keep the monitor green.
    return


_allowed = os.getenv("BROWSER_CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BrowseRequest(BaseModel):
    task: str
    url: str | None = None
    max_steps: int = 6


@app.get("/health")
def health():
    return {"status": "ok", "backend": os.getenv("BROWSER_BACKEND", "fetch")}


@app.post("/browse")
def do_browse(req: BrowseRequest) -> dict:
    return browse(req.task, req.url, req.max_steps)
