# Chatwoot Odoo Bridge

FastAPI service that receives Chatwoot webhooks and serves an embedded Chatwoot
Dashboard App for looking up customer data in Odoo 17.

It also serves a Chatwoot Dashboard App at `/dashboard`, so agents can view and
search Odoo data inside the Chatwoot conversation screen.

The first production path is read-only toward Odoo:

- Find `res.partner` by name, email, normalized phone, or Odoo partner ID.
- Show the matched contact and related company/child contacts.
- Search contacts manually by name, email, or phone.
- Show related `crm.lead` records.
- Split `sale.order` records into Quotations and confirmed Sales Orders.
- Show complete commercial fields and every returned sales order line, including
  quantities delivered/invoiced, discounts, taxes, totals, salesperson, sales
  team, addresses, payment terms, and linked invoices.
- Show customer invoices from `account.move`, their complete business fields,
  and every returned invoice line.
- Show a separate Invoiced Items view that links each product/service to its
  invoice, due date, payment state, origin, and salesperson.
- Show related journal entries from customer `account.move.line` records and
  their `account.move` entry.
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

RESTRICTED_DASHBOARD_SECTIONS=
SENSITIVE_DATA_ALLOWED_AGENT_EMAILS=
SENSITIVE_DATA_ALLOWED_AGENT_IDS=
SENSITIVE_DATA_ALLOWED_AGENT_DOMAINS=

ODOO_URL=https://engosoft.com
ODOO_DB=...
ODOO_USERNAME=api-user@example.com
ODOO_PASSWORD=...
MAX_LEADS=20
MAX_ORDERS=20
MAX_INVOICES=20
MAX_JOURNAL_ENTRIES=20
MAX_COURSES=20
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
- Auto-search Odoo using the contact name, email, and phone.
- Let agents manually search by name, email, or phone.
- Show Customer Profile, CRM, Quotations, Sales Orders, Invoiced Items, Invoices,
  Courses, Journal, and Related Contacts tabs.
- Show Odoo custom fields (`x_*`) when they are readable scalar or many2one
  fields.
- Show the contact salesperson, sales order salesperson, and invoice salesperson.
- Show every section to every signed-in Chatwoot agent.
- Show a Diagnostics panel with the partner search scope and optional-model
  warnings.
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
odoo_related_contacts_count
odoo_leads_count
odoo_courses_count
odoo_last_course
odoo_last_course_completion
```

Sensitive commercial attributes are only updated when
`CHATWOOT_UPDATE_SENSITIVE_ATTRIBUTES=true`:

```text
odoo_orders_count
odoo_quotations_count
odoo_sales_orders_count
odoo_last_order
odoo_last_order_state
odoo_last_order_total
odoo_last_order_salesperson
odoo_invoices_count
odoo_invoiced_items_count
odoo_last_invoice
odoo_last_invoice_payment_state
odoo_last_invoice_due
odoo_last_invoice_salesperson
odoo_journal_entries_count
odoo_last_journal_entry
odoo_last_journal_entry_date
odoo_last_journal
```

## Dashboard Access

All Odoo sections are visible to every agent who can open the Chatwoot Dashboard
App. Keep the legacy restriction variable empty on Railway:

```env
RESTRICTED_DASHBOARD_SECTIONS=
```

The old agent email/ID/domain allow-lists no longer hide dashboard sections.
Keep `DASHBOARD_APP_TOKEN` private because it protects the embedded app URL.
`CHATWOOT_UPDATE_SENSITIVE_ATTRIBUTES` only controls webhook custom-attribute
updates; it does not hide dashboard data.

## How Odoo records are matched

The bridge resolves the Chatwoot contact to a `res.partner` using name, email,
normalized phone, or partner ID. From that partner it builds a **search scope**:

```text
scope = [matched_partner_id, commercial_partner_id]
```

Contacts, CRM, sales orders, invoices, journal items, event registrations, and
course lines are queried against this hierarchy. Where fields are available, the
bridge also checks commercial partner, invoice address, and shipping address
links. This catches records booked on a parent company or sibling contact.

Journal entries are resolved through `account.move.line.partner_id`, then joined
to `account.move` records where `move_type=entry`. General entries often carry the
customer on journal items rather than on the move header.

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
    "journal_entries_included": true,
    "agent_email_present": true
  }
}
```

The dashboard surfaces the same information in a **Diagnostics** panel, including
any optional-model warnings (for example when the Odoo user cannot read
`account.move`).

## Troubleshooting: Customer data is empty

Work through these in order. The Diagnostics panel and the backend logs tell you
which case you are in.

1. **Check the matched contact.** Review `debug.scope_partner_ids`. If
   `commercial_partner_id` is missing, search manually by name, email, phone, or
   Odoo partner ID and select the correct match.

2. **Check phone formatting.** The bridge normalizes international/Egyptian
   variants and searches short suffixes, so numbers containing spaces,
   parentheses, or country prefixes can still be matched and scored locally.

3. **A warning is shown.** Optional models (`account.move`, `account.move.line`,
   `slide.channel.partner`,
   `event.registration`) never fail silently — if the Odoo API user lacks read
   access the Diagnostics panel and the `warnings` array say which model and why.
   Grant that model read access to the Odoo API user.

## Odoo access

Create a dedicated Odoo user with read access to:

- Contacts
- CRM
- Sales
- Invoicing / Accounting
- Journal Entries / Journal Items
- eLearning / Website Slides

Use that user in `.env`. Keep write permissions off until we add create/update flows.

Invoices, journal entries, and courses are optional reads. If the Odoo user lacks
access or the eLearning module is not installed, the dashboard still renders the
rest of the customer snapshot and marks optional data as unavailable.

## Docker

```powershell
Copy-Item .env.example .env
docker compose up --build -d
```

## Tests

```powershell
pytest
```
