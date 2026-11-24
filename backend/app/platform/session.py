"""/api/me : tout ce dont le frontend a besoin pour construire l'interface.

Le frontend ne décide de rien : il affiche les modules et actions que le serveur
lui renvoie ici. Le contrôle réel reste fait route par route par guard().
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.auth import Principal, current_principal
from app.core.db import get_control_db
from app.core.modules import registry
from app.core.tenancy import TenantContext, tenant_context

router = APIRouter(tags=["session"])


class OrgSummary(BaseModel):
    id: str
    name: str
    role: str


class ModuleInfo(BaseModel):
    key: str
    name: str
    category: str
    status: str
    can_write: bool


class MeOut(BaseModel):
    user_id: str
    org: OrgSummary
    orgs: list[OrgSummary]           # pour le sélecteur d'organisation
    plan: str
    subscription_status: str
    limits: dict[str, int]
    modules: list[ModuleInfo]
    branding: dict


@router.get("/me", response_model=MeOut)
async def me(
    principal: Principal = Depends(current_principal),
    ctx: TenantContext = Depends(tenant_context),
    db=Depends(get_control_db),
):
    memberships = await db.memberships.find({"user_id": principal.user_id, "status": "active"}).to_list(None)
    org_ids = [m["org_id"] for m in memberships]
    orgs = {o["_id"]: o for o in await db.orgs.find({"_id": {"$in": org_ids}, "deleted_at": None}).to_list(None)}

    reg = registry()
    modules = [
        ModuleInfo(key=k, name=reg[k].name, category=reg[k].category, status=reg[k].status,
                   can_write=ctx.can(f"{k}:write") and not ctx.entitlements.read_only)
        for k in sorted(ctx.entitlements.modules)
        if ctx.can(f"{k}:read")
    ]
    return MeOut(
        user_id=principal.user_id,
        org=OrgSummary(id=ctx.org_id, name=ctx.org["name"], role=ctx.role),
        orgs=[OrgSummary(id=m["org_id"], name=orgs[m["org_id"]]["name"], role=m["role"])
              for m in memberships if m["org_id"] in orgs],
        plan=ctx.entitlements.plan,
        subscription_status=ctx.entitlements.status,
        limits=ctx.entitlements.limits,
        modules=modules if ctx.is_internal else [],
        branding=ctx.org.get("branding", {}),
    )


@router.get("/modules/catalog")
async def module_catalog():
    """Catalogue public des modules (page tarifs, onboarding)."""
    return [
        {"key": m.key, "name": m.name, "category": m.category, "description": m.description,
         "status": m.status, "depends_on": m.depends_on, "market": m.market}
        for m in registry().values()
    ]


@router.get("/orgs/current/settings")
async def get_settings_route(ctx: TenantContext = Depends(tenant_context)):
    if not ctx.can("settings:read"):
        raise HTTPException(403, "Permission insuffisante")
    org = dict(ctx.org)
    org.pop("integrations", None)  # secrets chiffrés : jamais exposés
    org["id"] = org.pop("_id")
    return org
