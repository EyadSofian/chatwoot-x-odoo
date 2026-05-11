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
    leads = snapshot.get("leads", [])
    orders = snapshot.get("orders", [])

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
            f"Company: {partner.get('company_name') or _name(partner.get('commercial_partner_id'))}",
        ]
    )

    lines.append("")
    lines.append(f"CRM leads/opportunities: {len(leads)}")
    if leads:
        for lead in leads[:5]:
            stage = _name(lead.get("stage_id"))
            revenue = _money(lead.get("expected_revenue"))
            lines.append(f"- #{lead.get('id')} {lead.get('name') or '-'} | {stage} | {revenue}")

    lines.append("")
    lines.append(f"Recent sales orders: {len(orders)}")
    if orders:
        for order in orders[:5]:
            state = order.get("state") or "-"
            total = _money(order.get("amount_total"), order.get("currency_id"))
            invoice_status = order.get("invoice_status") or "-"
            lines.append(f"- {order.get('name')} | {state} | {total} | invoice: {invoice_status}")
            for order_line in order.get("lines", [])[:3]:
                product = _name(order_line.get("product_id"))
                qty = order_line.get("product_uom_qty") or 0
                subtotal = _money(order_line.get("price_subtotal"), order.get("currency_id"))
                lines.append(f"  * {product} x {qty}: {subtotal}")

    return "\n".join(lines)


def conversation_attributes(snapshot: dict[str, Any]) -> dict[str, Any]:
    partner = snapshot.get("partner")
    leads = snapshot.get("leads", [])
    orders = snapshot.get("orders", [])

    attrs: dict[str, Any] = {
        "odoo_match_found": bool(partner),
        "odoo_leads_count": len(leads),
        "odoo_orders_count": len(orders),
    }

    if partner:
        attrs["odoo_partner_id"] = str(partner.get("id"))
        attrs["odoo_partner_name"] = partner.get("name") or ""

    if orders:
        attrs["odoo_last_order"] = orders[0].get("name") or ""
        attrs["odoo_last_order_state"] = orders[0].get("state") or ""
        attrs["odoo_last_order_total"] = str(orders[0].get("amount_total") or 0)

    return attrs

