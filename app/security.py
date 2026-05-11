from __future__ import annotations

import hashlib
import hmac
import time


def verify_chatwoot_signature(
    *,
    raw_body: bytes,
    timestamp: str | None,
    received_signature: str | None,
    secret: str,
    tolerance_seconds: int = 300,
) -> bool:
    if not timestamp or not received_signature or not secret:
        return False

    try:
        timestamp_int = int(timestamp)
    except ValueError:
        return False

    if tolerance_seconds > 0 and abs(int(time.time()) - timestamp_int) > tolerance_seconds:
        return False

    message = f"{timestamp}.".encode("utf-8") + raw_body
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), message, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, received_signature)

