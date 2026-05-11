from __future__ import annotations

import logging
import re
import xmlrpc.client
from functools import cached_property
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)


def _digits(value: str | None) -> str:
    return re.sub(r"\D+", "", value or "")


def _or_domain(clauses: list[list[Any]]) -> list[Any]:
    if not clauses:
        return []
    if len(clauses) == 1:
        return clauses[0]
    return ["|"] * (len(clauses) - 1) + clauses


PARTNER_FIELDS = [
    "id",
    "name",
    "email",
    "phone",
    "mobile",
    "company_name",
    "commercial_partner_id",
    "vat",
    "city",
    "country_id",
    "customer_rank",
]


class OdooClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @cached_property
    def uid(self) -> int:
        common = xmlrpc.client.ServerProxy(
            f"{self.settings.odoo_url}/xmlrpc/2/common", allow_none=True
        )
        uid = common.authenticate(
            self.settings.odoo_db,
            self.settings.odoo_username,
            self.settings.odoo_password,
            {},
        )
        if not uid:
            raise RuntimeError("Odoo authentication failed")
        return int(uid)

    def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        models = xmlrpc.client.ServerProxy(
            f"{self.settings.odoo_url}/xmlrpc/2/object", allow_none=True
        )
        params: list[Any] = [
            self.settings.odoo_db,
            self.uid,
            self.settings.odoo_password,
            model,
            method,
            args or [],
        ]
        if kwargs is not None:
            params.append(kwargs)
        return models.execute_kw(*params)

    def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str],
        *,
        limit: int,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"fields": fields, "limit": limit}
        if order:
            kwargs["order"] = order
        return self.execute_kw(model, "search_read", [domain], kwargs)

    def read_records(
        self,
        model: str,
        ids: list[int],
        fields: list[str],
    ) -> list[dict[str, Any]]:
        if not ids:
            return []
        return self.execute_kw(model, "read", [ids], {"fields": fields})

    def _partner_search_domain(
        self,
        *,
        query: str | None = None,
        email: str | None = None,
        phone: str | None = None,
    ) -> list[Any]:
        clauses: list[list[Any]] = []
        query = (query or "").strip()

        if query:
            clauses.append(["name", "ilike", query])
            clauses.append(["email", "ilike", query])
            clauses.append(["phone", "ilike", query])
            clauses.append(["mobile", "ilike", query])

            query_digits = _digits(query)
            if query_digits:
                phone_token = query_digits[-9:] if len(query_digits) >= 9 else query_digits
                clauses.append(["phone", "ilike", phone_token])
                clauses.append(["mobile", "ilike", phone_token])

        if email:
            clauses.append(["email", "=ilike", email])

        phone_digits = _digits(phone)
        if phone_digits:
            phone_token = phone_digits[-9:] if len(phone_digits) >= 9 else phone_digits
            clauses.append(["phone", "ilike", phone_token])
            clauses.append(["mobile", "ilike", phone_token])

        return _or_domain(clauses)

    def search_partners(
        self,
        *,
        query: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        domain = self._partner_search_domain(query=query, email=email, phone=phone)
        if not domain:
            return []

        return self.search_read(
            "res.partner",
            domain,
            PARTNER_FIELDS,
            limit=limit,
            order="write_date desc",
        )

    def find_partner(self, *, email: str | None, phone: str | None) -> dict[str, Any] | None:
        partners = self.search_partners(email=email, phone=phone, limit=1)
        return partners[0] if partners else None

    def get_partner(self, partner_id: int) -> dict[str, Any] | None:
        partners = self.read_records("res.partner", [partner_id], PARTNER_FIELDS)
        return partners[0] if partners else None

    def get_leads(
        self,
        *,
        partner_id: int | None,
        email: str | None,
        phone: str | None,
    ) -> list[dict[str, Any]]:
        clauses: list[list[Any]] = []
        if partner_id:
            clauses.append(["partner_id", "=", partner_id])
        if email:
            clauses.append(["email_from", "=ilike", email])

        phone_digits = _digits(phone)
        if phone_digits:
            phone_token = phone_digits[-9:] if len(phone_digits) >= 9 else phone_digits
            clauses.append(["phone", "ilike", phone_token])
            clauses.append(["mobile", "ilike", phone_token])

        if not clauses:
            return []

        return self.search_read(
            "crm.lead",
            _or_domain(clauses),
            [
                "id",
                "name",
                "type",
                "stage_id",
                "expected_revenue",
                "probability",
                "email_from",
                "phone",
                "mobile",
                "create_date",
                "date_deadline",
                "user_id",
                "team_id",
            ],
            limit=self.settings.max_leads,
            order="write_date desc",
        )

    def get_sale_orders(self, *, partner_id: int | None) -> list[dict[str, Any]]:
        if not partner_id:
            return []

        orders = self.search_read(
            "sale.order",
            [["partner_id", "child_of", partner_id]],
            [
                "id",
                "name",
                "state",
                "date_order",
                "amount_total",
                "currency_id",
                "invoice_status",
                "partner_id",
                "user_id",
            ],
            limit=self.settings.max_orders,
            order="date_order desc",
        )
        if not orders:
            return []

        order_ids = [order["id"] for order in orders]
        lines = self.search_read(
            "sale.order.line",
            [["order_id", "in", order_ids]],
            [
                "order_id",
                "product_id",
                "product_uom_qty",
                "price_unit",
                "price_subtotal",
            ],
            limit=self.settings.max_orders * 10,
            order="id asc",
        )
        lines_by_order: dict[int, list[dict[str, Any]]] = {}
        for line in lines:
            order_ref = line.get("order_id")
            if isinstance(order_ref, list | tuple) and order_ref:
                lines_by_order.setdefault(int(order_ref[0]), []).append(line)

        for order in orders:
            order["lines"] = lines_by_order.get(int(order["id"]), [])
        return orders

    def customer_snapshot(
        self,
        *,
        email: str | None,
        phone: str | None,
        query: str | None = None,
        partner_id: int | None = None,
    ) -> dict[str, Any]:
        if partner_id:
            partner = self.get_partner(partner_id)
            matches = [partner] if partner else []
        elif query:
            matches = self.search_partners(query=query, email=email, phone=phone, limit=10)
            partner = matches[0] if matches else None
        else:
            matches = self.search_partners(email=email, phone=phone, limit=10)
            partner = matches[0] if matches else None

        partner_id = int(partner["id"]) if partner else None

        lookup_email = email or (partner or {}).get("email")
        lookup_phone = phone or (partner or {}).get("phone") or (partner or {}).get("mobile")
        leads = self.get_leads(partner_id=partner_id, email=lookup_email, phone=lookup_phone)
        orders = self.get_sale_orders(partner_id=partner_id)

        logger.info(
            "Odoo snapshot loaded partner=%s leads=%s orders=%s",
            partner_id,
            len(leads),
            len(orders),
        )
        return {"partner": partner, "matches": matches, "leads": leads, "orders": orders}
