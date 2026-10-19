import asyncio

import httpx

from isee.app import create_app
from isee.config import Settings


def test_health_endpoint_reports_application_status() -> None:
    async def request_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(Settings()))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json() == {"service": "iSeeYou", "status": "ok"}
