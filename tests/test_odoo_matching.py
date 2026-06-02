from app.services.odoo import _course_identity, _looks_like_course_line, _phone_tokens


def test_phone_tokens_include_egyptian_local_and_international_forms():
    tokens = set(_phone_tokens("+20 100 123 4567"))

    assert "201001234567" in tokens
    assert "01001234567" in tokens
    assert "1001234567" in tokens
    assert "001234567" in tokens


def test_course_line_detection_matches_event_course_descriptions():
    assert _looks_like_course_line("Management - PMP - Event PMP Course Online")


def test_course_identity_dedupes_sales_and_invoice_lines_for_same_course():
    sales_course = {"source": "sale_order_line", "channel_id": [109, "PMP Course Online"]}
    invoice_course = {"source": "invoice_line", "channel_id": [109, "PMP Course Online"]}

    assert _course_identity(sales_course) == _course_identity(invoice_course)
