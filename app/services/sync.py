from __future__ import annotations

import logging
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.services.chatwoot import ChatwootClient
from app.services.formatter import conversation_attributes, format_customer_note
from app.services.odoo import OdooClient
from app.services.payloads import extract_chatwoot_context, should_process_event
from app.services.state import StateStore

logger = logging.getLogger(__name__)


async def process_chatwoot_webhook(
    *,
    payload: dict[str, Any],
    settings: Settings,
    state: StateStore,
) -> dict[str, Any]:
    context = extract_chatwoot_context(payload)

    if not should_process_event(
        context, sync_on_message_created=settings.chatwoot_sync_on_message_created
    ):
        return {"status": "ignored", "event": context.event}

    if not context.conversation_id:
        return {"status": "ignored", "reason": "missing_conversation_id"}

    if not state.should_sync_conversation(context.conversation_id, settings.sync_ttl_seconds):
        return {"status": "ignored", "reason": "recently_synced"}

    chatwoot = ChatwootClient(settings)

    if not context.email and not context.phone:
        if settings.chatwoot_auto_private_notes:
            note = format_customer_note({}, lookup_email=context.email, lookup_phone=context.phone)
            await chatwoot.create_private_note(
                conversation_id=context.conversation_id,
                content=note,
            )
        state.mark_conversation_synced(context.conversation_id)
        return {
            "status": "synced",
            "match_found": False,
            "reason": "missing_lookup_key",
            "note_created": settings.chatwoot_auto_private_notes,
        }

    snapshot = await run_in_threadpool(
        OdooClient(settings).customer_snapshot,
        email=context.email,
        phone=context.phone,
        include_orders=settings.chatwoot_update_sensitive_attributes,
        include_invoices=settings.chatwoot_update_sensitive_attributes,
    )

    note_created = False
    if settings.chatwoot_auto_private_notes:
        note = format_customer_note(snapshot, lookup_email=context.email, lookup_phone=context.phone)
        await chatwoot.create_private_note(conversation_id=context.conversation_id, content=note)
        note_created = True

    attributes_updated = False
    if settings.chatwoot_update_attributes:
        try:
            await chatwoot.update_conversation_attributes(
                conversation_id=context.conversation_id,
                attributes=conversation_attributes(
                    snapshot,
                    include_sensitive=settings.chatwoot_update_sensitive_attributes,
                ),
            )
            attributes_updated = True
        except Exception:
            logger.exception("Failed to update Chatwoot custom attributes")

    state.mark_conversation_synced(context.conversation_id)
    return {
        "status": "synced",
        "event": context.event,
        "conversation_id": context.conversation_id,
        "match_found": bool(snapshot.get("partner")),
        "note_created": note_created,
        "attributes_updated": attributes_updated,
    }
