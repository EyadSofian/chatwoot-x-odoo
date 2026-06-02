from app.services.odoo import _looks_like_course_line, _phone_tokens


def test_phone_tokens_include_egyptian_local_and_international_forms():
    tokens = set(_phone_tokens("+20 100 123 4567"))

    assert "201001234567" in tokens
    assert "01001234567" in tokens
    assert "1001234567" in tokens
    assert "001234567" in tokens


def test_course_line_detection_matches_event_course_descriptions():
    assert _looks_like_course_line("Management - PMP - Event PMP Course Online")
