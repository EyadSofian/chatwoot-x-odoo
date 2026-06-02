# Chatwoot Odoo Bridge

FastAPI service that receives Chatwoot webhooks and serves an embedded Chatwoot
Dashboard App for looking up customer data in Odoo 17.

It also serves a Chatwoot Dashboard App at `/dashboard`, so agents can view and
search Odoo data inside the Chatwoot conversation screen.

The first production path is read-only toward Odoo:

- Find `res.partner` by email or phone.
- Search contacts manually by name, email, or phone.
- Show related `crm.lead` records.
- Show recent `sale.order` records and their lines.
- Show recent customer invoices from `account.move` and invoice lines.
- Show eLearning course memberships from `slide.channel.partner`, including
  progress percentage and next lesson.
- Show course/event registrations from `event.registration` and course-like sales
  order lines when courses are sold as event products.
- Optionally update Chatwoot conversation custom attributes for filtering.
- Optionally add the current Odoo snapshot to the conversation as a private note.

## Architecture

```text
Chatwoot webhook
    -> FastAPI bridge
    -> Odoo XML-RPC
    -> Chatwoot Application API private note

Chatwoot Dashboard App iframe
    -> /dashboard
    -> /api/dashboard/search
    -> Odoo XML-RPC
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
CHATWOOT_AUTO_PRIVATE_NOTES=false
CHATWOOT_UPDATE_SENSITIVE_ATTRIBUTES=false
DASHBOARD_APP_TOKEN=choose-a-long-random-token

RESTRICTED_DASHBOARD_SECTIONS=orders,invoices
SENSITIVE_DATA_ALLOWED_AGENT_EMAILS=manager@example.com,finance@example.com
SENSITIVE_DATA_ALLOWED_AGENT_IDS=
SENSITIVE_DATA_ALLOWED_AGENT_DOMAINS=

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

Automatic private notes are disabled by default. Keep this setting off if agents
should only create notes manually from the dashboard button:

```env
CHATWOOT_AUTO_PRIVATE_NOTES=false
```

## Chatwoot Dashboard App

In Chatwoot:

1. Go to Settings -> Integrations -> Dashboard apps.
2. Add a dashboard app named `Odoo`.
3. Use this URL:

```text
https://your-bridge-domain.com/dashboard?token=YOUR_DASHBOARD_APP_TOKEN
```

The dashboard app will:

- Receive the current conversation context from Chatwoot.
- Auto-search Odoo using the contact email or phone.
- Let agents manually search by name, email, or phone.
- Show contact, CRM, sales order, invoice, and course tabs.
- Hide restricted tabs such as orders and invoices unless the current Chatwoot
  agent is on the allow-list.
- Support Auto, Light, and Dark themes.
- Add a private note to the conversation when the agent clicks `Add private note`.

## Sensitive Data Access

By default, the dashboard hides `orders` and `invoices` for every agent:

```env
RESTRICTED_DASHBOARD_SECTIONS=orders,invoices
```

Grant access by adding Chatwoot agent emails, IDs, or whole domains:

```env
SENSITIVE_DATA_ALLOWED_AGENT_EMAILS=manager@example.com,finance@example.com
SENSITIVE_DATA_ALLOWED_AGENT_IDS=12,42
SENSITIVE_DATA_ALLOWED_AGENT_DOMAINS=engosoft.com
```

The dashboard receives the current agent from Chatwoot's `currentAgent` payload.
This is enough for normal internal use, but keep `DASHBOARD_APP_TOKEN` private
because anyone with the token can open the embedded app URL.

## Odoo access

Create a dedicated Odoo user with read access to:

- Contacts
- CRM
- Sales
- Invoicing / Accounting
- eLearning / Website Slides

Use that user in `.env`. Keep write permissions off until we add create/update flows.

Invoices and courses are optional reads. If the Odoo user lacks access or the eLearning
module is not installed, the dashboard still renders the rest of the customer snapshot
and marks optional data as unavailable.

## Docker

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

## Tests

```powershell
pytest
```
