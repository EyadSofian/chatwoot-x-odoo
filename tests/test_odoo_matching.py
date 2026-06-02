from app.services.odoo import _phone_tokens


def test_phone_tokens_include_egyptian_local_and_international_forms():
    tokens = set(_phone_tokens("+20 100 123 4567"))

    assert "201001234567" in tokens
    assert "01001234567" in tokens
    assert "1001234567" in tokens
    assert "001234567" in tokens
