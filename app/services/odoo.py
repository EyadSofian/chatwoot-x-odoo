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
        return [clauses[0]]
    return ["|"] * (len(clauses) - 1) + clauses


PARTNER_BASE_FIELDS = [
    "id",
    "name",
    "display_name",
    "email",
    "phone",
    "mobile",
    "website",
    "function",
    "title",
    "company_name",
    "commercial_partner_id",
    "parent_id",
    "type",
    "company_type",
    "is_company",
    "active",
    "vat",
    "ref",
    "street",
    "street2",
    "city",
    "state_id",
    "zip",
    "country_id",
    "lang",
    "category_id",
    "comment",
    "customer_rank",
    "supplier_rank",
    "user_id",
    "team_id",
    "property_payment_term_id",
    "property_product_pricelist",
    "credit",
    "credit_limit",
    "create_date",
    "write_date",
]
OPTIONAL_PARTNER_FIELDS = ["phone_sanitized"]
DISPLAYABLE_CUSTOM_FIELD_TYPES = {
    "boolean",
    "char",
    "date",
    "datetime",
    "float",
    "integer",
    "many2one",
    "monetary",
    "selection",
    "text",
}
ARABIC_SEARCH_TRANSLATION = str.maketrans(
    {
        "\u0622": "\u0627",
        "\u0623": "\u0627",
        "\u0625": "\u0627",
        "\u0626": "\u064a",
        "\u0624": "\u0648",
        "\u0629": "\u0647",
        "\u0649": "\u064a",
        "\u0640": None,
    }
)
ARABIC_DIACRITICS = re.compile(
    "[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]"
)


def _normalize_search_text(value: str | None) -> str:
    text = str(value or "").casefold().translate(ARABIC_SEARCH_TRANSLATION)
    text = ARABIC_DIACRITICS.sub("", text)
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def _name_search_tokens(value: str | None) -> list[str]:
    tokens = [
        token
        for token in re.sub(r"[^\w]+", " ", str(value or "")).split()
        if len(_normalize_search_text(token)) >= 3
    ]
    return sorted(dict.fromkeys(tokens), key=len, reverse=True)


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


def _phone_search_fragments(value: str | None) -> list[str]:
    digits = _digits(value)
    fragments = set(_phone_tokens(value))
    for length in (7, 6, 5, 4):
        if len(digits) >= length:
            fragments.add(digits[-length:])
    return sorted(fragments, key=len, reverse=True)


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


def _relation_id(value: Any) -> int | None:
    """Return the integer id from an Odoo many2one ``[id, name]`` pair or raw id."""
    if isinstance(value, list | tuple) and value:
        try:
            return int(value[0])
        except (TypeError, ValueError):
            return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def commercial_partner_id(partner: dict[str, Any] | None) -> int | None:
    if not partner:
        return None
    return _relation_id(partner.get("commercial_partner_id"))


