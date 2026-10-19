from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class HealthResponse(BaseModel):
    service: str
    status: Literal["ok"]


class CollectorHealthResponse(BaseModel):
    status: Literal["not_configured", "starting", "collecting", "ok", "error"]
    last_attempt_at: str | None
    last_success_at: str | None
    last_error: str | None


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health_check() -> HealthResponse:
    return HealthResponse(service="iSeeYou", status="ok")


@router.get("/health/collector", response_model=CollectorHealthResponse, tags=["health"])
def collector_health(request: Request) -> CollectorHealthResponse:
    health = request.app.state.collector_health
    return CollectorHealthResponse(
        status=health.status,
        last_attempt_at=health.last_attempt_at,
        last_success_at=health.last_success_at,
        last_error=health.last_error,
    )
