"""Unit tests for the Milestone 4 webhook HMAC helpers."""

from app.core.security import SIGNATURE_HEADER, sign_payload, verify_signature


SECRET = "test-secret-value"
BODY = b'{"batch_id":"abc","frames":[]}'


def test_signature_header_constant() -> None:
    assert SIGNATURE_HEADER == "X-HoopStar-Signature"


def test_sign_payload_is_deterministic_and_prefixed() -> None:
    first = sign_payload(SECRET, BODY)
    second = sign_payload(SECRET, BODY)
    assert first == second
    assert first.startswith("sha256=")


def test_verify_signature_round_trip() -> None:
    signature = sign_payload(SECRET, BODY)
    assert verify_signature(SECRET, BODY, signature) is True


def test_verify_signature_rejects_tampered_body() -> None:
    signature = sign_payload(SECRET, BODY)
    assert verify_signature(SECRET, BODY + b"x", signature) is False


def test_verify_signature_rejects_wrong_secret() -> None:
    signature = sign_payload(SECRET, BODY)
    assert verify_signature("other-secret", BODY, signature) is False


def test_verify_signature_rejects_missing_signature() -> None:
    assert verify_signature(SECRET, BODY, None) is False
    assert verify_signature(SECRET, BODY, "") is False
