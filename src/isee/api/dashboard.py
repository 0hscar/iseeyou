from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from isee_network.storage import SQLiteStore

router = APIRouter()
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


class RouterOverview(BaseModel):
    status: Literal["unknown", "available", "unavailable", "stale"]
    sampled_at: str | None
    uptime: str | None
    cpu_load_percent: int | None
    free_memory_bytes: int | None
    total_memory_bytes: int | None


class InterfaceOverview(BaseModel):
    name: str
    type: str
    comment: str | None
    running: bool | None
    monitored: bool
    sampled_at: str | None
    rates_sampled_at: str | None
    freshness: Literal["unknown", "fresh", "stale"]
    rate_valid: bool
    rate_reason: str | None
    rx_bits_per_second: float | None
    tx_bits_per_second: float | None
    rx_bytes: int | None
    tx_bytes: int | None


class ConnectedDevice(BaseModel):
    mac_address: str
    interface_name: str
    bridge_name: str | None
    vlan_id: int | None
    bridge_age: str | None
    host_name: str | None
    dhcp_server: str | None
    ip_addresses: list[str]


class ConnectedDevicesResponse(BaseModel):
    status: Literal["unknown", "fresh", "stale"]
    sampled_at: str | None
    devices: list[ConnectedDevice]


class ConnectivityOverview(BaseModel):
    name: str
    host: str
    port: int
    sampled_at: str
    status: Literal["unknown", "reachable", "degraded", "unreachable", "stale"]
    probes_sent: int
    probes_succeeded: int
    probe_failure_percent: float
    latency_ms: float | None


class OutageWindow(BaseModel):
    target_name: str
    started_at: str
    ended_at: str | None
    ongoing: bool
    duration_seconds: float


class OverviewResponse(BaseModel):
    generated_at: str
    collector_status: str
    collector_last_success_at: str | None
    router: RouterOverview
    interfaces: list[InterfaceOverview]
    connectivity: list[ConnectivityOverview]
    recent_outages: list[OutageWindow]


class InterfaceHistoryPoint(BaseModel):
    sampled_at: str
    rate_valid: bool
    rx_bits_per_second: float | None
    tx_bits_per_second: float | None


class InterfaceHistoryResponse(BaseModel):
    name: str
    hours: int
    points: list[InterfaceHistoryPoint]


class ConnectivityHistoryPoint(BaseModel):
    sampled_at: str
    latency_ms: float | None
    probe_failure_percent: float


class ConnectivityHistoryResponse(BaseModel):
    name: str
    hours: int
    points: list[ConnectivityHistoryPoint]


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def overview_page(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="overview.html",
        context={"page": "overview", "title": "Overview"},
    )


@router.get("/interfaces", response_class=HTMLResponse, include_in_schema=False)
def interfaces_page(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="interfaces.html",
        context={"page": "interfaces", "title": "Interfaces"},
    )


@router.get("/connectivity", response_class=HTMLResponse, include_in_schema=False)
def connectivity_page(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="connectivity.html",
        context={"page": "connectivity", "title": "Connectivity"},
    )


@router.get("/devices", response_class=HTMLResponse, include_in_schema=False)
def devices_page(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request=request,
        name="devices.html",
        context={"page": "devices", "title": "Devices"},
    )


@router.get(
    "/api/network/overview",
    response_model=OverviewResponse,
    tags=["network"],
)
def network_overview(request: Request) -> OverviewResponse:
    now = datetime.now(timezone.utc)
    store = _store(request)
    interval = request.app.state.settings.collection.interval_seconds
    latest_run = store.latest_collection_run()
    interface_rows = store.latest_interface_records()
    connectivity_rows = store.latest_connectivity_records()
    collector_health = request.app.state.collector_health

    if latest_run is None:
        router = RouterOverview(
            status="unknown",
            sampled_at=None,
            uptime=None,
            cpu_load_percent=None,
            free_memory_bytes=None,
            total_memory_bytes=None,
        )
    else:
        sampled_at = latest_run["router_sampled_at"] or latest_run["completed_at"]
        age = _age_seconds(sampled_at, now)
        if latest_run["router_status"] != "ok":
            router_status = "unavailable"
        elif age > interval * 3:
            router_status = "stale"
        else:
            router_status = "available"
        router = RouterOverview(
            status=router_status,
            sampled_at=sampled_at,
            uptime=latest_run["uptime"],
            cpu_load_percent=latest_run["cpu_load_percent"],
            free_memory_bytes=latest_run["free_memory_bytes"],
            total_memory_bytes=latest_run["total_memory_bytes"],
        )

    interfaces = [
        _interface_overview(row, now, interval)
        for row in interface_rows
    ]
    connectivity = [
        _connectivity_overview(row, now, interval)
        for row in connectivity_rows
    ]
    since = (now - timedelta(hours=24)).isoformat(timespec="milliseconds")
    recent_outages: list[OutageWindow] = []
    for target in connectivity_rows:
        samples = store.connectivity_samples_since(target["target_name"], since, 20_000)
        recent_outages.extend(
            _derive_outages(target["target_name"], samples, interval, now)
        )
    recent_outages.sort(key=lambda outage: outage.started_at, reverse=True)

    return OverviewResponse(
        generated_at=now.isoformat(timespec="milliseconds"),
        collector_status=collector_health.status,
        collector_last_success_at=collector_health.last_success_at,
        router=router,
        interfaces=interfaces,
        connectivity=connectivity,
        recent_outages=recent_outages[:10],
    )


