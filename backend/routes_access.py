"""Profils d'accès configurables : remplacent les rôles fixes une fois activés pour la société."""
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

import access_grid as ag
from core import SENSITIVE, ALL_PERMS, IN_ENV, PERMS, ROLES, Ctx, audit, current_member, db, need, new_id, now_iso, perms_of, profile_of

router = APIRouter(prefix="/api")
UM = need("users:manage")
READS = sorted(p for p in ALL_PERMS if p.endswith(":read"))
DEFAULTS = [("Administrateur", "Administrator", "admin", None, "all", True), ("Gérant", "Manager", "gerant", None, "all", False),
            ("Chargé de projet", "Project manager", "chef_projet", None, "all", False), ("Commercial", "Sales", "commercial", None, "all", False),
            ("Comptabilité", "Accounting", "comptable", None, "all", False), ("Technicien / chauffeur", "Technician / driver", "technicien", None, "assigned", False),
            ("Logistique / dépôt", "Logistics / warehouse", "", ["events:read", "catalog:read", "catalog:write", "venues:read", "team:read"], "all", False),
            ("Lecture seule", "Read only", "", READS, "all", False)]


class ProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    name_en: str = Field("", max_length=80)
    description: str = Field("", max_length=300)
    perms: List[str] = Field([], max_length=60)
    scope: Literal["all", "assigned"] = "all"
    sensitive: Dict[str, Any] = {}
    permissions: Optional[Dict[str, Dict[str, Any]]] = None
    require_2fa: Literal["optional", "required"] = "optional"


SWITCHES = ("send_client_messages", "send_quotes_invoices")


def _sens(body: ProfileIn) -> dict:
    lim = body.sensitive.get("expense_validation_limit")
    return {**{k: body.sensitive.get(k) is not False for k in SENSITIVE + SWITCHES}, "finance_costs": body.sensitive.get("finance_costs") is True, "expense_validation_limit": float(lim) if isinstance(lim, (int, float)) and lim > 0 else None}


def _rights(ctx: Ctx, body: ProfileIn) -> dict:
    if body.permissions is None:
        perms = _guard(ctx, body.perms)
        grid = ag.grid_from(perms, body.scope)
    else:
        grid = ag.clean(body.permissions)
        perms = _guard(ctx, sorted(ag.derive(grid)))
    if body.sensitive.get("finance_costs") is True and not ctx.can("finance:costs"):
        raise HTTPException(403, "Vous ne pouvez pas accorder un droit que vous n'avez pas")
    return {"perms": perms, "permissions": grid, "scope": grid["events"]["scope"], "sensitive": _sens(body)}


def _diff(a: dict, b: dict) -> str:
    out = [f"{m}.{k} : {(a.get(m) or {}).get(k)} → {v}" for m, row in b.items() for k, v in row.items() if (a.get(m) or {}).get(k) != v]
    return ", ".join(out) or "grille inchangée"


async def migrate() -> None:
    await db.access_profiles.update_many({"base_role": "gerant", "sensitive.finance_costs": {"$exists": False}}, {"$set": {"sensitive.finance_costs": True}})
    async for p in db.access_profiles.find({"permissions": {"$exists": False}}, {"_id": 0}):
        await db.access_profiles.update_one({"id": p["id"]}, {"$set": {"permissions": ag.grid_from(p.get("perms") or [], p.get("scope") or "all"), "require_2fa": "optional"}})


