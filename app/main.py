from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.security import verify_chatwoot_signature
from app.services.state import StateStore
from app.services.sync import process_chatwoot_webhook

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(title="Chatwoot Odoo Bridge", version="0.1.0")


@app.get("/health")
def health() -> dict[str, object]:
    missing = get_settings().missing_required()
    return {"ok": not missing, "missing": missing}


@app.post("/webhooks/chatwoot")
async def chatwoot_webhook(
    request: Request,
    x_chatwoot_signature: Annotated[str | None, Header(alias="X-Chatwoot-Signature")] = None,
    x_chatwoot_timestamp: Annotated[str | None, Header(alias="X-Chatwoot-Timestamp")] = None,
    x_chatwoot_delivery: Annotated[str | None, Header(alias="X-Chatwoot-Delivery")] = None,
) -> JSONResponse:
    current_settings = get_settings()
    missing = current_settings.missing_required()
    if missing:
        raise HTTPException(status_code=503, detail={"missing": missing})

    raw_body = await request.body()
    if not current_settings.allow_unsigned_webhooks:
        valid_signature = verify_chatwoot_signature(
            raw_body=raw_body,
            timestamp=x_chatwoot_timestamp,
            received_signature=x_chatwoot_signature,
            secret=current_settings.chatwoot_webhook_secret,
            tolerance_seconds=current_settings.webhook_tolerance_seconds,
        )
        if not valid_signature:
            raise HTTPException(status_code=401, detail="Invalid Chatwoot signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    state = StateStore(current_settings.app_state_db_path)
    if not state.mark_delivery_once(x_chatwoot_delivery):
        return JSONResponse({"status": "ignored", "reason": "duplicate_delivery"})

    result = await process_chatwoot_webhook(
        payload=payload,
        settings=current_settings,
        state=state,
    )
    return JSONResponse(result)

