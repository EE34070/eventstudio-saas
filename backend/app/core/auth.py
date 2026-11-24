"""Authentification : vérification serveur du JWT Clerk (signature JWKS, exp, iss, azp).

Clerk gère l'identité (e-mail, Google, 2FA facultative). Les rôles et l'appartenance
aux organisations sont gérés dans NOTRE base (collection memberships) : on reste
maître du modèle de droits et on peut changer de fournisseur d'identité sans migration.
"""
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status

from .config import Settings, get_settings


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str | None = None


_jwks_client: jwt.PyJWKClient | None = None


def _jwks(settings: Settings) -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(settings.CLERK_JWKS_URL, cache_keys=True, lifespan=3600)
    return _jwks_client


def _bearer(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentification requise")
    return header.removeprefix("Bearer ").strip()


async def current_principal(request: Request, settings: Settings = Depends(get_settings)) -> Principal:
    token = _bearer(request)
    try:
        key = _jwks(settings).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=settings.CLERK_ISSUER,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session invalide ou expirée")

    azp = claims.get("azp")
    if settings.CLERK_AUTHORIZED_PARTIES and azp not in settings.CLERK_AUTHORIZED_PARTIES:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Origine non autorisée")

    return Principal(user_id=claims["sub"], email=claims.get("email"))
