"""Snapshot-level tests for the Odoo client.

These use a network-isolated ``FakeOdoo`` subclass that overrides the low-level
read methods, so we can assert *which Odoo domains* the client builds without a
live Odoo server. The key regression being guarded: sales orders and invoices
that are booked on the **commercial (parent) partner** must still be found when
the Chatwoot email/phone only matches a child contact.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.services.odoo import (
    OdooClient,
    commercial_partner_id,
    partner_scope_ids,
)

# A child contact (id=10) whose commercial parent is the company (id=7).
CHILD_PARTNER: dict[str, Any] = {
    "id": 10,
    "name": "حسين الياس خليفه أحمد",
    "email": "hussein@example.com",
    "phone": "+201001234567",
    "mobile": False,
    "company_name": False,
    "commercial_partner_id": [7, "Engosoft Company"],
    "user_id": [3, "Sales Rep"],
}

# The order/invoice are booked on the commercial parent (7), NOT the child (10).
COMMERCIAL_ID = 7

_MODEL_FIELDS = {
    "res.partner": ["phone_sanitized"],
    "event.registration": ["id", "partner_id", "event_id", "name", "state"],
    "sale.order.line": ["id", "order_id", "product_id", "name", "display_type", "event_id"],
    "account.move.line": [
        "id",
        "move_id",
        "product_id",
        "name",
        "display_type",
        "date",
        "partner_id",
        "account_id",
        "debit",
        "credit",
        "balance",
        "currency_id",
    ],
}


def _child_of_targets(domain: list[Any], field: str = "partner_id") -> list[int]:
    """Return the id list used by a ``child_of`` leaf on ``field`` (or []).."""
    for clause in domain:
        if (
            isinstance(clause, (list, tuple))
            and len(clause) == 3
            and clause[0] == field
            and clause[1] == "child_of"
        ):
            ids = clause[2]
            return [ids] if isinstance(ids, int) else list(ids)
    return []


def _has_leaf(domain: list[Any], field: str, operator: str, value: Any) -> bool:
    return any(
        isinstance(clause, (list, tuple))
        and len(clause) == 3
        and clause[0] == field
        and clause[1] == operator
        and clause[2] == value
        for clause in domain
    )


class FakeOdoo(OdooClient):
    """An OdooClient that answers reads from in-memory fixtures."""

    def __init__(self, settings: Settings, partner: dict[str, Any]):
        super().__init__(settings)
        self.partner = partner
        self.calls: list[tuple[str, list[Any]]] = []

    # Never authenticate against a real server.
    @property
    def uid(self) -> int:  # type: ignore[override]
        return 1

    def model_fields(self, model: str) -> dict[str, Any]:
        return {name: {"string": name} for name in _MODEL_FIELDS.get(model, [])}

    def read_records(self, model: str, ids, fields):  # noqa: ANN001
        if model == "res.partner" and self.partner["id"] in ids:
            return [self.partner]
        return []

    def search_read(self, model, domain, fields, *, limit, order=None):  # noqa: ANN001
        self.calls.append((model, domain))

        if model == "res.partner":
            return [self.partner]

        if model == "sale.order":
            if COMMERCIAL_ID in _child_of_targets(domain):
                return [
                    {
                        "id": 555,
                        "name": "S14794",
                        "state": "sale",
                        "date_order": "2026-01-10",
                        "amount_total": 18000,
                        "currency_id": [74, "EGP"],
                        "invoice_status": "invoiced",
                        "partner_id": [COMMERCIAL_ID, "Engosoft Company"],
                        "user_id": [3, "Sales Rep"],
                    }
                ]
            return []

        if model == "account.move":
            if COMMERCIAL_ID in _child_of_targets(domain):
                return [
                    {
                        "id": 999,
                        "name": "INV/2026/0001",
                        "move_type": "out_invoice",
                        "state": "posted",
                        "invoice_date": "2026-01-12",
                        "invoice_date_due": "2026-01-26",
                        "amount_total": 18000,
                        "amount_residual": 0,
                        "currency_id": [74, "EGP"],
                        "payment_state": "paid",
                        "invoice_origin": "S14794",
                        "invoice_user_id": [3, "Sales Rep"],
                        "partner_id": [COMMERCIAL_ID, "Engosoft Company"],
                    }
                ]
            return []

        # crm.lead, sale.order.line, account.move.line, slide.channel.partner,
        # event.registration -> no extra rows for these tests.
        return []


class JournalEntryOdoo(FakeOdoo):
    def search_read(self, model, domain, fields, *, limit, order=None):  # noqa: ANN001
        if model == "account.move.line" and _has_leaf(
            domain, "move_id.move_type", "=", "entry"
        ):
            self.calls.append((model, domain))
            return [
                {
                    "id": 801,
                    "move_id": [777, "MISC/2026/0042"],
                    "date": "2026-02-01",
                    "name": "Customer adjustment",
                    "partner_id": [COMMERCIAL_ID, "Engosoft Company"],
                    "account_id": [1210, "Accounts Receivable"],
                    "debit": 250,
                    "credit": 0,
                    "balance": 250,
                    "currency_id": [74, "EGP"],
                }
            ]

        if model == "account.move" and _has_leaf(domain, "id", "in", [777]):
            self.calls.append((model, domain))
            return [
                {
                    "id": 777,
                    "name": "MISC/2026/0042",
                    "ref": "Customer adjustment",
                    "date": "2026-02-01",
                    "state": "posted",
                    "move_type": "entry",
                    "journal_id": [9, "Miscellaneous Operations"],
                    "currency_id": [74, "EGP"],
                }
            ]

        return super().search_read(model, domain, fields, limit=limit, order=order)


def _settings() -> Settings:
    return Settings.from_env()


def test_partner_scope_ids_includes_commercial_parent():
    assert partner_scope_ids(CHILD_PARTNER) == [10, 7]
    assert commercial_partner_id(CHILD_PARTNER) == 7


def test_partner_scope_ids_dedupes_when_partner_is_its_own_commercial():
    partner = {"id": 7, "commercial_partner_id": [7, "Engosoft Company"]}

    assert partner_scope_ids(partner) == [7]


def test_partner_scope_ids_handles_missing_commercial_partner():
    assert partner_scope_ids({"id": 10}) == [10]
    assert partner_scope_ids(None) == []


def test_sales_orders_found_through_commercial_partner():
    client = FakeOdoo(_settings(), CHILD_PARTNER)

    snapshot = client.customer_snapshot(
        email="hussein@example.com",
        phone=None,
        include_orders=True,
        include_invoices=True,
    )

    assert snapshot["partner"]["id"] == 10
    assert snapshot["debug"]["commercial_partner_id"] == 7
    assert snapshot["debug"]["scope_partner_ids"] == [10, 7]

    # The order is booked on the commercial parent (7) yet is still returned.
    assert [order["name"] for order in snapshot["orders"]] == ["S14794"]

    sale_domains = [domain for model, domain in client.calls if model == "sale.order"]
    assert sale_domains, "sale.order was never queried"
    assert all(COMMERCIAL_ID in _child_of_targets(domain) for domain in sale_domains)


def test_invoices_found_through_commercial_partner():
    client = FakeOdoo(_settings(), CHILD_PARTNER)

    snapshot = client.customer_snapshot(
        email="hussein@example.com",
        phone=None,
        include_orders=True,
        include_invoices=True,
    )

    assert [invoice["name"] for invoice in snapshot["invoices"]] == ["INV/2026/0001"]
    assert snapshot["invoices"][0]["payment_state"] == "paid"

    move_domains = [domain for model, domain in client.calls if model == "account.move"]
    assert move_domains, "account.move was never queried"
    assert all(COMMERCIAL_ID in _child_of_targets(domain) for domain in move_domains)


def test_crm_search_uses_commercial_partner_hierarchy():
    client = FakeOdoo(_settings(), CHILD_PARTNER)

    client.customer_snapshot(email="hussein@example.com", phone=None)

    lead_domains = [domain for model, domain in client.calls if model == "crm.lead"]
    assert lead_domains
    assert COMMERCIAL_ID in _child_of_targets(lead_domains[0])


def test_journal_entries_are_found_from_customer_account_move_lines():
    client = JournalEntryOdoo(_settings(), CHILD_PARTNER)

    snapshot = client.customer_snapshot(email="hussein@example.com", phone=None)

    assert [entry["name"] for entry in snapshot["journal_entries"]] == [
        "MISC/2026/0042"
    ]
    assert snapshot["journal_entries"][0]["partner_debit"] == 250
    journal_line_domains = [
        domain
        for model, domain in client.calls
        if model == "account.move.line"
        and _has_leaf(domain, "move_id.move_type", "=", "entry")
    ]
    assert journal_line_domains
    assert COMMERCIAL_ID in _child_of_targets(journal_line_domains[0])


def test_orders_and_invoices_empty_when_restricted_but_courses_still_resolve():
    client = FakeOdoo(_settings(), CHILD_PARTNER)

    snapshot = client.customer_snapshot(
        email="hussein@example.com",
        phone=None,
        include_orders=False,
        include_invoices=False,
    )

    # The sensitive sections expose no order/invoice records to a normal agent.
    assert snapshot["orders"] == []
    assert snapshot["invoices"] == []
    assert snapshot["debug"]["orders_included"] is False
    assert snapshot["debug"]["invoices_included"] is False
