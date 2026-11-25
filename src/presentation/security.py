import hashlib
import hmac

from fastapi import Header, HTTPException, status
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from src.core.config import get_settings


def _safe_equal(left: str, right: str) -> bool:
    """Comparaison en temps constant de deux chaînes."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


class AdminAuth(AuthenticationBackend):
    """Backend d'authentification du panneau SQLAdmin (identifiants issus de la config/Vault)."""

    async def login(self, request: Request) -> bool:
        """Valide les identifiants du formulaire et ouvre la session admin."""
        settings = get_settings()
        form = await request.form()
        username = str(form.get("username", ""))
        password = str(form.get("password", ""))
        if not settings.ADMIN_PASSWORD:
            return False
        if _safe_equal(username, settings.ADMIN_USERNAME) and _safe_equal(
            password, settings.ADMIN_PASSWORD
        ):
            request.session.update({"admin_token": self._token()})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        """Ferme la session admin."""
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        """Vérifie que la session contient un jeton admin valide."""
        token = request.session.get("admin_token", "")
        return bool(token) and _safe_equal(str(token), self._token())

    @staticmethod
    def _token() -> str:
        settings = get_settings()
        raw = f"{settings.SECRET_KEY}:{settings.ADMIN_USERNAME}:{settings.ADMIN_PASSWORD}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def require_admin_api_key(x_api_key: str = Header(default="")) -> None:
    """Dépendance FastAPI protégeant les endpoints d'administration par clé API."""
    expected = get_settings().ADMIN_API_KEY
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Endpoint d'administration désactivé : ADMIN_API_KEY non configurée.",
        )
    if not _safe_equal(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clé d'administration invalide.",
        )


async def require_partner_api_key(x_partner_key: str = Header(default="")) -> None:
    """Dépendance FastAPI protégeant l'espace partenaire (juristes référents) par clé dédiée."""
    expected = get_settings().PARTNER_API_KEY
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Espace partenaire désactivé : PARTNER_API_KEY non configurée.",
        )
    if not _safe_equal(x_partner_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clé d'accès partenaire invalide.",
        )
