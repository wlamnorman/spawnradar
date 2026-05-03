"""Prometheus metrics export endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from app.dependencies import get_metrics_service
from app.metrics.service import MetricsService

router = APIRouter()


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(
    metrics_service: MetricsService = Depends(get_metrics_service),
) -> PlainTextResponse:
    """Expose durable business metrics in Prometheus text format."""
    return PlainTextResponse(
        metrics_service.render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
