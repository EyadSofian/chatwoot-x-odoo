from app.services.formatter import conversation_attributes, format_customer_note


def test_formats_missing_partner_note():
    note = format_customer_note({}, lookup_email="nobody@example.com", lookup_phone=None)

    assert "No matching Odoo contact" in note


def test_formats_snapshot_and_attributes():
    snapshot = {
        "partner": {
            "id": 5,
            "name": "Alice",
            "email": "alice@example.com",
            "phone": "+201001112223",
            "mobile": False,
            "company_name": "Acme",
            "commercial_partner_id": [5, "Acme"],
        },
        "leads": [{"id": 9, "name": "Website lead", "stage_id": [1, "New"]}],
        "orders": [
            {
                "id": 3,
                "name": "S0003",
                "state": "sale",
                "amount_total": 1200,
                "currency_id": [74, "EGP"],
                "invoice_status": "to invoice",
                "lines": [{"product_id": [4, "Service"], "product_uom_qty": 2, "price_subtotal": 1200}],
            }
        ],
        "invoices": [
            {
                "id": 11,
                "name": "INV/2026/0001",
                "state": "posted",
                "payment_state": "partial",
                "amount_total": 900,
                "amount_residual": 300,
                "currency_id": [74, "EGP"],
                "lines": [{"product_id": [8, "Course"], "quantity": 1, "price_subtotal": 900}],
            }
        ],
        "courses": [
            {
                "id": 12,
                "channel_id": [6, "Sales Masterclass"],
                "member_status": "joined",
                "completion": 67,
                "completed_slides_count": 8,
                "next_slide_id": [10, "Final quiz"],
            }
        ],
    }

    note = format_customer_note(snapshot, lookup_email="alice@example.com", lookup_phone=None)
    attrs = conversation_attributes(snapshot)

    assert "Alice" in note
    assert "S0003" in note
    assert "INV/2026/0001" in note
    assert "Sales Masterclass" in note
    assert attrs["odoo_match_found"] is True
    assert attrs["odoo_partner_id"] == "5"
    assert attrs["odoo_invoices_count"] == 1
    assert attrs["odoo_courses_count"] == 1
