from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.security import verify_chatwoot_signature
from app.services.dashboard import (
    create_snapshot_note,
    fetch_dashboard_snapshot,
    verify_dashboard_access,
)
from app.services.state import StateStore
from app.services.sync import process_chatwoot_webhook

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(title="Chatwoot Odoo Bridge", version="0.1.0")
APP_DIR = Path(__file__).resolve().parent
app.mount(
    "/dashboard/assets",
    StaticFiles(directory=APP_DIR / "dashboard" / "assets"),
    name="dashboard-assets",
)


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Chatwoot Odoo Bridge</title>
        <style>
          body {
            margin: 0;
            background: #f7f8fa;
            color: #111827;
            font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
              "Segoe UI", sans-serif;
          }
          main {
            max-width: 760px;
            margin: 0 auto;
            padding: 48px 20px;
          }
          section {
            border: 1px solid #d8dee8;
            border-radius: 8px;
            background: #ffffff;
            padding: 22px;
            box-shadow: 0 12px 34px rgba(15, 23, 42, 0.08);
          }
          h1 {
            margin: 0 0 8px;
            font-size: 24px;
          }
          p {
            margin: 0 0 18px;
            color: #64748b;
          }
          a {
            color: #0f7eea;
            font-weight: 700;
            text-decoration: none;
          }
          code {
            display: block;
            margin: 10px 0;
            overflow-wrap: anywhere;
            border-radius: 8px;
            background: #f2f5f8;
            padding: 10px;
          }
        </style>
      </head>
      <body>
        <main>
          <section>
            <h1>Chatwoot Odoo Bridge</h1>
            <p>The service is running. Use these paths in Chatwoot:</p>
            <code>/dashboard?token=YOUR_DASHBOARD_APP_TOKEN</code>
            <code>/webhooks/chatwoot</code>
            <p><a href="/health">Open health check</a></p>
          </section>
        </main>
      </body>
    </html>
    """
    return HTMLResponse(html)


@app.get("/health")
def health() -> dict[str, object]:
    missing = get_settings().missing_required()
    return {"ok": not missing, "missing": missing}


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_app(
    request: Request,
    token: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    verify_dashboard_access(request=request, token=token, settings=get_settings())
    html = (APP_DIR / "dashboard" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/api/dashboard/search")
async def dashboard_search(
    request: Request,
    token: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    email: Annotated[str | None, Query(max_length=200)] = None,
    phone: Annotated[str | None, Query(max_length=80)] = None,
    partner_id: Annotated[int | None, Query()] = None,
) -> dict[str, object]:
    current_settings = get_settings()
    verify_dashboard_access(request=request, token=token, settings=current_settings)

    if not any([q, email, phone, partner_id]):
        return {"partner": None, "matches": [], "leads": [], "orders": []}

    missing = [
        name
        for name in ["ODOO_URL", "ODOO_DB", "ODOO_USERNAME", "ODOO_PASSWORD"]
        if name in current_settings.missing_required()
    ]
    if missing:
        raise HTTPException(status_code=503, detail={"missing": missing})

    return await fetch_dashboard_snapshot(
        settings=current_settings,
        query=q,
        email=email,
        phone=phone,
        partner_id=partner_id,
    )


@app.post("/api/dashboard/conversations/{conversation_id}/note")
async def dashboard_create_note(
    conversation_id: int,
    request: Request,
    token: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    current_settings = get_settings()
    verify_dashboard_access(request=request, token=token, settings=current_settings)

    missing = current_settings.missing_required()
    if missing:
        raise HTTPException(status_code=503, detail={"missing": missing})

    payload = await request.json()
    return await create_snapshot_note(
        settings=current_settings,
        conversation_id=conversation_id,
        query=payload.get("query"),
        email=payload.get("email"),
        phone=payload.get("phone"),
        partner_id=payload.get("partner_id"),
    )


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
