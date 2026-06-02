import pytest

from app.services.sync import process_chatwoot_webhook


class DummySettings:
    chatwoot_sync_on_message_created = False
    chatwoot_auto_private_notes = False
    chatwoot_update_attributes = False
    chatwoot_update_sensitive_attributes = False
    sync_ttl_seconds = 1800


class DummyState:
    def __init__(self):
        self.synced = []

    def should_sync_conversation(self, conversation_id, ttl_seconds):
        return True

    def mark_conversation_synced(self, conversation_id):
        self.synced.append(conversation_id)


class FailingChatwootClient:
    def __init__(self, settings):
        self.settings = settings

    async def create_private_note(self, *, conversation_id, content):
        raise AssertionError("Private notes should not be created automatically")


@pytest.mark.anyio
async def test_webhook_does_not_create_auto_private_note_when_disabled(monkeypatch):
    monkeypatch.setattr("app.services.sync.ChatwootClient", FailingChatwootClient)

    state = DummyState()
    result = await process_chatwoot_webhook(
        payload={"event": "conversation_created", "id": 42},
        settings=DummySettings(),
        state=state,
    )

    assert result["status"] == "synced"
    assert result["note_created"] is False
    assert state.synced == [42]
