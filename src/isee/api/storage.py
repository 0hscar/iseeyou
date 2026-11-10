from __future__ import annotations

import gzip
import io
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from isee_network.storage import SQLiteStore

router = APIRouter()
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))
PROTECTED_DAYS = 30


class StorageMonth(BaseModel):
    month: str
    runs: int
    interface_samples: int
    interface_inventory: int
    connectivity_samples: int
    estimated_payload_bytes: int


class StorageUsageResponse(BaseModel):
    database_bytes: int
    protected_before: date
    months: list[StorageMonth]


class DeleteHistoryRequest(BaseModel):
    before: date
    confirmation: Literal["DELETE"]


class DeleteHistoryResponse(BaseModel):
    deleted_runs: int
    deleted_interface_samples: int
    deleted_interface_inventory: int
    deleted_connectivity_samples: int
    database_bytes_before: int
    database_bytes_after: int


@router.get("/storage", include_in_schema=False)
def storage_page(request: Request):
    return TEMPLATES.TemplateResponse(
        request=request,
        name="storage.html",
        context={"page": "storage", "title": "Storage"},
    )


@router.get(
    "/api/storage/usage",
    response_model=StorageUsageResponse,
    tags=["storage"],
)
def storage_usage(request: Request) -> StorageUsageResponse:
    usage = _store(request).monthly_storage_usage()
    protected_before = datetime.now(timezone.utc) - timedelta(days=PROTECTED_DAYS)
    return StorageUsageResponse(
        database_bytes=usage["database_bytes"],
        protected_before=protected_before.date(),
        months=[StorageMonth(**month) for month in usage["months"]],
    )


@router.get("/api/storage/export", tags=["storage"])
def export_storage(
    request: Request,
    from_date: date = Query(alias="from"),
    through: date = Query(),
) -> StreamingResponse:
    if from_date > through:
        raise HTTPException(status_code=422, detail="'from' must not be after 'through'")
    if through == date.max:
        raise HTTPException(status_code=422, detail="'through' date is out of range")

    start = datetime.combine(from_date, datetime.min.time(), timezone.utc)
    end_exclusive = datetime.combine(
        through + timedelta(days=1),
        datetime.min.time(),
        timezone.utc,
    )
    store = _store(request)
    filename = f"iseeyou-{from_date.isoformat()}-to-{through.isoformat()}.jsonl.gz"
    return StreamingResponse(
        _compressed_jsonl(store, start, end_exclusive),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/api/storage/delete",
    response_model=DeleteHistoryResponse,
    tags=["storage"],
)
def delete_storage_history(
    request: Request,
    body: DeleteHistoryRequest,
) -> DeleteHistoryResponse:
    cutoff = datetime.combine(body.before, datetime.min.time(), timezone.utc)
    try:
        result = _store(request).delete_history_before(
            cutoff,
            protected_days=PROTECTED_DAYS,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return DeleteHistoryResponse(
        deleted_runs=result["collection_runs"],
        deleted_interface_samples=result["interface_samples"],
        deleted_interface_inventory=result["interface_inventory"],
        deleted_connectivity_samples=result["connectivity_samples"],
        database_bytes_before=result["database_bytes_before"],
        database_bytes_after=result["database_bytes_after"],
    )


def _store(request: Request) -> SQLiteStore:
    store = request.app.state.store
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Dashboard storage is not initialized; application lifespan is not active",
        )
    return store


def _compressed_jsonl(
    store: SQLiteStore,
    start: datetime,
    end_exclusive: datetime,
) -> Iterator[bytes]:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as compressed:
        for record in store.iter_export_records(start, end_exclusive):
            compressed.write(
                (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                .encode("utf-8")
            )
            if buffer.tell() >= 64 * 1024:
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate()
    if buffer.tell():
        yield buffer.getvalue()
