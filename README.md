# Chatwoot Odoo Bridge

FastAPI service that receives Chatwoot webhooks, looks up the customer in Odoo 17,
then writes an Odoo summary back to the Chatwoot conversation as a private note.

The first production path is read-only toward Odoo:

- Find `res.partner` by email or phone.
- Show related `crm.lead` records.
- Show recent `sale.order` records and their lines.
- Optionally update Chatwoot conversation custom attributes for filtering.

## Architecture

```text
Chatwoot webhook
    -> FastAPI bridge
    -> Odoo XML-RPC
    -> Chatwoot Application API private note
```

Why this shape:

- Odoo 17 exposes model access through XML-RPC `execute_kw`.
- Chatwoot can send signed webhooks and accepts private notes through the
  Application API.
- The bridge keeps credentials out of both systems and gives us logging,
  deduplication, retries later, and one place for business rules.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Edit `.env`:

```env
CHATWOOT_BASE_URL=https://chat.example.com
CHATWOOT_ACCOUNT_ID=1
CHATWOOT_API_ACCESS_TOKEN=...
CHATWOOT_WEBHOOK_SECRET=...

ODOO_URL=https://engosoft.com
ODOO_DB=...
ODOO_USERNAME=api-user@example.com
ODOO_PASSWORD=...
```

Run locally:

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

## Chatwoot configuration

In Chatwoot:

1. Go to Settings -> Integrations -> Webhooks.
2. Add webhook URL:

```text
https://your-bridge-domain.com/webhooks/chatwoot
```

3. Subscribe to:

```text
conversation_created
message_created
```

`message_created` is ignored by default unless `CHATWOOT_SYNC_ON_MESSAGE_CREATED=true`.

## Odoo access

Create a dedicated Odoo user with read access to:

- Contacts
- CRM
- Sales

Use that user in `.env`. Keep write permissions off until we add create/update flows.

## Docker

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

## Tests

```powershell
pytest
```

