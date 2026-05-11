from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class ChatwootClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "api_access_token": self.settings.chatwoot_api_access_token,
        }

    def _account_url(self, path: str) -> str:
        return (
            f"{self.settings.chatwoot_base_url}/api/v1/accounts/"
            f"{self.settings.chatwoot_account_id}{path}"
        )

    async def create_private_note(self, *, conversation_id: int, content: str) -> dict[str, Any]:
        url = self._account_url(f"/conversations/{conversation_id}/messages")
        payload = {
            "content": content,
            "message_type": "outgoing",
            "private": True,
            "content_type": "text",
            "content_attributes": {},
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, headers=self._headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def update_conversation_attributes(
        self, *, conversation_id: int, attributes: dict[str, Any]
    ) -> dict[str, Any]:
        url = self._account_url(f"/conversations/{conversation_id}/custom_attributes")
        payload = {"custom_attributes": attributes}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, headers=self._headers, json=payload)
            response.raise_for_status()
            return response.json()

