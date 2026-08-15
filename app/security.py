import hmac
import hashlib
from fastapi import Request, HTTPException, status
from app.config import settings

def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    """
    Verifies HMAC-SHA256 signature from X-PseudoGram-Signature header.
    Format: sha256=<hex_digest>
    Secret: settings.API_KEY
    """
    if not signature_header:
        return False

    parts = signature_header.split("=")
    if len(parts) != 2 or parts[0].lower() != "sha256":
        return False

    provided_signature = parts[1].strip()

    # Secret is the API key
    secret = settings.API_KEY.encode("utf-8")
    expected_signature = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected_signature, provided_signature)