def partner_scope_ids(partner: dict[str, Any] | None) -> list[int]:
    """Partner ids to search commercial records against.

    Includes the matched partner *and* its ``commercial_partner_id`` (the top of the
    company/contact hierarchy in Odoo). Sales orders and invoices are frequently
    booked on the commercial parent while the Chatwoot email/phone matches a child
    contact, so searching only the matched id with ``child_of`` would miss them.
    """
    if not partner:
        return []
    ids: list[int] = []
    matched_id = _relation_id(partner.get("id"))
    if matched_id:
        ids.append(matched_id)
    commercial_id = commercial_partner_id(partner)
    if commercial_id and commercial_id not in ids:
        ids.append(commercial_id)
    return ids


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
        return self.record_fields(
            "res.partner",
            PARTNER_BASE_FIELDS + OPTIONAL_PARTNER_FIELDS,
            include_custom=True,
        )

    @cached_property
    def partner_search_fields(self) -> list[str]:
        return self.record_fields(
            "res.partner",
            [
                "id",
                "name",
                "email",
                "phone",
                "mobile",
                "phone_sanitized",
                "company_name",
                "commercial_partner_id",
                "parent_id",
                "type",
                "is_company",
                "customer_rank",
                "user_id",
                "write_date",
            ],
        )

    def model_fields(self, model: str) -> dict[str, Any]:
        if model in self._model_fields_cache:
            return self._model_fields_cache[model]

        try:
            available = self.execute_kw(
                model,
                "fields_get",
                [],
                {"attributes": ["string", "type"]},
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

    def available_fields(self, model: str, desired_fields: list[str]) -> list[str]:
        available = self.model_fields(model)
        if not available:
            return desired_fields
        return [field for field in desired_fields if field in available]

    def record_fields(
        self,
        model: str,
        desired_fields: list[str],
        *,
        include_custom: bool = False,
    ) -> list[str]:
        available = self.model_fields(model)
        if not available:
            return list(dict.fromkeys(desired_fields))

        fields = [field for field in desired_fields if field in available]
        if include_custom:
            fields.extend(
                field
                for field, metadata in available.items()
                if field.startswith("x_")
                and metadata.get("type") in DISPLAYABLE_CUSTOM_FIELD_TYPES
            )
        return list(dict.fromkeys(fields))

    def field_labels(self, model: str, fields: set[str]) -> dict[str, str]:
        metadata = self.model_fields(model)
        return {
            field: str(metadata.get(field, {}).get("string") or field)
            for field in sorted(fields)
        }

    def partner_link_domain(
        self,
        model: str,
        partner_ids: list[int],
        *,
        candidate_fields: tuple[str, ...] = ("partner_id",),
    ) -> list[Any]:
        if not partner_ids:
            return []

        available = self.model_fields(model)
        clauses: list[list[Any]] = []
        for index, field in enumerate(candidate_fields):
            if available and field not in available:
                continue
            if not available and index > 0:
                continue
            operator = "in" if field == "commercial_partner_id" else "child_of"
            clauses.append([field, operator, partner_ids])

        return _or_domain(clauses) if clauses else [["id", "=", 0]]

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
                for name_token in _name_search_tokens(query)[:3]:
                    if name_token.casefold() != query.casefold():
                        clauses.append(["name", "ilike", name_token])
            elif query.isdigit() and len(query) <= 9:
                clauses.append(["id", "=", int(query)])

            for phone_token in _phone_search_fragments(query)[:6]:
                for field in ["phone", "mobile", "phone_sanitized"]:
                    if field in self.partner_fields:
                        clauses.append([field, "ilike", phone_token])

        if email:
            clauses.append(["email", "ilike", email.strip()])

        for phone_token in _phone_search_fragments(phone)[:6]:
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
        query_value = _normalize_search_text(query)

        if lookup_email and partner_email == lookup_email:
            score += 180
        elif lookup_email and lookup_email in partner_email:
            score += 120

        if query_value and not _digits(query_value):
            name = _normalize_search_text(partner.get("name"))
            if name == query_value:
                score += 160
            elif query_value in name:
                score += 100

            query_tokens = set(query_value.split())
            name_tokens = set(name.split())
            overlap = query_tokens & name_tokens
            if query_tokens and query_tokens.issubset(name_tokens):
                score += 120
            elif overlap:
                score += int(80 * len(overlap) / len(query_tokens))

            if partner_email and query_value in _normalize_search_text(partner_email):
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
            self.partner_search_fields,
            limit=max(limit, 100),
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

    def get_related_contacts(
        self, *, partner_ids: list[int]
    ) -> tuple[list[dict[str, Any]], str | None]:
        if not partner_ids:
            return [], None

        contacts, warning = self.optional_search_read(
            "res.partner",
            [["id", "child_of", partner_ids]],
            self.partner_fields,
            limit=25,
            order="name asc, id asc",
        )
        return contacts, warning

    def get_leads(
        self,
        *,
        partner_ids: list[int],
        email: str | None,
        phone: str | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        clauses: list[list[Any]] = []
        if partner_ids:
            clauses.append(["partner_id", "child_of", partner_ids])
        if email:
            clauses.append(["email_from", "ilike", email.strip()])

        phone_digits = _digits(phone)
        if phone_digits:
            for phone_token in _phone_search_fragments(phone)[:6]:
                clauses.append(["phone", "ilike", phone_token])
                clauses.append(["mobile", "ilike", phone_token])

        if not clauses:
            return [], None

        lead_fields = self.record_fields(
            "crm.lead",
            [
                "id",
                "name",
                "type",
                "active",
                "partner_id",
                "partner_name",
                "contact_name",
                "stage_id",
                "expected_revenue",
                "probability",
                "recurring_revenue",
                "recurring_plan",
                "priority",
                "email_from",
                "phone",
                "mobile",
                "street",
                "street2",
                "city",
                "state_id",
                "zip",
                "country_id",
                "create_date",
                "date_open",
                "date_closed",
                "date_deadline",
                "date_last_stage_update",
                "user_id",
                "team_id",
                "company_id",
                "campaign_id",
                "medium_id",
                "source_id",
                "tag_ids",
                "description",
                "lost_reason_id",
                "write_date",
            ],
            include_custom=True,
        )
        return self.optional_search_read(
            "crm.lead",
            _or_domain(clauses),
            lead_fields,
            limit=self.settings.max_leads,
            order="write_date desc",
        )

    def get_sale_orders(
        self, *, partner_ids: list[int]
    ) -> tuple[list[dict[str, Any]], str | None]:
        if not partner_ids:
            return [], None

        partner_domain = self.partner_link_domain(
            "sale.order",
            partner_ids,
            candidate_fields=(
                "commercial_partner_id",
                "partner_id",
            ),
        )
        order_fields = self.record_fields(
            "sale.order",
            [
                "id",
                "name",
                "state",
                "locked",
                "date_order",
                "create_date",
                "validity_date",
                "commitment_date",
                "expected_date",
                "client_order_ref",
                "origin",
                "reference",
                "partner_id",
                "commercial_partner_id",
                "partner_invoice_id",
                "partner_shipping_id",
                "user_id",
                "team_id",
                "company_id",
                "warehouse_id",
                "pricelist_id",
                "currency_id",
                "payment_term_id",
                "fiscal_position_id",
                "journal_id",
                "amount_untaxed",
                "amount_tax",
                "amount_total",
                "amount_to_invoice",
                "amount_invoiced",
                "amount_paid",
                "invoice_status",
                "invoice_count",
                "require_signature",
                "require_payment",
                "signed_by",
                "signed_on",
                "campaign_id",
                "medium_id",
                "source_id",
                "tag_ids",
                "note",
                "write_date",
            ],
        )
        orders, warning = self.optional_search_read(
            "sale.order",
            partner_domain,
            order_fields,
            limit=self.settings.max_orders,
            order="date_order desc",
        )
        if warning or not orders:
            return orders, warning

        order_ids = [order["id"] for order in orders]
        line_fields = self.record_fields(
            "sale.order.line",
            [
                "id",
                "order_id",
                "sequence",
                "display_type",
                "product_id",
                "name",
                "product_template_id",
                "product_uom_qty",
                "product_uom",
                "qty_delivered",
                "qty_invoiced",
                "qty_to_invoice",
                "invoice_status",
                "price_unit",
                "discount",
                "tax_id",
                "price_subtotal",
                "price_tax",
                "price_total",
                "currency_id",
                "customer_lead",
                "is_downpayment",
                "event_id",
                "event_ticket_id",
                "analytic_distribution",
                "create_date",
                "write_date",
            ],
        )
        lines, lines_warning = self.optional_search_read(
            "sale.order.line",
            [["order_id", "in", order_ids]],
            line_fields,
            limit=max(self.settings.max_orders * 50, 250),
            order="sequence asc, id asc",
        )
        lines_by_order: dict[int, list[dict[str, Any]]] = {}
        for line in lines:
            order_ref = line.get("order_id")
            if isinstance(order_ref, list | tuple) and order_ref:
                lines_by_order.setdefault(int(order_ref[0]), []).append(line)

        for order in orders:
            order["lines"] = lines_by_order.get(int(order["id"]), [])
        return orders, lines_warning

    def get_invoices(
        self, *, partner_ids: list[int]
    ) -> tuple[list[dict[str, Any]], str | None]:
        if not partner_ids:
            return [], None

        partner_domain = self.partner_link_domain(
            "account.move",
            partner_ids,
            candidate_fields=("partner_id", "commercial_partner_id"),
        )
        invoice_fields = self.record_fields(
            "account.move",
            [
                "id",
                "name",
                "ref",
                "move_type",
                "state",
                "date",
                "invoice_date",
                "invoice_date_due",
                "invoice_origin",
                "payment_reference",
                "partner_id",
                "commercial_partner_id",
                "invoice_partner_display_name",
                "invoice_user_id",
                "company_id",
                "journal_id",
                "currency_id",
                "invoice_currency_rate",
                "invoice_payment_term_id",
                "fiscal_position_id",
                "amount_untaxed",
                "amount_tax",
                "amount_total",
                "amount_residual",
                "amount_untaxed_signed",
                "amount_tax_signed",
                "amount_total_signed",
                "amount_residual_signed",
                "payment_state",
                "reversed_entry_id",
                "invoice_incoterm_id",
                "invoice_cash_rounding_id",
                "narration",
                "campaign_id",
                "medium_id",
                "source_id",
                "create_date",
                "write_date",
            ],
            include_custom=True,
        )
        invoices, warning = self.optional_search_read(
            "account.move",
            partner_domain + [["move_type", "in", ["out_invoice", "out_refund"]]],
            invoice_fields,
            limit=self.settings.max_invoices,
            order="invoice_date desc, id desc",
        )
        if warning or not invoices:
            return invoices, warning

        invoice_ids = [invoice["id"] for invoice in invoices]
        invoice_line_fields = self.record_fields(
            "account.move.line",
            [
                "id",
                "move_id",
                "sequence",
                "display_type",
                "product_id",
                "product_uom_id",
                "name",
                "quantity",
                "price_unit",
                "discount",
                "tax_ids",
                "price_subtotal",
                "price_total",
                "balance",
                "amount_currency",
                "currency_id",
                "account_id",
                "analytic_distribution",
                "sale_line_ids",
                "date",
                "date_maturity",
                "create_date",
                "write_date",
            ],
            include_custom=True,
        )
        lines, lines_warning = self.optional_search_read(
            "account.move.line",
            [
                ["move_id", "in", invoice_ids],
                ["display_type", "in", ["product", False]],
            ],
            invoice_line_fields,
            limit=max(self.settings.max_invoices * 50, 250),
            order="sequence asc, id asc",
        )
        lines_by_invoice: dict[int, list[dict[str, Any]]] = {}
        for line in lines:
            move_ref = line.get("move_id")
            if isinstance(move_ref, list | tuple) and move_ref:
                lines_by_invoice.setdefault(int(move_ref[0]), []).append(line)

        for invoice in invoices:
            invoice["lines"] = lines_by_invoice.get(int(invoice["id"]), [])

        return invoices, lines_warning

    def get_journal_entries(
        self, *, partner_ids: list[int]
    ) -> tuple[list[dict[str, Any]], str | None]:
        if not partner_ids:
            return [], None

        line_fields = self.available_fields(
            "account.move.line",
            [
                "id",
                "move_id",
                "date",
                "name",
                "ref",
                "partner_id",
                "account_id",
                "debit",
                "credit",
                "balance",
                "currency_id",
                "amount_currency",
                "reconciled",
            ],
        )
        partner_lines, lines_warning = self.optional_search_read(
            "account.move.line",
            self.partner_link_domain("account.move.line", partner_ids)
            + [["move_id.move_type", "=", "entry"]],
            line_fields,
            limit=max(self.settings.max_journal_entries * 20, 100),
            order="date desc, id desc",
        )
        if lines_warning or not partner_lines:
            return [], lines_warning

        move_ids: list[int] = []
        for line in partner_lines:
            move_id = _relation_id(line.get("move_id"))
            if move_id and move_id not in move_ids:
                move_ids.append(move_id)
            if len(move_ids) >= self.settings.max_journal_entries:
                break

        move_fields = self.available_fields(
            "account.move",
            [
                "id",
                "name",
                "ref",
                "date",
                "state",
                "move_type",
                "journal_id",
                "company_id",
                "partner_id",
                "commercial_partner_id",
                "currency_id",
            ],
        )
        entries, entries_warning = self.optional_search_read(
            "account.move",
            [["id", "in", move_ids], ["move_type", "=", "entry"]],
            move_fields,
            limit=self.settings.max_journal_entries,
            order="date desc, id desc",
        )
        if entries_warning:
            return [], entries_warning

        lines_by_move: dict[int, list[dict[str, Any]]] = {}
        for line in partner_lines:
            move_id = _relation_id(line.get("move_id"))
            if move_id in move_ids:
                lines_by_move.setdefault(int(move_id), []).append(line)

        for entry in entries:
            entry_lines = lines_by_move.get(int(entry["id"]), [])
            entry["lines"] = entry_lines
            entry["partner_debit"] = sum(float(line.get("debit") or 0) for line in entry_lines)
            entry["partner_credit"] = sum(float(line.get("credit") or 0) for line in entry_lines)
            entry["partner_balance"] = sum(
                float(line.get("balance") or 0) for line in entry_lines
            )

        return entries, None

    def get_courses(
        self, *, partner_ids: list[int]
    ) -> tuple[list[dict[str, Any]], str | None]:
        if not partner_ids:
            return [], None

        courses: list[dict[str, Any]] = []
        warnings: list[str] = []

        elearning_courses, warning = self.optional_search_read(
            "slide.channel.partner",
            [["partner_id", "child_of", partner_ids]],
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
            partner_ids=partner_ids
        )
        if event_warning:
            warnings.append(event_warning)
        courses.extend(event_courses)

        sale_line_courses, sale_line_warning = self.get_sale_line_courses(
            partner_ids=partner_ids
        )
        if sale_line_warning:
            warnings.append(sale_line_warning)
        courses.extend(sale_line_courses)

        invoice_line_courses, invoice_line_warning = self.get_invoice_line_courses(
            partner_ids=partner_ids
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
        self, *, partner_ids: list[int]
    ) -> tuple[list[dict[str, Any]], str | None]:
        if not partner_ids:
            return [], None

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
            self.partner_link_domain("event.registration", partner_ids),
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
        self, *, partner_ids: list[int]
    ) -> tuple[list[dict[str, Any]], str | None]:
        if not partner_ids:
            return [], None

        orders, orders_warning = self.optional_search_read(
            "sale.order",
            self.partner_link_domain(
                "sale.order",
                partner_ids,
                candidate_fields=(
                    "partner_id",
                    "commercial_partner_id",
                    "partner_invoice_id",
                    "partner_shipping_id",
                ),
            ),
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
        self, *, partner_ids: list[int]
    ) -> tuple[list[dict[str, Any]], str | None]:
        if not partner_ids:
            return [], None

        moves, moves_warning = self.optional_search_read(
            "account.move",
            self.partner_link_domain(
                "account.move",
                partner_ids,
                candidate_fields=("partner_id", "commercial_partner_id"),
            )
            + [["move_type", "in", ["out_invoice", "out_refund"]]],
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
        include_contacts: bool = True,
        include_leads: bool = True,
        include_orders: bool = True,
        include_invoices: bool = True,
        include_journal_entries: bool = True,
        include_courses: bool = True,
    ) -> dict[str, Any]:
        if partner_id:
            partner = self.get_partner(partner_id)
            matches = [partner] if partner else []
        elif query:
            matches = self.search_partners(query=query, email=email, phone=phone, limit=10)
            candidate = matches[0] if matches else None
            partner = (
                self.get_partner(int(candidate["id"]))
                if candidate and candidate.get("id")
                else candidate
            )
        else:
            matches = self.search_partners(email=email, phone=phone, limit=10)
            candidate = matches[0] if matches else None
            partner = (
                self.get_partner(int(candidate["id"]))
                if candidate and candidate.get("id")
                else candidate
            )

        partner_id = int(partner["id"]) if partner else None
        scope_ids = partner_scope_ids(partner)
        commercial_id = commercial_partner_id(partner)

        lookup_email = email or (partner or {}).get("email")
        lookup_phone = phone or (partner or {}).get("phone") or (partner or {}).get("mobile")
        related_contacts, contacts_warning = (
            self.get_related_contacts(partner_ids=scope_ids)
            if include_contacts
            else ([], None)
        )
        leads, leads_warning = (
            self.get_leads(
                partner_ids=scope_ids,
                email=lookup_email,
                phone=lookup_phone,
            )
            if include_leads
            else ([], None)
        )
        orders, orders_warning = (
            self.get_sale_orders(partner_ids=scope_ids) if include_orders else ([], None)
        )
        invoices, invoices_warning = (
            self.get_invoices(partner_ids=scope_ids) if include_invoices else ([], None)
        )
        quotations = [
            order for order in orders if order.get("state") in {"draft", "sent"}
        ]
        sales_orders = [
            order for order in orders if order.get("state") not in {"draft", "sent"}
        ]
        invoiced_items: list[dict[str, Any]] = []
        for invoice in invoices:
            for invoice_line in invoice.get("lines", []):
                item = dict(invoice_line)
                item.update(
                    {
                        "invoice_id": invoice.get("id"),
                        "invoice_name": invoice.get("name"),
                        "invoice_type": invoice.get("move_type"),
                        "invoice_state": invoice.get("state"),
                        "invoice_date": invoice.get("invoice_date"),
                        "invoice_date_due": invoice.get("invoice_date_due"),
                        "invoice_origin": invoice.get("invoice_origin"),
                        "payment_state": invoice.get("payment_state"),
                        "invoice_user_id": invoice.get("invoice_user_id"),
                        "invoice_currency_id": invoice.get("currency_id"),
                    }
                )
                invoiced_items.append(item)
        journal_entries, journal_entries_warning = (
            self.get_journal_entries(partner_ids=scope_ids)
            if include_journal_entries
            else ([], None)
        )
        courses, courses_warning = (
            self.get_courses(partner_ids=scope_ids) if include_courses else ([], None)
        )
        warnings = [
            warning
            for warning in [
                contacts_warning,
                leads_warning,
                orders_warning,
                invoices_warning,
                journal_entries_warning,
                courses_warning,
            ]
            if warning
        ]

        logger.info(
            "Odoo snapshot loaded partner=%s commercial=%s scope=%s "
            "contacts=%s leads=%s quotations=%s sales_orders=%s invoices=%s "
            "invoiced_items=%s journal_entries=%s courses=%s warnings=%s",
            partner_id,
            commercial_id,
            scope_ids,
            len(related_contacts),
            len(leads),
            len(quotations),
            len(sales_orders),
            len(invoices),
            len(invoiced_items),
            len(journal_entries),
            len(courses),
            len(warnings),
        )

        def record_keys(records: list[dict[str, Any]]) -> set[str]:
            return {key for record in records for key in record}

        order_line_keys = record_keys(
            [
                line
                for order in orders
                for line in order.get("lines", [])
                if isinstance(line, dict)
            ]
        )
        invoice_line_keys = record_keys(
            [
                line
                for invoice in invoices
                for line in invoice.get("lines", [])
                if isinstance(line, dict)
            ]
        )
        field_labels = {
            "partner": self.field_labels(
                "res.partner",
                set(partner or {}) | record_keys(related_contacts),
            ),
            "crm_lead": self.field_labels("crm.lead", record_keys(leads)),
            "sale_order": self.field_labels("sale.order", record_keys(orders)),
            "sale_order_line": self.field_labels("sale.order.line", order_line_keys),
            "invoice": self.field_labels("account.move", record_keys(invoices)),
            "invoice_line": self.field_labels("account.move.line", invoice_line_keys),
        }
        debug = {
            "partner_id": partner_id,
            "commercial_partner_id": commercial_id,
            "scope_partner_ids": scope_ids,
            "contacts_included": include_contacts,
            "leads_included": include_leads,
            "orders_included": include_orders,
            "invoices_included": include_invoices,
            "journal_entries_included": include_journal_entries,
            "courses_included": include_courses,
            "counts": {
                "matches": len(matches),
                "related_contacts": len(related_contacts),
                "leads": len(leads),
                "orders": len(orders),
                "quotations": len(quotations),
                "sales_orders": len(sales_orders),
                "invoices": len(invoices),
                "invoiced_items": len(invoiced_items),
                "journal_entries": len(journal_entries),
                "courses": len(courses),
            },
        }
        return {
            "partner": partner,
            "matches": matches,
            "related_contacts": related_contacts,
            "leads": leads,
            "orders": orders,
            "quotations": quotations,
            "sales_orders": sales_orders,
            "invoices": invoices,
            "invoiced_items": invoiced_items,
            "journal_entries": journal_entries,
            "courses": courses,
            "field_labels": field_labels,
            "warnings": warnings,
            "debug": debug,
        }
