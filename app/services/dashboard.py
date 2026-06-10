from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.services.chatwoot import ChatwootClient
from app.services.formatter import format_customer_note
from app.services.odoo import OdooClient
from app.services.permissions import AgentContext, restricted_sections_for

logger = logging.getLogger(__name__)


def _log_restriction(agent: AgentContext, restricted_sections: list[str]) -> None:
    """Explain in the backend logs why sensitive sections are hidden."""
    if not restricted_sections:
        return
    if not agent.normalized_email:
        logger.warning(
            "Dashboard sections %s locked: Chatwoot did not send the current agent email "
            "(agent_id=%r, agent_name=%r). The Dashboard App context must include "
            "currentAgent.email, then add that email to SENSITIVE_DATA_ALLOWED_AGENT_EMAILS.",
            restricted_sections,
            agent.normalized_id or None,
            agent.name or None,
        )
    else:
        logger.info(
            "Dashboard sections %s locked for agent %s: not in "
            "SENSITIVE_DATA_ALLOWED_AGENT_EMAILS/_IDS/_DOMAINS.",
            restricted_sections,
            agent.normalized_email,
        )


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
    agent_email: str | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
) -> dict[str, Any]:
    agent = AgentContext(email=agent_email, agent_id=agent_id, name=agent_name)
    restricted_sections = restricted_sections_for(agent, settings)
    _log_restriction(agent, restricted_sections)
    snapshot = await run_in_threadpool(
        OdooClient(settings).customer_snapshot,
        email=email,
        phone=phone,
        query=query,
        partner_id=partner_id,
        include_orders="orders" not in restricted_sections,
        include_invoices="invoices" not in restricted_sections,
        include_journal_entries=True,
    )
    snapshot["restricted_sections"] = restricted_sections
    snapshot["agent"] = {
        "email": agent.normalized_email,
        "id": agent.normalized_id,
        "name": agent.name or "",
    }
    debug = snapshot.setdefault("debug", {})
    debug["agent_email_present"] = bool(agent.normalized_email)
    debug["restricted_sections"] = restricted_sections
    return snapshot


async def create_snapshot_note(
    *,
    settings: Settings,
    conversation_id: int,
    query: str | None,
    email: str | None,
    phone: str | None,
    partner_id: int | None,
    agent_email: str | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
) -> dict[str, Any]:
    snapshot = await fetch_dashboard_snapshot(
        settings=settings,
        query=query,
        email=email,
        phone=phone,
        partner_id=partner_id,
        agent_email=agent_email,
        agent_id=agent_id,
        agent_name=agent_name,
    )
    note = format_customer_note(snapshot, lookup_email=email, lookup_phone=phone)
    await ChatwootClient(settings).create_private_note(
        conversation_id=conversation_id,
        content=note,
    )
    return {"status": "created", "conversation_id": conversation_id}
