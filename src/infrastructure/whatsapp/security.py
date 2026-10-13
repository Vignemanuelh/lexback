import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


def verify_whatsapp_signature(
    payload_bytes: bytes,
    signature_header: str | None,
    app_secret: str,
) -> bool:
    """Vérifie la signature cryptographique X-Hub-Signature-256 émise par Meta.

    Args:
        payload_bytes: Corps brut de la requête HTTP en octets.
        signature_header: En-tête X-Hub-Signature-256 (format: 'sha256=<hex_hash>').
        app_secret: Clé secrète de l'application Meta WhatsApp Cloud API.

    Returns:
        True si la signature est valide, False sinon.
    """
    if not signature_header or not app_secret:
        logger.warning("Vérification signature impossible: en-tête ou app_secret manquant.")
        return False

    if not signature_header.startswith("sha256="):
        logger.warning("Format d'en-tête de signature non conforme (préfixe sha256= attendu).")
        return False

    expected_hash = signature_header[len("sha256=") :]
    computed_hash = hmac.new(
        key=app_secret.encode("utf-8"),
        msg=payload_bytes,
        digestmod=hashlib.sha256,
    ).hexdigest()

    is_valid = hmac.compare_digest(expected_hash, computed_hash)
    if not is_valid:
        logger.warning("Signature X-Hub-Signature-256 invalide, rejet de la requête.")
    return is_valid
