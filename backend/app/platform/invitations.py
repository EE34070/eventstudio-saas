"""Invitations des comptes externes (mariés, clients, prestataires, organisateurs).

Un module interne crée une invitation (create_invitation) : e-mail, rôle externe,
contact rattaché et « scope » propre au module (ex. {"wedding_id": ...}).
L'invité reçoit un lien /invitation/<jeton>, se connecte (Clerk), puis le frontend
appelle POST /api/invitations/accept : la membership est créée dans la base plateforme.

- Le jeton n'est stocké que haché (sha256) ; il expire après 30 jours.
- Un module peut enregistrer un « hook » appelé à l'acceptation (notification, statut).
"""
import hashlib
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.auth import Principal, current_principal
from app.core.entitlements import resolve
from app.core.rbac import Role
from app.core.tenancy import TenantContext

router = APIRouter(prefix="/invitations", tags=["invitations"])

EXTERNAL_ROLES = {Role.CLIENT, Role.PARTNER, Role.ORGANIZER}
TTL = timedelta(days=30)

AcceptHook = Callable[[TenantContext, dict], Awaitable[None]]
_HOOKS: dict[str, AcceptHook] = {}


def register_accept_hook(module: str, fn: AcceptHook) -> None:
    _HOOKS[module] = fn


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _control(request: Request):
    return request.app.state.router.control


async def create_invitation(request: Request, ctx: TenantContext, *, email: str, role: Role, module: str,
                            contact_id: str, scope: dict, lang: str = "fr") -> tuple[dict, str]:
    """Crée (ou renouvelle) l'invitation d'un compte externe. Renvoie (invitation, jeton en clair)."""
    if role not in EXTERNAL_ROLES:
        raise ValueError("Seuls les rôles externes passent par une invitation")
    control = _control(request)
    token = secrets.token_urlsafe(32)
    key = {"org_id": ctx.org_id, "module": module, "contact_id": contact_id}
    existing = await control.invitations.find_one({**key, "status": {"$in": ["pending", "accepted"]}})
    if existing and existing["status"] == "accepted" and existing.get("email") == email.lower():
        return existing, ""
    doc = {
        **key, "email": email.lower(), "role": str(role), "scope": scope, "lang": lang,
        "token_hash": _hash(token), "status": "pending", "invited_by": ctx.user_id,
        "created_at": _now(), "expires_at": _now() + TTL, "sent_count": 1,
    }
    if existing:
        if existing["status"] == "pending":
            doc["sent_count"] = existing.get("sent_count", 1) + 1
        await control.invitations.update_one({"_id": existing["_id"]}, {"$set": doc})
        doc["_id"] = existing["_id"]
    else:
        doc["_id"] = uuid4().hex
        await control.invitations.insert_one(doc)
    return doc, token


async def invitation_statuses(request: Request, org_id: str, module: str, contact_ids: list[str]) -> dict[str, dict]:
    """Statut des invitations par contact, pour l'écran « Compte et droits »."""
    out: dict[str, dict] = {}
    async for inv in _control(request).invitations.find(
        {"org_id": org_id, "module": module, "contact_id": {"$in": contact_ids}}
    ):
        out[inv["contact_id"]] = {"status": inv["status"], "email": inv["email"],
                                  "sent_count": inv.get("sent_count", 1), "accepted_at": inv.get("accepted_at")}
    return out


class AcceptIn(BaseModel):
    token: str


class InvitationPreview(BaseModel):
    org_name: str
    role: str
    email: str
    lang: str
    status: str


@router.get("/{token}", response_model=InvitationPreview)
async def preview(token: str, request: Request):
    """Lecture publique minimale (avant connexion) : nom de l'organisation et langue de la page d'accueil."""
    control = _control(request)
    inv = await control.invitations.find_one({"token_hash": _hash(token)})
    if not inv:
        raise HTTPException(404, "Invitation introuvable")
    org = await control.orgs.find_one({"_id": inv["org_id"]}) or {}
    status = "expired" if inv["status"] == "pending" and _aware(inv["expires_at"]) < _now() else inv["status"]
    return InvitationPreview(org_name=org.get("name", ""), role=inv["role"], email=inv["email"],
                             lang=inv.get("lang", "fr"), status=status)


@router.post("/accept")
async def accept(body: AcceptIn, request: Request, principal: Principal = Depends(current_principal)):
    control = _control(request)
    inv = await control.invitations.find_one({"token_hash": _hash(body.token)})
    if not inv or inv["status"] == "revoked":
        raise HTTPException(404, "Invitation introuvable")
    if inv["status"] == "accepted":
        if inv.get("user_id") == principal.user_id:
            return {"org_id": inv["org_id"]}
        raise HTTPException(409, "Invitation déjà utilisée")
    if _aware(inv["expires_at"]) < _now():
        raise HTTPException(410, "Invitation expirée : demandez un nouvel envoi")
    if principal.email and principal.email.lower() != inv["email"]:
        raise HTTPException(403, "Cette invitation a été envoyée à une autre adresse e-mail")

    existing = await control.memberships.find_one({"user_id": principal.user_id, "org_id": inv["org_id"]})
    if existing and existing.get("role") not in {r.value for r in EXTERNAL_ROLES}:
        raise HTTPException(409, "Ce compte est déjà membre de l'équipe de cette organisation")
    await control.memberships.update_one(
        {"user_id": principal.user_id, "org_id": inv["org_id"]},
        {"$set": {"role": inv["role"], "status": "active", "contact_id": inv["contact_id"],
                  "scope": inv.get("scope", {}), "module": inv["module"]},
         "$setOnInsert": {"created_at": _now()}},
        upsert=True,
    )
    await control.invitations.update_one(
        {"_id": inv["_id"]}, {"$set": {"status": "accepted", "user_id": principal.user_id, "accepted_at": _now()}}
    )

    hook = _HOOKS.get(inv["module"])
    org = await control.orgs.find_one({"_id": inv["org_id"]})
    if hook and org:
        ctx = TenantContext(org_id=org["_id"], user_id=principal.user_id, role=Role(inv["role"]),
                            permissions=set(), entitlements=resolve(org), org=org,
                            db=request.app.state.router.tenant(org))
        await hook(ctx, inv)
    return {"org_id": inv["org_id"]}