@router.get(
    "/api/network/interfaces",
    response_model=list[InterfaceOverview],
    tags=["network"],
)
def list_interfaces(request: Request) -> list[InterfaceOverview]:
    now = datetime.now(timezone.utc)
    interval = request.app.state.settings.collection.interval_seconds
    return [
        _interface_overview(row, now, interval)
        for row in _store(request).latest_interface_records()
    ]


@router.get(
    "/api/network/devices",
    response_model=ConnectedDevicesResponse,
    tags=["network"],
)
def list_connected_devices(request: Request) -> ConnectedDevicesResponse:
    now = datetime.now(timezone.utc)
    interval = request.app.state.settings.collection.interval_seconds
    inventory = _store(request).latest_connected_devices()
    sampled_at = inventory["sampled_at"]
    status = _freshness(sampled_at, now, interval)
    return ConnectedDevicesResponse(
        status=status,
        sampled_at=sampled_at,
        devices=[
            ConnectedDevice(**device)
            for device in inventory["devices"]
        ],
    )


@router.get(
    "/api/network/interfaces/history",
    response_model=InterfaceHistoryResponse,
    tags=["network"],
)
def interface_history(
    request: Request,
    name: str = Query(min_length=1, max_length=128),
    hours: int = Query(default=24, ge=1, le=168),
) -> InterfaceHistoryResponse:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    bucket_seconds = max(1, ceil(hours * 3600 / 1000))
    rows = _store(request).interface_history(
        name,
        since.isoformat(timespec="milliseconds"),
        bucket_seconds,
    )
    return InterfaceHistoryResponse(
        name=name,
        hours=hours,
        points=[
            InterfaceHistoryPoint(
                sampled_at=row["sampled_at"],
                rate_valid=bool(row["rate_valid"]),
                rx_bits_per_second=row["rx_bits_per_second"],
                tx_bits_per_second=row["tx_bits_per_second"],
            )
            for row in rows
        ],
    )


@router.get(
    "/api/network/connectivity",
    response_model=list[ConnectivityOverview],
    tags=["network"],
)
def list_connectivity(request: Request) -> list[ConnectivityOverview]:
    now = datetime.now(timezone.utc)
    interval = request.app.state.settings.collection.interval_seconds
    return [
        _connectivity_overview(row, now, interval)
        for row in _store(request).latest_connectivity_records()
    ]


@router.get(
    "/api/network/connectivity/history",
    response_model=ConnectivityHistoryResponse,
    tags=["network"],
)
def connectivity_history(
    request: Request,
    name: str = Query(min_length=1, max_length=128),
    hours: int = Query(default=24, ge=1, le=168),
) -> ConnectivityHistoryResponse:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    bucket_seconds = max(1, ceil(hours * 3600 / 1000))
    rows = _store(request).connectivity_history(
        name,
        since.isoformat(timespec="milliseconds"),
        bucket_seconds,
    )
    return ConnectivityHistoryResponse(
        name=name,
        hours=hours,
        points=[
            ConnectivityHistoryPoint(
                sampled_at=row["sampled_at"],
                latency_ms=row["latency_ms"],
                probe_failure_percent=row["probe_failure_percent"],
            )
            for row in rows
        ],
    )


