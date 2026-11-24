"""Portails externes : clients, prestataires (DJ, staff), organisateurs.

Routes séparées des routes internes (/api/portal/*) et schémas de sortie dédiés :
un portail ne renvoie JAMAIS prix d'achat, marges, notes internes ni coordonnées
d'autres prestataires. Un prestataire peut appartenir à plusieurs organisations
avec un seul compte (une membership par organisation, rôle "partner").
"""
from fastapi import APIRouter, Depends, HTTPException

from app.core.rbac import Role
from app.core.repository import TenantRepository
from app.core.tenancy import TenantContext, tenant_context

router = APIRouter(prefix="/portal", tags=["portal"])

PUBLIC_EVENT_FIELDS = ("title", "title_i18n", "starts_at", "ends_at", "status", "enabled_modules")


@router.get("/events")
async def my_events(ctx: TenantContext = Depends(tenant_context)):
    if ctx.role not in {Role.CLIENT, Role.PARTNER, Role.ORGANIZER}:
        raise HTTPException(403, "Réservé aux espaces externes")
    contact_id = ctx.membership.get("contact_id")
    field = {Role.CLIENT: "client_id", Role.ORGANIZER: "organizer_id", Role.PARTNER: "assigned_partner_ids"}[ctx.role]
    docs = await TenantRepository(ctx, "events").find({field: contact_id}, sort=[("starts_at", 1)])
    return [{"id": d["_id"], **{k: d.get(k) for k in PUBLIC_EVENT_FIELDS}} for d in docs]
