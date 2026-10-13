import hashlib
import hmac

from src.infrastructure.whatsapp.security import verify_whatsapp_signature


def test_verify_whatsapp_signature_valid():
    secret = "my_meta_secret_123"
    body = b'{"object": "whatsapp_business_account"}'
    valid_hash = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    header = f"sha256={valid_hash}"

    assert verify_whatsapp_signature(body, header, secret) is True


def test_verify_whatsapp_signature_tampered_body():
    secret = "my_meta_secret_123"
    body = b'{"object": "whatsapp_business_account"}'
    valid_hash = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    header = f"sha256={valid_hash}"

    tampered_body = b'{"object": "whatsapp_tampered"}'
    assert verify_whatsapp_signature(tampered_body, header, secret) is False


def test_verify_whatsapp_signature_missing_header():
    secret = "my_meta_secret_123"
    assert verify_whatsapp_signature(b"data", None, secret) is False
    assert verify_whatsapp_signature(b"data", "", secret) is False
    assert verify_whatsapp_signature(b"data", "invalid_format", secret) is False
