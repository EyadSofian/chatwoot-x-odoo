from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChatwootContext:
    event: str
    conversation_id: int | None
    account_id: int | None
    contact_id: int | None
    contact_name: str | None
    email: str | None
    phone: str | None
    message_type: str | int | None
    private: bool


def _nested(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_chatwoot_context(payload: dict[str, Any]) -> ChatwootContext:
    event = str(payload.get("event") or "")
    conversation = payload.get("conversation") or payload.get("current_conversation") or {}
    meta_sender = _nested(conversation, "meta", "sender") or {}

    sender = payload.get("sender") or {}
    contact = payload.get("contact") or {}
    if not contact and str(sender.get("type", "")).lower() == "contact":
        contact = sender
    if not contact and meta_sender:
        contact = meta_sender

    account_id = _as_int(
        _first(_nested(payload, "account", "id"), payload.get("account_id"), conversation.get("account_id"))
    )

    conversation_id = _as_int(
        _first(conversation.get("id"), payload.get("conversation_id"), conversation.get("display_id"))
    )
    if not conversation_id and event.startswith("conversation_"):
        conversation_id = _as_int(payload.get("id"))

    contact_id = _as_int(_first(contact.get("id"), payload.get("contact_id")))
    email = _first(contact.get("email"), sender.get("email"), payload.get("email"))
    phone = _first(
        contact.get("phone_number"),
        contact.get("phone"),
        contact.get("mobile"),
        sender.get("phone_number"),
        payload.get("phone_number"),
        payload.get("phone"),
    )

    return ChatwootContext(
        event=event,
        conversation_id=conversation_id,
        account_id=account_id,
        contact_id=contact_id,
        contact_name=_first(contact.get("name"), sender.get("name")),
        email=email,
        phone=phone,
        message_type=payload.get("message_type"),
        private=bool(payload.get("private", False)),
    )


def should_process_event(context: ChatwootContext, *, sync_on_message_created: bool) -> bool:
    if context.event == "conversation_created":
        return True

    if context.event != "message_created" or not sync_on_message_created:
        return False

    if context.private:
        return False

    message_type = context.message_type
    if isinstance(message_type, str):
        return message_type.lower() == "incoming"

    return message_type == 0

