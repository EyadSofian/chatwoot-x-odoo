from app.services.payloads import extract_chatwoot_context, should_process_event


def test_extracts_message_payload_context():
    payload = {
        "event": "message_created",
        "message_type": "incoming",
        "conversation": {"id": 77, "account_id": 1},
        "contact": {
            "id": 10,
            "name": "Alice",
            "email": "alice@example.com",
            "phone_number": "+201001112223",
        },
    }

    context = extract_chatwoot_context(payload)

    assert context.conversation_id == 77
    assert context.account_id == 1
    assert context.contact_id == 10
    assert context.email == "alice@example.com"
    assert context.phone == "+201001112223"
    assert should_process_event(context, sync_on_message_created=True)


def test_ignores_outgoing_messages():
    context = extract_chatwoot_context(
        {"event": "message_created", "message_type": "outgoing", "conversation": {"id": 1}}
    )

    assert not should_process_event(context, sync_on_message_created=True)


def test_processes_conversation_created():
    context = extract_chatwoot_context({"event": "conversation_created", "id": 55})

    assert context.conversation_id == 55
    assert should_process_event(context, sync_on_message_created=False)

