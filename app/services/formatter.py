from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def _name(value: Any) -> str:
    if isinstance(value, list | tuple) and len(value) >= 2:
        return str(value[1])
    if value in (False, None, ""):
        return "-"
    return str(value)


def _money(value: Any, currency: Any = None) -> str:
    try:
        amount = Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        amount = Decimal("0.00")
    currency_name = _name(currency)
    if currency_name == "-":
        return f"{amount}"
    return f"{amount} {currency_name}"


def format_customer_note(snapshot: dict[str, Any], *, lookup_email: str | None, lookup_phone: str | None) -> str:
    partner = snapshot.get("partner")
    related_contacts = snapshot.get("related_contacts", [])
    leads = snapshot.get("leads", [])
    orders = snapshot.get("orders", [])
    quotations = snapshot.get(
        "quotations",
        [order for order in orders if order.get("state") in {"draft", "sent"}],
    )
    sales_orders = snapshot.get(
        "sales_orders",
        [order for order in orders if order.get("state") not in {"draft", "sent"}],
    )
    invoices = snapshot.get("invoices", [])
    invoiced_items = snapshot.get(
        "invoiced_items",
        [line for invoice in invoices for line in invoice.get("lines", [])],
    )
    journal_entries = snapshot.get("journal_entries", [])
    courses = snapshot.get("courses", [])
    warnings = snapshot.get("warnings", [])
    restricted_sections = snapshot.get("restricted_sections", [])

    lines: list[str] = ["Odoo customer snapshot"]
    lookup_bits = []
    if lookup_email:
        lookup_bits.append(f"email: {lookup_email}")
    if lookup_phone:
        lookup_bits.append(f"phone: {lookup_phone}")
    if lookup_bits:
        lines.append(f"Lookup: {', '.join(lookup_bits)}")

    if not partner:
        lines.append("")
        lines.append("No matching Odoo contact was found.")
        return "\n".join(lines)

    lines.extend(
        [
            "",
            f"Contact: {partner.get('name') or '-'}",
            f"Odoo partner ID: {partner.get('id')}",
            f"Email: {partner.get('email') or '-'}",
            f"Phone: {partner.get('phone') or partner.get('mobile') or '-'}",
            f"Salesperson: {_name(partner.get('user_id'))}",
            f"Company: {partner.get('company_name') or _name(partner.get('commercial_partner_id'))}",
        ]
    )

    lines.append("")
    lines.append(f"Related contacts: {len(related_contacts)}")
    for contact in related_contacts[:5]:
        lines.append(
            f"- #{contact.get('id')} {contact.get('name') or '-'} | "
            f"{contact.get('email') or '-'} | "
            f"{contact.get('phone') or contact.get('mobile') or '-'}"
        )

    lines.append("")
    lines.append(f"CRM leads/opportunities: {len(leads)}")
    if leads:
        for lead in leads[:5]:
            stage = _name(lead.get("stage_id"))
            revenue = _money(lead.get("expected_revenue"))
            lines.append(f"- #{lead.get('id')} {lead.get('name') or '-'} | {stage} | {revenue}")

    lines.append("")
    if "orders" in restricted_sections:
        lines.append("Recent sales orders: restricted for current agent")
        lines.append("Quotations: restricted for current agent")
    else:
        lines.append(f"Quotations: {len(quotations)}")
        lines.append(f"Sales orders: {len(sales_orders)}")
    if orders and "orders" not in restricted_sections:
        for order in (quotations + sales_orders)[:5]:
            state = order.get("state") or "-"
            total = _money(order.get("amount_total"), order.get("currency_id"))
            invoice_status = order.get("invoice_status") or "-"
            salesperson = _name(order.get("user_id"))
            lines.append(
                f"- {order.get('name')} | {state} | {total} | "
                f"invoice: {invoice_status} | salesperson: {salesperson}"
            )
            for order_line in order.get("lines", [])[:3]:
                product = _name(order_line.get("product_id"))
                qty = order_line.get("product_uom_qty") or 0
                subtotal = _money(order_line.get("price_subtotal"), order.get("currency_id"))
                lines.append(f"  * {product} x {qty}: {subtotal}")

    lines.append("")
    if "invoices" in restricted_sections:
        lines.append("Recent invoices: restricted for current agent")
    else:
        lines.append(f"Recent invoices: {len(invoices)}")
        lines.append(f"Invoiced items: {len(invoiced_items)}")
    if invoices and "invoices" not in restricted_sections:
        for invoice in invoices[:5]:
            total = _money(invoice.get("amount_total"), invoice.get("currency_id"))
            due = _money(invoice.get("amount_residual"), invoice.get("currency_id"))
            salesperson = _name(invoice.get("invoice_user_id"))
            lines.append(
                f"- {invoice.get('name')} | {invoice.get('state') or '-'} | "
                f"{invoice.get('payment_state') or '-'} | total: {total} | "
                f"due: {due} | salesperson: {salesperson}"
            )
            for invoice_line in invoice.get("lines", [])[:3]:
                product = _name(invoice_line.get("product_id")) or invoice_line.get("name") or "-"
                qty = invoice_line.get("quantity") or 0
                subtotal = _money(invoice_line.get("price_subtotal"), invoice.get("currency_id"))
                lines.append(f"  * {product} x {qty}: {subtotal}")

    lines.append("")
    lines.append(f"Journal entries: {len(journal_entries)}")
    for entry in journal_entries[:5]:
        debit = _money(entry.get("partner_debit"), entry.get("currency_id"))
        credit = _money(entry.get("partner_credit"), entry.get("currency_id"))
        lines.append(
            f"- {entry.get('name') or '-'} | {entry.get('date') or '-'} | "
            f"{_name(entry.get('journal_id'))} | {entry.get('state') or '-'} | "
            f"debit: {debit} | credit: {credit}"
        )

    lines.append("")
    lines.append(f"Courses: {len(courses)}")
    if courses:
        for course in courses[:5]:
            completion = course.get("completion")
            status = course.get("member_status") or "-"
            source = course.get("source_label") or course.get("source") or "-"
            if completion in (False, None, ""):
                order_name = course.get("order_name") or _name(course.get("order_id"))
                quantity = course.get("quantity")
                details = [f"source: {source}", f"status: {status}"]
                if order_name != "-":
                    details.append(f"order: {order_name}")
                invoice_name = course.get("invoice_name") or _name(course.get("invoice_id"))
                if invoice_name != "-":
                    details.append(f"invoice: {invoice_name}")
                salesperson = _name(course.get("salesperson"))
                if salesperson != "-":
                    details.append(f"salesperson: {salesperson}")
                if quantity not in (False, None, ""):
                    details.append(f"qty: {quantity}")
                lines.append(f"- {_name(course.get('channel_id'))} | {' | '.join(details)}")
            else:
                next_lesson = _name(course.get("next_slide_id"))
                lines.append(
                    f"- {_name(course.get('channel_id'))} | source: {source} | "
                    f"{status} | {completion}% complete | next: {next_lesson}"
                )

    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in warnings[:3]:
            lines.append(f"- {warning}")

    return "\n".join(lines)


