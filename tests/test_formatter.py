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
            "user_id": [22, "Mona Sales"],
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
                "user_id": [22, "Mona Sales"],
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
                "invoice_user_id": [22, "Mona Sales"],
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
    assert "Mona Sales" in note
    assert attrs["odoo_match_found"] is True
    assert attrs["odoo_partner_id"] == "5"
    assert attrs["odoo_partner_salesperson"] == "Mona Sales"
    assert attrs["odoo_last_order_salesperson"] == "Mona Sales"
    assert attrs["odoo_last_invoice_salesperson"] == "Mona Sales"
    assert attrs["odoo_invoices_count"] == 1
    assert attrs["odoo_courses_count"] == 1


def test_formats_sales_order_line_course_without_fake_progress():
    snapshot = {
        "partner": {
            "id": 5,
            "name": "Alice",
            "email": "alice@example.com",
            "phone": False,
            "mobile": False,
            "company_name": False,
            "commercial_partner_id": [5, "Alice"],
        },
        "leads": [],
        "orders": [],
        "invoices": [],
        "courses": [
            {
                "id": "sale_order_line:1",
                "source_label": "Sales course line",
                "channel_id": [109, "Management - PMP - Event"],
                "member_status": "sale",
                "completion": None,
                "order_name": "S14794",
                "quantity": 1,
            }
        ],
    }

    note = format_customer_note(snapshot, lookup_email="alice@example.com", lookup_phone=None)

    assert "Management - PMP - Event" in note
    assert "order: S14794" in note
    assert "0% complete" not in note


def test_formats_restricted_sections_without_implying_zero_records():
    snapshot = {
        "partner": {
            "id": 5,
            "name": "Alice",
            "email": "alice@example.com",
            "phone": False,
            "mobile": False,
            "company_name": False,
            "commercial_partner_id": [5, "Alice"],
        },
        "leads": [],
        "orders": [],
        "invoices": [],
        "courses": [],
        "restricted_sections": ["orders", "invoices"],
    }

    note = format_customer_note(snapshot, lookup_email="alice@example.com", lookup_phone=None)

    assert "Recent sales orders: restricted" in note
    assert "Recent invoices: restricted" in note