@router.get(
    "/api/network/connectivity/outages",
    response_model=list[OutageWindow],
    tags=["network"],
)
def connectivity_outages(
    request: Request,
    name: str = Query(min_length=1, max_length=128),
    hours: int = Query(default=24, ge=1, le=168),
) -> list[OutageWindow]:
    now = datetime.now(timezone.utc)
    interval = request.app.state.settings.collection.interval_seconds
    since = (now - timedelta(hours=hours)).isoformat(timespec="milliseconds")
    samples = _store(request).connectivity_samples_since(name, since, 200_000)
    outages = _derive_outages(name, samples, interval, now)
    return outages[-50:][::-1]


def _store(request: Request) -> SQLiteStore:
    store = request.app.state.store
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Dashboard storage is not initialized; application lifespan is not active",
        )
    return store


def _interface_overview(
    row: dict,
    now: datetime,
    interval_seconds: int,
) -> InterfaceOverview:
    rates_sampled_at = row["rates_sampled_at"]
    monitored = rates_sampled_at is not None
    freshness = _freshness(rates_sampled_at, now, interval_seconds)
    return InterfaceOverview(
        name=row["interface_name"],
        type=row["interface_type"],
        comment=row["comment"],
        running=None if row["running"] is None else bool(row["running"]),
        monitored=monitored,
        sampled_at=row["router_sampled_at"],
        rates_sampled_at=rates_sampled_at,
        freshness=freshness,
        rate_valid=bool(row["rate_valid"]) if monitored else False,
        rate_reason=row["rate_reason"],
        rx_bits_per_second=row["rx_bits_per_second"],
        tx_bits_per_second=row["tx_bits_per_second"],
        rx_bytes=row["rx_bytes"],
        tx_bytes=row["tx_bytes"],
    )


def _connectivity_overview(
    row: dict,
    now: datetime,
    interval_seconds: int,
) -> ConnectivityOverview:
    sampled_at = row["sampled_at"]
    if _freshness(sampled_at, now, interval_seconds) == "stale":
        status = "stale"
    elif row["probes_succeeded"] == 0:
        status = "unreachable"
    elif row["probe_failure_percent"] > 0:
        status = "degraded"
    else:
        status = "reachable"
    return ConnectivityOverview(
        name=row["target_name"],
        host=row["target_host"],
        port=row["target_port"],
        sampled_at=sampled_at,
        status=status,
        probes_sent=row["probes_sent"],
        probes_succeeded=row["probes_succeeded"],
        probe_failure_percent=row["probe_failure_percent"],
        latency_ms=row["latency_ms"],
    )


def _freshness(
    sampled_at: str | None,
    now: datetime,
    interval_seconds: int,
) -> Literal["unknown", "fresh", "stale"]:
    if sampled_at is None:
        return "unknown"
    return "stale" if _age_seconds(sampled_at, now) > interval_seconds * 3 else "fresh"


def _age_seconds(sampled_at: str, now: datetime) -> float:
    return (now - datetime.fromisoformat(sampled_at)).total_seconds()


def _derive_outages(
    target_name: str,
    samples: list[dict],
    interval_seconds: int,
    now: datetime,
) -> list[OutageWindow]:
    outages: list[OutageWindow] = []
    started_at: datetime | None = None
    last_failed_at: datetime | None = None
    maximum_gap = interval_seconds * 3

    for sample in samples:
        sampled_at = datetime.fromisoformat(sample["sampled_at"])
        if (
            started_at is not None
            and last_failed_at is not None
            and (sampled_at - last_failed_at).total_seconds() > maximum_gap
        ):
            outages.append(
                _outage(target_name, started_at, last_failed_at, now, ongoing=False)
            )
            started_at = None
            last_failed_at = None

        if sample["probes_succeeded"] == 0:
            if started_at is None:
                started_at = sampled_at
            last_failed_at = sampled_at
        elif started_at is not None:
            outages.append(
                _outage(target_name, started_at, sampled_at, now, ongoing=False)
            )
            started_at = None
            last_failed_at = None

    if started_at is not None:
        outages.append(_outage(target_name, started_at, None, now, ongoing=True))
    return outages


def _outage(
    target_name: str,
    started_at: datetime,
    ended_at: datetime | None,
    now: datetime,
    *,
    ongoing: bool,
) -> OutageWindow:
    endpoint = ended_at or now
    return OutageWindow(
        target_name=target_name,
        started_at=started_at.isoformat(timespec="milliseconds"),
        ended_at=ended_at.isoformat(timespec="milliseconds") if ended_at else None,
        ongoing=ongoing,
        duration_seconds=max(0, (endpoint - started_at).total_seconds()),
    )
