"""Durcissement HTTP, chiffrement des secrets d'intégration, clés de stockage."""
import re
from uuid import uuid4

from cryptography.fernet import Fernet
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get_settings

SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        return response


# --- Secrets d'intégration (Gmail, WhatsApp, Yousign, Pennylane, Meta, banque…) ---
# Stockés par organisation, chiffrés au repos, jamais renvoyés au frontend.

def _fernet() -> Fernet:
    key = get_settings().ENCRYPTION_KEY
    if not key:
        raise RuntimeError("ENCRYPTION_KEY manquante")
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


# --- Fichiers : clé R2 toujours préfixée par l'organisation ---------------------

_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def storage_key(org_id: str, module: str, filename: str) -> str:
    """org/{org_id}/{module}/{uuid}-{nom-nettoyé} — le nom d'origine est conservé en base."""
    clean = _SAFE.sub("-", filename)[-80:] or "fichier"
    return f"org/{org_id}/{module}/{uuid4().hex}-{clean}"


def assert_key_in_org(key: str, org_id: str) -> None:
    if not key.startswith(f"org/{org_id}/"):
        raise PermissionError("Fichier hors de l'organisation")
