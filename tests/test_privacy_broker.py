from agent.privacy_broker import PrivacyBroker


def test_privacy_broker_tokenizes_identifiers() -> None:
    broker = PrivacyBroker(names=("Alice",))
    result = broker.tokenize("Pay Alice 100 at alice@example.com +8613800138000")
    assert "Alice" not in result.text
    assert "alice@example.com" not in result.text
    assert "13800138000" not in result.text
    assert "[PERSON_1]" in result.text
    assert "[EMAIL_1]" in result.text
    assert "[PHONE_1]" in result.text
    assert result.replacements["[PERSON_1]"] == "Alice"


def test_privacy_broker_rejects_reserved_placeholders() -> None:
    broker = PrivacyBroker()
    try:
        broker.tokenize("send to $R1")
    except ValueError as exc:
        assert "reserved" in str(exc)
    else:
        raise AssertionError("reserved placeholder was accepted")
