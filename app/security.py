import hmac
import hashlib
import logging
from app.config import settings

logger = logging.getLogger("security")

DEFAULT_SECRET = "YOUR_API_KEY_HERE"

def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    """
    Verifies HMAC-SHA256 signature from X-PseudoGram-Signature header.
    Format: sha256=<hex_digest> or <hex_digest>
    Secret: settings.API_KEY or DEFAULT_SECRET
    """
    if not signature_header:
        return False

    provided = signature_header.strip()
    if provided.lower().startswith("sha256="):
        provided = provided[7:].strip()

    # Secret list to check
    secrets_to_check = [settings.API_KEY, DEFAULT_SECRET]
    
    for secret_str in secrets_to_check:
        if not secret_str:
            continue
        secret_bytes = secret_str.encode("utf-8")
        expected_hex = hmac.new(secret_bytes, raw_body, hashlib.sha256).hexdigest()
        
        if hmac.compare_digest(expected_hex.lower(), provided.lower()):
            return True

    logger.warning(f"Signature mismatch. Provided: '{signature_header[:20]}...'")
    return False
