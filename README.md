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
- Show course-like invoice lines when the course is only visible through customer
  invoices.
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
- Show the contact salesperson, sales order salesperson, and invoice salesperson.
- Hide restricted tabs such as orders and invoices unless the current Chatwoot
  agent is on the allow-list.
- Show a Diagnostics panel with the detected agent email, the partner search
  scope, and any optional-model warnings when something is locked or missing.
- Support Auto, Light, and Dark themes.
- Add a private note to the conversation when the agent clicks `Add private note`.

## Chatwoot Custom Attributes

The dashboard works without custom attributes. Add these conversation custom
attributes in Chatwoot only if you want to filter conversations or show Odoo
status in Chatwoot lists:

```text
odoo_match_found
odoo_partner_id
odoo_partner_name
odoo_partner_salesperson
odoo_leads_count
odoo_courses_count
odoo_last_course
odoo_last_course_completion
```

Sensitive commercial attributes are only updated when
`CHATWOOT_UPDATE_SENSITIVE_ATTRIBUTES=true`:

```text
odoo_orders_count
odoo_last_order
odoo_last_order_state
odoo_last_order_total
odoo_last_order_salesperson
odoo_invoices_count
odoo_last_invoice
odoo_last_invoice_payment_state
odoo_last_invoice_due
odoo_last_invoice_salesperson
```

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

## How Odoo records are matched

The bridge first resolves the Chatwoot contact to a single `res.partner`
(by email, then by normalized phone, then by manual search). From that partner it
builds a **search scope**:

```text
scope = [matched_partner_id, commercial_partner_id]
```

Sales orders, invoices, event registrations, and course lines are then queried
with `["partner_id", "child_of", scope]`. `child_of` matches the partner *and its
descendants*, so including the `commercial_partner_id` (the top of the Odoo
company/contact tree) means we also catch records booked on the parent company or
on sibling contacts — the common case where an order such as `S14794` is booked on
the commercial partner while Chatwoot only knows a child contact's email/phone.

`/api/dashboard/search` returns a `debug` block so you can see exactly what was
searched:

```json
{
  "debug": {
    "partner_id": 10,
    "commercial_partner_id": 7,
    "scope_partner_ids": [10, 7],
    "orders_included": true,
    "invoices_included": true,
    "agent_email_present": true
  }
}
```

The dashboard surfaces the same information in a **Diagnostics** panel, including
any optional-model warnings (for example when the Odoo user cannot read
`account.move`).

## Troubleshooting: Sales Orders / Invoices are empty

Work through these in order. The Diagnostics panel and the backend logs tell you
which case you are in.

1. **Sections are locked (most common).** If the panel says *"Sensitive sections
   locked"* or *"Chatwoot did not send the current agent email"*, the records were
   never fetched. Orders and invoices are only fetched for allow-listed agents:

   ```env
   RESTRICTED_DASHBOARD_SECTIONS=orders,invoices
   SENSITIVE_DATA_ALLOWED_AGENT_EMAILS=eyad.sofiane@engosoft.com,mohamed.assem@engosoft.com
   ```

   - If the panel shows a detected agent email, add that exact email to
     `SENSITIVE_DATA_ALLOWED_AGENT_EMAILS` on Railway and redeploy.
   - If the panel shows *no* agent email, Chatwoot did not include
     `currentAgent.email` in the Dashboard App context. Open the app from inside a
     conversation while signed in as an agent. As a fallback you may allow a whole
     domain with `SENSITIVE_DATA_ALLOWED_AGENT_DOMAINS=engosoft.com`, but the email
     still has to be delivered for the allow-list to match.

2. **The agent is allowed but records are still empty.** Check the `debug`
   `scope_partner_ids`. If `commercial_partner_id` is missing, the matched contact
   may be the wrong record — search manually by name to pick the correct partner.
   The bridge already searches `partner_id`, `commercial_partner_id`, and
   `child_of`, so a truly linked order/invoice will appear.

3. **A warning is shown.** Optional models (`account.move`, `slide.channel.partner`,
   `event.registration`) never fail silently — if the Odoo API user lacks read
   access the Diagnostics panel and the `warnings` array say which model and why.
   Grant that model read access to the Odoo API user.

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
