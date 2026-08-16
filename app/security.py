import hmac
import hashlib
import logging
from app.config import settings

logger = logging.getLogger("security")

def verify_webhook_signature(raw_body: bytes, signature_header: str) -> bool:
    """
    Verifies HMAC-SHA256 signature from X-PseudoGram-Signature header.
    Format: sha256=<hex_digest> or <hex_digest>
    Secret: settings.API_KEY (read strictly from environment)
    """
    if not signature_header or not settings.API_KEY:
        logger.warning("Missing signature header or API_KEY environment variable.")
        return False

    provided = signature_header.strip()
    if provided.lower().startswith("sha256="):
        provided = provided[7:].strip()

    secret_bytes = settings.API_KEY.encode("utf-8")
    expected_hex = hmac.new(secret_bytes, raw_body, hashlib.sha256).hexdigest()

    if hmac.compare_digest(expected_hex.lower(), provided.lower()):
        return True

    logger.warning(f"Signature mismatch. Header: '{signature_header[:20]}...'")
    return False
