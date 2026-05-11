from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.services.chatwoot import ChatwootClient
from app.services.formatter import format_customer_note
from app.services.odoo import OdooClient


def verify_dashboard_access(
    *,
    request: Request,
    token: str | None,
    settings: Settings,
) -> None:
    expected_token = settings.dashboard_app_token
    if not expected_token:
        return

    header_token = request.headers.get("X-Dashboard-App-Token")
    if token == expected_token or header_token == expected_token:
        return

    raise HTTPException(status_code=401, detail="Invalid dashboard app token")


async def fetch_dashboard_snapshot(
    *,
    settings: Settings,
    query: str | None,
    email: str | None,
    phone: str | None,
    partner_id: int | None,
) -> dict[str, Any]:
    return await run_in_threadpool(
        OdooClient(settings).customer_snapshot,
        email=email,
        phone=phone,
        query=query,
        partner_id=partner_id,
    )


async def create_snapshot_note(
    *,
    settings: Settings,
    conversation_id: int,
    query: str | None,
    email: str | None,
    phone: str | None,
    partner_id: int | None,
) -> dict[str, Any]:
    snapshot = await fetch_dashboard_snapshot(
        settings=settings,
        query=query,
        email=email,
        phone=phone,
        partner_id=partner_id,
    )
    note = format_customer_note(snapshot, lookup_email=email, lookup_phone=phone)
    await ChatwootClient(settings).create_private_note(
        conversation_id=conversation_id,
        content=note,
    )
    return {"status": "created", "conversation_id": conversation_id}
