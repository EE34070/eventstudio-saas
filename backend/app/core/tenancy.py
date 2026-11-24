"""Contexte d'organisation (tenant).

L'organisation active est choisie par le frontend via l'en-tête X-Org-Id
(sélecteur d'organisation), MAIS elle n'est jamais crue sur parole : le serveur
vérifie que l'utilisateur authentifié a une membership active dans cette organisation.
Sans en-tête, on prend la première membership active (cas général : une seule org).
"""
from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from .auth import Principal, current_principal
from .db import ClusterRouter, get_router
from .entitlements import Entitlements, resolve
from .rbac import INTERNAL_ROLES, Role, has_permission, permissions_for


@dataclass
class TenantContext:
    org_id: str
    user_id: str
    role: Role
    permissions: set[str]
    entitlements: Entitlements
    org: dict = field(repr=False, default_factory=dict)
    membership: dict = field(repr=False, default_factory=dict)
    db: AsyncIOMotorDatabase | None = field(repr=False, default=None)  # base de CETTE société

    @property
    def is_internal(self) -> bool:
        return self.role in INTERNAL_ROLES

    def can(self, perm: str) -> bool:
        return has_permission(self.permissions, perm)


async def tenant_context(
    request: Request,
    principal: Principal = Depends(current_principal),
    router: ClusterRouter = Depends(get_router),
) -> TenantContext:
    db = router.control
    requested = request.headers.get("X-Org-Id")
    query = {"user_id": principal.user_id, "status": "active"}
    if requested:
        query["org_id"] = requested
    membership = await db.memberships.find_one(query, sort=[("created_at", 1)])
    if not membership:
        # 403 identique que l'org existe ou non : on ne révèle pas l'existence d'une organisation
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Accès à cette organisation refusé")

    org = await db.orgs.find_one({"_id": membership["org_id"], "deleted_at": None})
    if not org or org.get("provisioning") != "ready":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Accès à cette organisation refusé")

    role = Role(membership["role"])
    perms = permissions_for(role, membership.get("extra_permissions"), membership.get("revoked_permissions"))
    ent = resolve(org)

    # Restriction optionnelle des modules par membre (ex. un commercial sans Finance)
    allowed = membership.get("modules")
    if allowed is not None:
        ent = Entitlements(ent.plan, ent.modules & set(allowed), ent.limits, ent.status)

    return TenantContext(
        org_id=org["_id"], user_id=principal.user_id, role=role,
        permissions=perms, entitlements=ent, org=org, membership=membership,
        db=router.tenant(org),
    )


def guard(module: str, perm: str = "read"):
    """Dépendance FastAPI unique pour toute route métier : module actif + permission + écriture autorisée."""

    async def _dep(request: Request, ctx: TenantContext = Depends(tenant_context)) -> TenantContext:
        if not ctx.entitlements.has_module(module):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Module « {module} » non inclus dans votre offre")
        if not ctx.can(f"{module}:{perm}"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission insuffisante")
        if request.method not in {"GET", "HEAD", "OPTIONS"} and ctx.entitlements.read_only:
            raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "Abonnement inactif : lecture seule")
        request.state.tenant = ctx  # pour l'audit et les logs
        return ctx

    return _dep