# ---------- Données sensibles : filtrage des réponses en un seul endroit ----------
KEYS = {"sale_prices": {"quote_ht", "quote_ttc", "import_gap", "import_total_ht", "total_ttc", "total_ht", "total_vat", "vat_breakdown", "unit_price", "price_day", "price", "amount", "amount_ht", "amount_ttc", "balance_due", "deposit_paid", "deposit_amount", "paid_amount",
                        "budget", "budget_amount", "budget_min", "budget_max", "balance", "total", "total_due", "totals", "line_total", "price_m2", "price_per_secondary_uom"},
        "costs_margins": {"cost", "cost_ht", "costs_total", "purchase_price", "margin", "margin_ht", "margin_percent", "rate", "rate_basis", "purchases_total", "purchases_overdue", "cost_km", "fees", "base_rate", "extra_hour_rate", "day_rate", "hourly_rate",
                          "unit_cost", "cost_history", "suppliers", "supplier_name", "cost_total", "amount_base", "amount_overtime", "amount_expenses", "amount_services", "amount_equipment"},
        "client_contacts": {"email", "phone", "address", "zip", "city", "instagram_handle", "client_email", "client_phone", "sent_to"},
        "hr_data": {"iban", "ssn", "iban_encrypted", "ssn_encrypted", "iban_last4", "salary", "birth_date", "birth_place", "contract_file"}}
CLIENT_PATHS = ("/api/contacts", "/api/events", "/api/quotes", "/api/invoices", "/api/crm", "/api/search")
DOC_PATHS = ("quotes", "invoices", "finance", "export", "accounting")


def _scrub(v, keys: set):
    if isinstance(v, list):
        return [_scrub(x, keys) for x in v]
    if isinstance(v, dict):
        return {k: ([] if isinstance(x, list) else {}) if k in keys and isinstance(x, (list, dict)) else _scrub(x, keys) for k, x in v.items() if not (k in keys and not isinstance(x, (list, dict)))}
    return v


async def scrub_mw(request: Request, call_next):
    resp = await call_next(request)
    hide, path = getattr(request.state, "hide", None), request.url.path
    from security import COST_KEYS
    cost = COST_KEYS if getattr(request.state, "no_cost", False) else set()
    if not (hide or cost) or path.startswith(("/api/me", "/api/access-profiles", "/api/team", "/api/users")):
        return resp
    hide = hide or set()
    ct = resp.headers.get("content-type", "")
    if "application/json" not in ct:
        if hide & {"sale_prices", "costs_margins"} and any(x in ct for x in ("pdf", "csv", "spreadsheet", "zip")) and any(x in path for x in DOC_PATHS):
            return JSONResponse({"detail": "Document non disponible avec votre profil d'accès (montants masqués)"}, status_code=403)
        return resp
    body = b"".join([c async for c in resp.body_iterator])
    headers = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-length", "content-type")}
    try:
        data = json.loads(body)
    except ValueError:
        return Response(body, status_code=resp.status_code, headers=headers, media_type=ct)
    keys = set().union(*(KEYS[h] for h in hide if h != "client_contacts" or path.startswith(CLIENT_PATHS))) | cost
    return JSONResponse(_scrub(data, keys), status_code=resp.status_code, headers=headers)


@router.get("/me/permissions")
async def my_permissions(member: dict = Depends(current_member)):
    prof = await profile_of(member)
    return {"profile": {"id": prof["id"], "name": prof["name"]} if prof else None, "perms": sorted(perms_of(member, prof)), "scope": (prof or {}).get("scope") or ("assigned" if member.get("role") == "technicien" else "all")}


async def _staff(ctx: Ctx) -> list:
    return await db.users.find({"org_id": ctx.org_id, "role": {"$in": ROLES}, **IN_ENV}, {"_id": 0, "user_id": 1, "name": 1, "email": 1, "role": 1, "access_profile_id": 1, "status": 1, "permission_overrides": 1, "team_id": 1, "last_login_at": 1, "two_factor": 1}).to_list(1000)


