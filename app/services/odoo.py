from __future__ import annotations

import logging
import re
import xmlrpc.client
from functools import cached_property
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)
COURSE_KEYWORDS = (
    "course",
    "event",
    "training",
    "workshop",
    "online",
    "كورس",
    "دورة",
    "برنامج",
    "تدريب",
)


def _digits(value: str | None) -> str:
    return re.sub(r"\D+", "", value or "")


def _or_domain(clauses: list[list[Any]]) -> list[Any]:
    if not clauses:
        return []
    if len(clauses) == 1:
        return clauses[0]
    return ["|"] * (len(clauses) - 1) + clauses


PARTNER_BASE_FIELDS = [
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
    "user_id",
]
OPTIONAL_PARTNER_FIELDS = ["phone_sanitized"]


def _phone_tokens(value: str | None) -> list[str]:
    digits = _digits(value)
    if not digits:
        return []

    tokens = {digits}
    if digits.startswith("00") and len(digits) > 4:
        tokens.add(digits[2:])

    normalized = digits[2:] if digits.startswith("00") else digits
    if normalized.startswith("20") and len(normalized) >= 11:
        tokens.add(normalized[2:])
        tokens.add(f"0{normalized[2:]}")
    elif normalized.startswith("0") and len(normalized) >= 10:
        tokens.add(normalized[1:])
        tokens.add(f"20{normalized[1:]}")

    for length in (11, 10, 9, 8):
        if len(normalized) >= length:
            tokens.add(normalized[-length:])

    return sorted((token for token in tokens if len(token) >= 7), key=len, reverse=True)


def _phone_match_score(lookup_values: list[str], partner_values: list[str]) -> int:
    lookup_tokens = {token for value in lookup_values for token in _phone_tokens(value)}
    partner_tokens = {token for value in partner_values for token in _phone_tokens(value)}
    if not lookup_tokens or not partner_tokens:
        return 0

    if lookup_tokens & partner_tokens:
        return 120

    for lookup in lookup_tokens:
        for partner in partner_tokens:
            if len(lookup) >= 10 and len(partner) >= 10 and (
                lookup.endswith(partner[-10:]) or partner.endswith(lookup[-10:])
            ):
                return 100
            if len(lookup) >= 9 and len(partner) >= 9 and (
                lookup.endswith(partner[-9:]) or partner.endswith(lookup[-9:])
            ):
                return 80

    return 0


def _looks_like_course_line(value: str | None) -> bool:
    text = str(value or "").lower()
    return any(keyword in text for keyword in COURSE_KEYWORDS)


def _record_name(value: Any) -> str:
    if isinstance(value, list | tuple) and len(value) >= 2:
        return str(value[1])
    if value in (False, None, ""):
        return ""
    return str(value)


def _course_identity(course: dict[str, Any]) -> str:
    name = _record_name(course.get("channel_id")) or str(course.get("description") or "")
    source = str(course.get("source") or "")
    if source in {"sale_order_line", "invoice_line"}:
        source = "commercial_line"
    return f"{source}:{name.strip().lower()}"


class OdooClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model_fields_cache: dict[str, dict[str, Any]] = {}

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

    @cached_property
    def partner_fields(self) -> list[str]:
        available = self.model_fields("res.partner")
        if not available:
            return PARTNER_BASE_FIELDS

        fields = list(PARTNER_BASE_FIELDS)
        fields.extend(field for field in OPTIONAL_PARTNER_FIELDS if field in available)
        return fields

    def model_fields(self, model: str) -> dict[str, Any]:
        if model in self._model_fields_cache:
            return self._model_fields_cache[model]

        try:
            available = self.execute_kw(
                model,
                "fields_get",
                [],
                {"attributes": ["string"]},
            )
        except xmlrpc.client.Fault:
            logger.warning("Could not inspect Odoo model fields for %s", model, exc_info=True)
            available = {}

        self._model_fields_cache[model] = available
        return available

    def optional_search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str],
        *,
        limit: int,
        order: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        try:
            return self.search_read(model, domain, fields, limit=limit, order=order), None
        except xmlrpc.client.Fault as exc:
            logger.warning("Optional Odoo model %s could not be read: %s", model, exc)
            fault_lines = exc.faultString.splitlines()
            fault_summary = fault_lines[-1] if fault_lines else str(exc)
            return [], f"{model}: {fault_summary}"

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
            if not _digits(query):
                clauses.append(["name", "ilike", query])
                clauses.append(["email", "ilike", query])

            for phone_token in _phone_tokens(query)[:4]:
                for field in ["phone", "mobile", "phone_sanitized"]:
                    if field in self.partner_fields:
                        clauses.append([field, "ilike", phone_token])

        if email:
            clauses.append(["email", "=ilike", email])

        for phone_token in _phone_tokens(phone)[:4]:
            for field in ["phone", "mobile", "phone_sanitized"]:
                if field in self.partner_fields:
                    clauses.append([field, "ilike", phone_token])

        return _or_domain(clauses)

    def _score_partner(
        self,
        partner: dict[str, Any],
        *,
        query: str | None,
        email: str | None,
        phone: str | None,
    ) -> int:
        score = 0
        partner_email = str(partner.get("email") or "").strip().lower()
        lookup_email = str(email or "").strip().lower()
        query_value = str(query or "").strip().lower()

        if lookup_email and partner_email == lookup_email:
            score += 180
        elif lookup_email and lookup_email in partner_email:
            score += 120

        if query_value and not _digits(query_value):
            name = str(partner.get("name") or "").strip().lower()
            if name == query_value:
                score += 110
            elif query_value in name:
                score += 70
            if partner_email and query_value in partner_email:
                score += 60

        lookup_phones = [value for value in [phone, query] if value and _digits(value)]
        partner_phones = [
            str(partner.get(field) or "")
            for field in ["phone", "mobile", "phone_sanitized"]
            if partner.get(field)
        ]
        score += _phone_match_score(lookup_phones, partner_phones)

        customer_rank = partner.get("customer_rank") or 0
        if isinstance(customer_rank, int):
            score += min(customer_rank, 10)

        return score

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

        partners = self.search_read(
            "res.partner",
            domain,
            self.partner_fields,
            limit=max(limit, 25),
            order="write_date desc",
        )
        partners.sort(
            key=lambda partner: self._score_partner(
                partner,
                query=query,
                email=email,
                phone=phone,
            ),
            reverse=True,
        )
        return partners[:limit]

    def find_partner(self, *, email: str | None, phone: str | None) -> dict[str, Any] | None:
        partners = self.search_partners(email=email, phone=phone, limit=1)
        return partners[0] if partners else None

    def get_partner(self, partner_id: int) -> dict[str, Any] | None:
        partners = self.read_records("res.partner", [partner_id], self.partner_fields)
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
            for phone_token in _phone_tokens(phone)[:3]:
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

    def get_invoices(self, *, partner_id: int | None) -> tuple[list[dict[str, Any]], str | None]:
        if not partner_id:
            return [], None

        invoices, warning = self.optional_search_read(
            "account.move",
            [
                ["partner_id", "child_of", partner_id],
                ["move_type", "in", ["out_invoice", "out_refund"]],
            ],
            [
                "id",
                "name",
                "move_type",
                "state",
                "invoice_date",
                "invoice_date_due",
                "amount_total",
                "amount_residual",
                "currency_id",
                "payment_state",
                "invoice_origin",
                "invoice_user_id",
            ],
            limit=self.settings.max_invoices,
            order="invoice_date desc, id desc",
        )
        if warning or not invoices:
            return invoices, warning

        invoice_ids = [invoice["id"] for invoice in invoices]
        lines, lines_warning = self.optional_search_read(
            "account.move.line",
            [
                ["move_id", "in", invoice_ids],
                ["display_type", "not in", ["line_section", "line_note"]],
            ],
            [
                "move_id",
                "product_id",
                "name",
                "quantity",
                "price_unit",
                "price_subtotal",
            ],
            limit=self.settings.max_invoices * 10,
            order="id asc",
        )
        lines_by_invoice: dict[int, list[dict[str, Any]]] = {}
        for line in lines:
            move_ref = line.get("move_id")
            if isinstance(move_ref, list | tuple) and move_ref:
                lines_by_invoice.setdefault(int(move_ref[0]), []).append(line)

        for invoice in invoices:
            invoice["lines"] = lines_by_invoice.get(int(invoice["id"]), [])

        return invoices, lines_warning

    def get_courses(self, *, partner_id: int | None) -> tuple[list[dict[str, Any]], str | None]:
        if not partner_id:
            return [], None

        courses: list[dict[str, Any]] = []
        warnings: list[str] = []

        elearning_courses, warning = self.optional_search_read(
            "slide.channel.partner",
            [["partner_id", "=", partner_id]],
            [
                "id",
                "channel_id",
                "member_status",
                "completion",
                "completed_slides_count",
                "next_slide_id",
                "partner_id",
            ],
            limit=self.settings.max_courses,
            order="write_date desc",
        )
        if warning:
            warnings.append(warning)
        for course in elearning_courses:
            course["source"] = "elearning"
            course["source_label"] = "eLearning"
            courses.append(course)

        event_courses, event_warning = self.get_event_registration_courses(
            partner_id=partner_id
        )
        if event_warning:
            warnings.append(event_warning)
        courses.extend(event_courses)

        sale_line_courses, sale_line_warning = self.get_sale_line_courses(
            partner_id=partner_id
        )
        if sale_line_warning:
            warnings.append(sale_line_warning)
        courses.extend(sale_line_courses)

        invoice_line_courses, invoice_line_warning = self.get_invoice_line_courses(
            partner_id=partner_id
        )
        if invoice_line_warning:
            warnings.append(invoice_line_warning)
        courses.extend(invoice_line_courses)

        deduped_courses: list[dict[str, Any]] = []
        seen: set[str] = set()
        for course in courses:
            identity = _course_identity(course)
            if identity in seen:
                continue
            seen.add(identity)
            deduped_courses.append(course)

        return deduped_courses[: self.settings.max_courses], "; ".join(warnings) or None

    def get_event_registration_courses(
        self, *, partner_id: int | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        fields = self.model_fields("event.registration")
        if not fields:
            return [], None

        if "partner_id" not in fields:
            return [], "event.registration: partner_id field is unavailable"

        desired_fields = [
            field
            for field in [
                "id",
                "event_id",
                "event_ticket_id",
                "partner_id",
                "name",
                "email",
                "phone",
                "state",
                "sale_order_id",
                "sale_order_line_id",
                "create_date",
            ]
            if field in fields
        ]
        registrations, warning = self.optional_search_read(
            "event.registration",
            [["partner_id", "child_of", partner_id]],
            desired_fields,
            limit=self.settings.max_courses,
            order="create_date desc",
        )
        if warning:
            return [], warning

        courses: list[dict[str, Any]] = []
        for registration in registrations:
            course_name = (
                registration.get("event_id")
                or registration.get("event_ticket_id")
                or registration.get("name")
                or f"Event registration #{registration.get('id')}"
            )
            courses.append(
                {
                    "id": f"event_registration:{registration.get('id')}",
                    "source": "event_registration",
                    "source_label": "Event attendee",
                    "channel_id": course_name,
                    "member_status": registration.get("state") or "-",
                    "completion": None,
                    "completed_slides_count": None,
                    "next_slide_id": False,
                    "attendee_name": registration.get("name"),
                    "event_ticket_id": registration.get("event_ticket_id"),
                    "sale_order_id": registration.get("sale_order_id"),
                    "sale_order_line_id": registration.get("sale_order_line_id"),
                }
            )
        return courses, None

    def get_sale_line_courses(
        self, *, partner_id: int | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        orders, orders_warning = self.optional_search_read(
            "sale.order",
            [["partner_id", "child_of", partner_id]],
            ["id", "name", "state", "date_order", "user_id"],
            limit=max(self.settings.max_courses * 4, 20),
            order="date_order desc",
        )
        if orders_warning:
            return [], orders_warning
        if not orders:
            return [], None

        order_ids = [order["id"] for order in orders]
        orders_by_id = {int(order["id"]): order for order in orders}
        fields = self.model_fields("sale.order.line")
        desired_fields = [
            field
            for field in [
                "id",
                "order_id",
                "product_id",
                "name",
                "product_uom_qty",
                "qty_delivered",
                "qty_invoiced",
                "event_id",
                "event_ticket_id",
                "display_type",
            ]
            if field in fields
        ]
        domain: list[Any] = [["order_id", "in", order_ids]]
        if "display_type" in fields:
            domain.append(["display_type", "=", False])

        lines, lines_warning = self.optional_search_read(
            "sale.order.line",
            domain,
            desired_fields,
            limit=max(self.settings.max_courses * 10, 50),
            order="id desc",
        )
        if lines_warning:
            return [], lines_warning

        courses: list[dict[str, Any]] = []
        for line in lines:
            text = " ".join(
                [
                    str(line.get("name") or ""),
                    str(line.get("product_id") or ""),
                    str(line.get("event_id") or ""),
                    str(line.get("event_ticket_id") or ""),
                ]
            )
            has_event_field = bool(line.get("event_id") or line.get("event_ticket_id"))
            if not has_event_field and not _looks_like_course_line(text):
                continue

            order_ref = line.get("order_id")
            order_id = int(order_ref[0]) if isinstance(order_ref, list | tuple) and order_ref else None
            order = orders_by_id.get(order_id) if order_id else None
            courses.append(
                {
                    "id": f"sale_order_line:{line.get('id')}",
                    "source": "sale_order_line",
                    "source_label": "Sales course line",
                    "channel_id": line.get("product_id") or line.get("name"),
                    "member_status": (order or {}).get("state") or "-",
                    "completion": None,
                    "completed_slides_count": None,
                    "next_slide_id": False,
                    "description": line.get("name"),
                    "quantity": line.get("product_uom_qty"),
                    "delivered": line.get("qty_delivered"),
                    "invoiced": line.get("qty_invoiced"),
                    "order_id": order_ref,
                    "order_name": (order or {}).get("name"),
                    "salesperson": (order or {}).get("user_id"),
                    "event_id": line.get("event_id"),
                    "event_ticket_id": line.get("event_ticket_id"),
                }
            )
            if len(courses) >= self.settings.max_courses:
                break

        return courses, None

    def get_invoice_line_courses(
        self, *, partner_id: int | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        moves, moves_warning = self.optional_search_read(
            "account.move",
            [
                ["partner_id", "child_of", partner_id],
                ["move_type", "in", ["out_invoice", "out_refund"]],
            ],
            ["id", "name", "state", "payment_state", "invoice_date", "invoice_user_id"],
            limit=max(self.settings.max_courses * 4, 20),
            order="invoice_date desc, id desc",
        )
        if moves_warning:
            return [], moves_warning
        if not moves:
            return [], None

        move_ids = [move["id"] for move in moves]
        moves_by_id = {int(move["id"]): move for move in moves}
        fields = self.model_fields("account.move.line")
        desired_fields = [
            field
            for field in [
                "id",
                "move_id",
                "product_id",
                "name",
                "quantity",
                "display_type",
            ]
            if field in fields
        ]
        domain: list[Any] = [["move_id", "in", move_ids]]
        if "display_type" in fields:
            domain.append(["display_type", "not in", ["line_section", "line_note"]])

        lines, lines_warning = self.optional_search_read(
            "account.move.line",
            domain,
            desired_fields,
            limit=max(self.settings.max_courses * 10, 50),
            order="id desc",
        )
        if lines_warning:
            return [], lines_warning

        courses: list[dict[str, Any]] = []
        for line in lines:
            text = " ".join(
                [
                    str(line.get("name") or ""),
                    str(line.get("product_id") or ""),
                ]
            )
            if not _looks_like_course_line(text):
                continue

            move_ref = line.get("move_id")
            move_id = int(move_ref[0]) if isinstance(move_ref, list | tuple) and move_ref else None
            move = moves_by_id.get(move_id) if move_id else None
            courses.append(
                {
                    "id": f"invoice_line:{line.get('id')}",
                    "source": "invoice_line",
                    "source_label": "Invoice course line",
                    "channel_id": line.get("product_id") or line.get("name"),
                    "member_status": (move or {}).get("state") or "-",
                    "completion": None,
                    "completed_slides_count": None,
                    "next_slide_id": False,
                    "description": line.get("name"),
                    "quantity": line.get("quantity"),
                    "invoice_id": move_ref,
                    "invoice_name": (move or {}).get("name"),
                    "salesperson": (move or {}).get("invoice_user_id"),
                }
            )
            if len(courses) >= self.settings.max_courses:
                break

        return courses, None

    def customer_snapshot(
        self,
        *,
        email: str | None,
        phone: str | None,
        query: str | None = None,
        partner_id: int | None = None,
        include_orders: bool = True,
        include_invoices: bool = True,
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
        orders = self.get_sale_orders(partner_id=partner_id) if include_orders else []
        invoices, invoices_warning = (
            self.get_invoices(partner_id=partner_id) if include_invoices else ([], None)
        )
        courses, courses_warning = self.get_courses(partner_id=partner_id)
        warnings = [warning for warning in [invoices_warning, courses_warning] if warning]

        logger.info(
            "Odoo snapshot loaded partner=%s leads=%s orders=%s invoices=%s courses=%s",
            partner_id,
            len(leads),
            len(orders),
            len(invoices),
            len(courses),
        )
        return {
            "partner": partner,
            "matches": matches,
            "leads": leads,
            "orders": orders,
            "invoices": invoices,
            "courses": courses,
            "warnings": warnings,
        }
