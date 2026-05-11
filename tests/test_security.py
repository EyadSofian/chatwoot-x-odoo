import hashlib
import hmac
import time

from app.security import verify_chatwoot_signature


def test_verify_chatwoot_signature_accepts_valid_signature():
    secret = "top-secret"
    timestamp = str(int(time.time()))
    raw_body = b'{"event":"message_created"}'
    signature = "sha256=" + hmac.new(
        secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256
    ).hexdigest()

    assert verify_chatwoot_signature(
        raw_body=raw_body,
        timestamp=timestamp,
        received_signature=signature,
        secret=secret,
    )


def test_verify_chatwoot_signature_rejects_invalid_signature():
    assert not verify_chatwoot_signature(
        raw_body=b"{}",
        timestamp=str(int(time.time())),
        received_signature="sha256=wrong",
        secret="top-secret",
    )