@router.get("/access-profiles")
async def list_profiles(ctx: Ctx = Depends(UM)):
    profs, users = await ctx.list("access_profiles", sort=[("created_at", 1)]), await _staff(ctx)
    ends = {t["id"]: t.get("end_date") or "" for t in await ctx.list("team", {"id": {"$in": [u["team_id"] for u in users if u.get("team_id")]}})}
    for u in users:
        u["end_date"], u["status"] = ends.get(u.get("team_id"), ""), u.get("status") or "active"
    for p in profs:
        p["members"] = sum(u.get("access_profile_id") == p["id"] for u in users)
        if p.get("locked"):
            p["perms"] = sorted(ALL_PERMS)
    mods = [{"key": k, "label": fr, "actions": ag.actions_of(k), "scopes": ag.SCOPES.get(k, [])} for k, fr, _ in ag.MODULES]
    return {"active": bool(profs), "modules": mods, "my_locked": bool((ctx.profile or {}).get("locked")), "all_perms": sorted(ALL_PERMS), "profiles": profs, "users": users, "my_profile_id": (ctx.profile or {}).get("id", "")}


@router.post("/access-profiles/activate")
async def activate(ctx: Ctx = Depends(UM)):
    if ctx.role != "admin":
        raise HTTPException(403, "Seul un administrateur peut activer les profils d'accès")
    if await db.access_profiles.find_one(ctx.q({})):
        raise HTTPException(409, "Les profils d'accès sont déjà activés")
    rows = [{"id": new_id(), "org_id": ctx.org_id, "created_at": now_iso(), "name": n, "name_en": en, "description": "", "base_role": br, "is_system": True, "locked": lock,
             "perms": sorted(PERMS[br] if perms is None else perms), "scope": scope, "require_2fa": "optional",
             "permissions": ag.grid_from(PERMS[br] if perms is None else perms, scope)} for n, en, br, perms, scope, lock in DEFAULTS]
    await db.access_profiles.insert_many([dict(r) for r in rows])
    by = {r["base_role"]: r for r in rows if r["base_role"]}
    table = []
    for u in await _staff(ctx):
        await db.users.update_one({"user_id": u["user_id"], "org_id": ctx.org_id}, {"$set": {"access_profile_id": by[u["role"]]["id"]}})
        table.append({"email": u["email"], "role": u["role"], "profile": by[u["role"]]["name"]})
    await audit(ctx.org_id, ctx.member, "access_profiles_activated", "", f"{len(table)} membre(s) migré(s)")
    return {"mapping": {br: r["name"] for br, r in by.items()}, "members": table}


def _guard(ctx: Ctx, perms: List[str]) -> list:
    bad = set(perms) - ALL_PERMS
    if bad:
        raise HTTPException(400, f"Permission inconnue : {sorted(bad)[0]}")
    if set(perms) - ctx.perms:
        raise HTTPException(403, "Vous ne pouvez pas accorder un droit que vous n'avez pas")
    return sorted(set(perms))


@router.post("/access-profiles")
async def create_profile(body: ProfileIn, ctx: Ctx = Depends(UM)):
    p = await ctx.insert("access_profiles", {**body.model_dump(), **_rights(ctx, body), "base_role": "", "is_system": False, "locked": False})
    await audit(ctx.org_id, ctx.member, "access_profile_created", p["name"], ", ".join(p["perms"]))
    return p


@router.put("/access-profiles/{pid}")
async def update_profile(pid: str, body: ProfileIn, ctx: Ctx = Depends(UM)):
    cur = await ctx.get("access_profiles", pid)
    if cur.get("locked"):
        raise HTTPException(403, "Le profil Administrateur n'est pas modifiable")
    if pid == (ctx.profile or {}).get("id"):
        raise HTTPException(403, "Vous ne pouvez pas modifier votre propre profil")
    p = await ctx.update("access_profiles", pid, {**body.model_dump(), **_rights(ctx, body)})
    masked = lambda x: ",".join(k for k in SENSITIVE if (x.get("sensitive") or {}).get(k) is False) or "rien"  # noqa: E731
    await audit(ctx.org_id, ctx.member, "access_profile_updated", p["name"], f"avant : {', '.join(cur.get('perms', []))} [{cur.get('scope')}] masqué {masked(cur)} | après : {', '.join(p['perms'])} [{p['scope']}] masqué {masked(p)} | 2FA {p.get('require_2fa')} | {_diff(cur.get('permissions') or {}, p['permissions'])}")
    return p


