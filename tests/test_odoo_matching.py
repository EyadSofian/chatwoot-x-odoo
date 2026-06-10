from app.services.odoo import (
    OdooClient,
    _course_identity,
    _looks_like_course_line,
    _normalize_search_text,
    _phone_search_fragments,
    _phone_tokens,
)
from app.config import Settings


def test_phone_tokens_include_egyptian_local_and_international_forms():
    tokens = set(_phone_tokens("+20 100 123 4567"))

    assert "201001234567" in tokens
    assert "01001234567" in tokens
    assert "1001234567" in tokens
    assert "001234567" in tokens


def test_phone_search_fragments_include_short_suffix_for_formatted_odoo_numbers():
    fragments = set(_phone_search_fragments("+20 100 123 4567"))

    assert "1234567" in fragments
    assert "4567" in fragments


def test_course_line_detection_matches_event_course_descriptions():
    assert _looks_like_course_line("Management - PMP - Event PMP Course Online")


def test_course_identity_dedupes_sales_and_invoice_lines_for_same_course():
    sales_course = {"source": "sale_order_line", "channel_id": [109, "PMP Course Online"]}
    invoice_course = {"source": "invoice_line", "channel_id": [109, "PMP Course Online"]}

    assert _course_identity(sales_course) == _course_identity(invoice_course)


def test_arabic_name_normalization_handles_hamza_and_taa_marbuta():
    assert _normalize_search_text("\u0623\u062d\u0645\u062f \u062e\u0644\u064a\u0641\u0629") == "\u0627\u062d\u0645\u062f \u062e\u0644\u064a\u0641\u0647"


def test_full_arabic_name_scores_above_generic_first_name():
    client = OdooClient(Settings.from_env())
    query = (
        "\u062d\u0633\u064a\u0646 \u0627\u0644\u064a\u0627\u0633 "
        "\u062e\u0644\u064a\u0641\u0629 \u0623\u062d\u0645\u062f"
    )
    exact = client._score_partner(
        {
            "name": (
                "\u062d\u0633\u064a\u0646 \u0627\u0644\u064a\u0627\u0633 "
                "\u062e\u0644\u064a\u0641\u0647 \u0627\u062d\u0645\u062f"
            )
        },
        query=query,
        email=None,
        phone=None,
    )
    generic = client._score_partner(
        {"name": "\u062d\u0633\u064a\u0646"},
        query=query,
        email=None,
        phone=None,
    )

    assert exact > generic
