"""Thin REST helper: the load generator only needs to create meetings."""

from __future__ import annotations

import httpx


async def create_meeting(http: httpx.AsyncClient, title: str) -> str:
    response = await http.post("/api/meetings", json={"title": title})
    response.raise_for_status()
    return response.json()["id"]
