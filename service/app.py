"""HTTP service: Higgsfield Marketing Studio assets + daily token refresh."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from service.hf import (
    HiggsfieldError,
    account_status,
    list_avatars,
    list_products,
    refresh_auth,
)

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("higgsfield-service")

scheduler = AsyncIOScheduler()
_last_refresh: dict[str, Any] | None = None


def _api_key_ok(header_value: str | None) -> bool:
    expected = os.getenv("SERVICE_API_KEY", "").strip()
    if not expected:
        return True  # open in local/dev unless configured
    return header_value == expected


async def scheduled_refresh() -> None:
    global _last_refresh
    try:
        result = refresh_auth()
        _last_refresh = {
            **result,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "trigger": "cron",
        }
        log.info("Scheduled auth refresh OK expires_at=%s", result.get("expires_at"))
    except Exception:
        log.exception("Scheduled auth refresh failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _last_refresh
    # Boot refresh so the process starts warm.
    try:
        result = refresh_auth()
        _last_refresh = {
            **result,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "trigger": "startup",
        }
        log.info("Startup auth refresh OK")
    except Exception:
        log.exception("Startup auth refresh failed — endpoints may error until fixed")

    # Default: once daily at 06:00 UTC (override with REFRESH_CRON="0 6 * * *")
    cron = os.getenv("REFRESH_CRON", "0 6 * * *").split()
    if len(cron) != 5:
        raise RuntimeError("REFRESH_CRON must have 5 fields (min hour dom mon dow)")
    minute, hour, day, month, dow = cron
    scheduler.add_job(
        scheduled_refresh,
        CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=dow,
            timezone="UTC",
        ),
        id="higgsfield-auth-refresh",
        replace_existing=True,
    )
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Higgsfield Marketing Studio Bridge",
    version="0.1.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def api_key_middleware(request, call_next):
    if request.url.path in {"/health", "/docs", "/openapi.json", "/redoc"}:
        return await call_next(request)
    key = request.headers.get("x-api-key")
    if not _api_key_ok(key):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "last_refresh": _last_refresh,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/auth/refresh")
def auth_refresh() -> dict[str, Any]:
    global _last_refresh
    try:
        result = refresh_auth()
    except HiggsfieldError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _last_refresh = {
        **result,
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "trigger": "manual",
    }
    return _last_refresh


@app.get("/account")
def get_account() -> dict[str, Any]:
    try:
        return account_status()
    except HiggsfieldError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/avatars")
def get_avatars(
    size: int = Query(100, ge=1, le=200),
    custom_only: bool = Query(False, description="Only workspace-created avatars"),
) -> dict[str, Any]:
    try:
        items = list_avatars(size=size, custom_only=custom_only)
    except HiggsfieldError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"count": len(items), "items": items}


@app.get("/products")
def get_products(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    try:
        items = list_products(limit=limit)
    except HiggsfieldError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"count": len(items), "items": items}