def conversation_attributes(
    snapshot: dict[str, Any],
    *,
    include_sensitive: bool = True,
) -> dict[str, Any]:
    partner = snapshot.get("partner")
    related_contacts = snapshot.get("related_contacts", [])
    leads = snapshot.get("leads", [])
    orders = snapshot.get("orders", []) if include_sensitive else []
    quotations = (
        snapshot.get(
            "quotations",
            [order for order in orders if order.get("state") in {"draft", "sent"}],
        )
        if include_sensitive
        else []
    )
    sales_orders = (
        snapshot.get(
            "sales_orders",
            [order for order in orders if order.get("state") not in {"draft", "sent"}],
        )
        if include_sensitive
        else []
    )
    invoices = snapshot.get("invoices", []) if include_sensitive else []
    invoiced_items = (
        snapshot.get(
            "invoiced_items",
            [line for invoice in invoices for line in invoice.get("lines", [])],
        )
        if include_sensitive
        else []
    )
    journal_entries = snapshot.get("journal_entries", []) if include_sensitive else []
    courses = snapshot.get("courses", [])

    attrs: dict[str, Any] = {
        "odoo_match_found": bool(partner),
        "odoo_related_contacts_count": len(related_contacts),
        "odoo_leads_count": len(leads),
        "odoo_courses_count": len(courses),
    }

    if include_sensitive:
        attrs["odoo_orders_count"] = len(orders)
        attrs["odoo_quotations_count"] = len(quotations)
        attrs["odoo_sales_orders_count"] = len(sales_orders)
        attrs["odoo_invoices_count"] = len(invoices)
        attrs["odoo_invoiced_items_count"] = len(invoiced_items)
        attrs["odoo_journal_entries_count"] = len(journal_entries)

    if partner:
        attrs["odoo_partner_id"] = str(partner.get("id"))
        attrs["odoo_partner_name"] = partner.get("name") or ""
        partner_salesperson = _name(partner.get("user_id"))
        if partner_salesperson != "-":
            attrs["odoo_partner_salesperson"] = partner_salesperson

    if orders:
        attrs["odoo_last_order"] = orders[0].get("name") or ""
        attrs["odoo_last_order_state"] = orders[0].get("state") or ""
        attrs["odoo_last_order_total"] = str(orders[0].get("amount_total") or 0)
        attrs["odoo_last_order_salesperson"] = _name(orders[0].get("user_id"))

    if invoices:
        attrs["odoo_last_invoice"] = invoices[0].get("name") or ""
        attrs["odoo_last_invoice_payment_state"] = invoices[0].get("payment_state") or ""
        attrs["odoo_last_invoice_due"] = str(invoices[0].get("amount_residual") or 0)
        attrs["odoo_last_invoice_salesperson"] = _name(invoices[0].get("invoice_user_id"))

    if journal_entries:
        attrs["odoo_last_journal_entry"] = journal_entries[0].get("name") or ""
        attrs["odoo_last_journal_entry_date"] = journal_entries[0].get("date") or ""
        attrs["odoo_last_journal"] = _name(journal_entries[0].get("journal_id"))

    if courses:
        attrs["odoo_last_course"] = _name(courses[0].get("channel_id"))
        attrs["odoo_last_course_completion"] = str(courses[0].get("completion") or 0)

    return attrs