@router.delete("/access-profiles/{pid}")
async def delete_profile(pid: str, ctx: Ctx = Depends(UM)):
    cur = await ctx.get("access_profiles", pid)
    if cur.get("locked") or cur.get("is_system"):
        raise HTTPException(403, "Un profil fourni par défaut ne peut pas être supprimé")
    if await db.users.count_documents({"org_id": ctx.org_id, "access_profile_id": pid}):
        raise HTTPException(409, "Des membres sont rattachés à ce profil : changez d'abord leur profil")
    await ctx.delete("access_profiles", pid)
    await audit(ctx.org_id, ctx.member, "access_profile_deleted", cur["name"], ", ".join(cur.get("perms", [])))
    return {"ok": True}


class AssignIn(BaseModel):
    profile_id: str


@router.patch("/users/{user_id}/profile")
async def assign_profile(user_id: str, body: AssignIn, ctx: Ctx = Depends(UM)):
    if user_id == ctx.member["user_id"]:
        raise HTTPException(403, "Vous ne pouvez pas changer votre propre profil")
    t = await db.users.find_one({"user_id": user_id, "org_id": ctx.org_id, "role": {"$in": ROLES}, **IN_ENV}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Introuvable")
    new, old = await ctx.get("access_profiles", body.profile_id), await profile_of(t)
    if not (ctx.profile or {}).get("locked") and ((old or {}).get("locked") or new.get("locked")):
        raise HTTPException(403, "Seul un administrateur peut attribuer ou retirer le profil Administrateur")
    if perms_of(t, old) - ctx.perms or perms_of(t, new) - ctx.perms:
        raise HTTPException(403, "Vous ne pouvez pas attribuer ou retirer un profil plus élevé que le vôtre")
    if old and old.get("locked") and not new.get("locked") and await db.users.count_documents({"org_id": ctx.org_id, "access_profile_id": old["id"], **IN_ENV}) <= 1:
        raise HTTPException(409, "Il faut conserver au moins un administrateur")
    await db.users.update_one({"user_id": user_id, "org_id": ctx.org_id}, {"$set": {"access_profile_id": new["id"], **({"role": new["base_role"]} if new.get("base_role") else {})}})
    await audit(ctx.org_id, ctx.member, "member_profile_changed", t.get("email", ""), f"{(old or {}).get('name', t['role'])} → {new['name']}")
    return {"user_id": user_id, "profile_id": new["id"]}


class Override(BaseModel):
    perm: str
    grant: bool
    expires_at: Optional[str] = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")


class OverridesIn(BaseModel):
    overrides: List[Override] = Field([], max_length=40)


@router.put("/users/{user_id}/overrides")
async def set_overrides(user_id: str, body: OverridesIn, ctx: Ctx = Depends(UM)):
    if user_id == ctx.member["user_id"]:
        raise HTTPException(403, "Vous ne pouvez pas ajuster vos propres droits")
    t = await db.users.find_one({"user_id": user_id, "org_id": ctx.org_id, "role": {"$in": ROLES}, **IN_ENV}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Introuvable")
    prof = await profile_of(t)
    if not prof:
        raise HTTPException(409, "Activez d'abord les profils d'accès")
    if prof.get("locked"):
        raise HTTPException(403, "Les droits d'un administrateur ne s'ajustent pas")
    rows = [o.model_dump() for o in body.overrides]
    _guard(ctx, [o["perm"] for o in rows if o["grant"]])
    if {o["perm"] for o in rows} - ALL_PERMS or perms_of(t, prof) - ctx.perms:
        raise HTTPException(403, "Ajustement non autorisé")
    await db.users.update_one({"user_id": user_id, "org_id": ctx.org_id}, {"$set": {"permission_overrides": rows}})
    txt = lambda rs: ", ".join(f"{'+' if o['grant'] else '−'}{o['perm']}" + (f" jusqu'au {o['expires_at']}" if o.get("expires_at") else "") for o in rs) or "aucune"  # noqa: E731
    await audit(ctx.org_id, ctx.member, "member_overrides_changed", t.get("email", ""), f"avant : {txt(t.get('permission_overrides') or [])} | après : {txt(rows)}")
    return {"user_id": user_id, "overrides": rows}


# ---------- Cycle de vie des membres ----------
async def _target(ctx: Ctx, uid: str, leaving: bool = False) -> dict:
    if uid == ctx.member["user_id"]:
        raise HTTPException(403, "Cette action ne s'applique pas à votre propre compte")
    t = await db.users.find_one({"user_id": uid, "org_id": ctx.org_id, "role": {"$in": ROLES}, **IN_ENV}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Introuvable")
    prof = await profile_of(t)
    if prof and prof.get("locked"):
        if not (ctx.profile or {}).get("locked"):
            raise HTTPException(403, "Seul un administrateur peut gérer le compte d'un administrateur")
        if leaving and t.get("status") not in ("suspended", "disabled", "deleted") and await db.users.count_documents({"org_id": ctx.org_id, "access_profile_id": prof["id"], "status": {"$nin": ["suspended", "disabled", "deleted"]}, **IN_ENV}) <= 1:
            raise HTTPException(409, "Il faut conserver au moins un administrateur actif")
    elif perms_of(t, prof) - ctx.perms:
        raise HTTPException(403, "Ce membre a plus de droits que vous")
    return t


async def deactivate(org_id: str, t: dict, actor: dict | None, why: str) -> None:
    import portal_core as po
    await db.users.update_one({"user_id": t["user_id"], "org_id": org_id}, {"$set": {"status": "disabled", "disabled_at": now_iso()}})
    await po.revoke_sessions(t["user_id"])
    if t.get("team_id"):
        await db.team.update_one({"org_id": org_id, "id": t["team_id"]}, {"$set": {"active": False}})
    await audit(org_id, actor, "member_disabled", t.get("email", ""), why)


@router.post("/members/{uid}/do/{action}")
async def member_action(uid: str, action: Literal["suspend", "reactivate", "revoke", "reset-2fa", "disable"], ctx: Ctx = Depends(UM)):
    import portal_core as po
    t = await _target(ctx, uid, action in ("suspend", "disable"))
    if action == "disable":
        await deactivate(ctx.org_id, t, ctx.member, "désactivé manuellement")
        return {"ok": True}
    if action == "suspend":
        await db.users.update_one({"user_id": uid}, {"$set": {"status": "suspended"}})
        await po.revoke_sessions(uid)
    elif action == "reactivate":
        await db.users.update_one({"user_id": uid}, {"$set": {"status": "active"}})
        if t.get("team_id"):
            await db.team.update_one({"org_id": ctx.org_id, "id": t["team_id"]}, {"$set": {"active": True, "contract_ended": True}})
    elif action == "revoke":
        await po.revoke_sessions(uid)
    else:
        await po.clerk("DELETE", f"/users/{uid}/mfa")
        await db.users.update_one({"user_id": uid}, {"$set": {"two_factor": False}})
    await audit(ctx.org_id, ctx.member, f"member_{action}", t.get("email", ""))
    return {"ok": True}


def _open(ctx: Ctx, t: dict) -> dict:
    day = datetime.now().strftime("%Y-%m-%d")
    return {"tasks": ("tasks", ctx.q({"assignee_ids": t["user_id"], "status": {"$ne": "done"}, "deleted_at": None})),
            "events": ("events", ctx.q({"team.member_id": t.get("team_id") or "__none__", "end": {"$gte": day}})),
            "opportunities": ("opportunities", ctx.q({"owner_id": t["user_id"], "stage_key": {"$nin": ["gagnee", "perdue"]}}))}


@router.get("/members/{uid}/handover")
async def handover_preview(uid: str, ctx: Ctx = Depends(UM)):
    t = await _target(ctx, uid)
    return {k: await db[c].count_documents(f) for k, (c, f) in _open(ctx, t).items()}


class HandoverIn(BaseModel):
    to_user_id: str
    tasks: bool = True
    events: bool = True
    opportunities: bool = True


@router.post("/members/{uid}/handover")
async def handover(uid: str, body: HandoverIn, ctx: Ctx = Depends(UM)):
    t = await _target(ctx, uid)
    to = await db.users.find_one({"user_id": body.to_user_id, "org_id": ctx.org_id, "role": {"$in": ROLES}, "status": {"$nin": ["suspended", "disabled", "deleted"]}, **IN_ENV}, {"_id": 0})
    if not to or to["user_id"] == uid:
        raise HTTPException(400, "Choisissez un autre membre actif")
    f, done = _open(ctx, t), {}
    if body.tasks:
        done["tâches"] = (await db.tasks.update_many(f["tasks"][1], {"$set": {"assignee_ids.$": to["user_id"]}})).modified_count
    if body.events:
        if not to.get("team_id"):
            raise HTTPException(409, "Ce membre n'a pas de fiche Équipe : ses événements ne peuvent pas lui être confiés")
        src, dst = t.get("team_id") or "__none__", to["team_id"]
        await db.events.update_many({**f["events"][1], "$and": [{"team.member_id": dst}]}, {"$pull": {"team": {"member_id": src}}})
        done["événements"] = (await db.events.update_many(f["events"][1], {"$set": {"team.$[x].member_id": dst}}, array_filters=[{"x.member_id": src}])).modified_count
    if body.opportunities:
        done["opportunités"] = (await db.opportunities.update_many(f["opportunities"][1], {"$set": {"owner_id": to["user_id"]}})).modified_count
        await db.tasks.update_many(ctx.q({"owner_id": uid, "status": {"$ne": "done"}}), {"$set": {"owner_id": to["user_id"]}})
    await audit(ctx.org_id, ctx.member, "member_handover", t.get("email", ""), f"vers {to.get('email')} : " + ", ".join(f"{n} {k}" for k, n in done.items()))
    return done


async def tick(org_id: str | None = None) -> None:
    """Fin de contrat : rappel aux administrateurs à J-7, désactivation le lendemain de la date de fin."""
    from providers_core import PARIS
    import trash
    await trash.purge_expired(org_id)
    now = datetime.now(PARIS)
    day, soon = now.strftime("%Y-%m-%d"), (now + timedelta(days=7)).strftime("%Y-%m-%d")
    async for t in db.team.find({"end_date": {"$gt": "", "$lte": soon}, "contract_ended": {"$ne": True}, **({"org_id": org_id} if org_id else {})}, {"_id": 0}):
        key = {"org_id": t["org_id"], "id": t["id"]}
        if t["end_date"] < day:
            u = await db.users.find_one({"user_id": t.get("user_id"), "org_id": t["org_id"]}, {"_id": 0}) if t.get("user_id") else None
            if u and u.get("status") != "disabled":
                await deactivate(t["org_id"], u, None, f"fin de contrat le {t['end_date']}")
            await db.team.update_one(key, {"$set": {"active": False, "contract_ended": True, "invite_link": ""}})
        elif not t.get("end_reminded"):
            admins = [u["user_id"] async for u in db.users.find({"org_id": t["org_id"], "role": "admin", **IN_ENV}, {"user_id": 1})]
            await db.tasks.insert_one({"id": new_id(), "org_id": t["org_id"], "created_at": now_iso(), "title": f"Fin de contrat de {t['name']} le {t['end_date']}",
                                       "description": "Son accès sera désactivé automatiquement le lendemain. Pensez à transférer ses tâches et ses événements (Membres & accès).",
                                       "due_at": t["end_date"], "due_date": t["end_date"], "priority": "high", "assignee_ids": admins, "event_id": "", "status": "todo", "done": False, "done_at": None,
                                       "checklist": [], "attachments": [], "source": "auto", "source_ref": f"contract-end:{t['id']}", "created_by": "Système", "created_by_id": ""})
            await db.team.update_one(key, {"$set": {"end_reminded": True}})
