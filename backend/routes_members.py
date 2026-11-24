"""Membres & accès : liste unifiée (fiches Équipe + comptes), modification, désactivation, suppression sans historique."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import routes_access as ra
from core import IN_ENV, ROLES, Ctx, audit, db, need

router = APIRouter(prefix="/api")
UM = need("users:manage")
D = r"^(\d{4}-\d{2}-\d{2})?$"
OFF = ("suspended", "disabled", "deleted")


async def history(ctx: Ctx, tid: str, uid: str | None) -> list:
    """Ce qui empêche une suppression : toute donnée attribuée au membre."""
    t, u = tid or "__none__", uid or "__none__"
    checks = [("événement(s)", "events", {"team.member_id": t}), ("tâche(s)", "tasks", {"$or": [{"assignee_ids": u}, {"created_by_id": u}, {"owner_id": u}]}),
              ("devis", "quotes", {"$or": [{"created_by_id": u}, {"owner_id": u}]}), ("heure(s)", "time_entries", {"team_id": t}), ("contrat(s)", "employment_contracts", {"team_id": t, "deleted_at": None}),
              ("absence(s)", "absences", {"team_id": t}), ("note(s) de frais", "expense_reports", {"user_id": {"$in": [t, u]}}), ("opportunité(s)", "opportunities", {"owner_id": u}),
              ("activité(s) CRM", "crm_activities", {"created_by": u}), ("conversation(s)", "conversations", {"assigned_to": {"$in": [t, u]}}), ("fiche salarié", "employee_files", {"team_id": t})]
    out = [f"{n} {label}" for label, c, f in checks if (n := await db[c].count_documents(ctx.q(f)))]
    if uid and (await db.users.find_one({"user_id": uid}, {"last_login_at": 1}) or {}).get("last_login_at"):
        out.append("déjà connecté")
    return out


def split(name: str) -> tuple:
    a, _, b = (name or "").strip().partition(" ")
    return a, b


@router.get("/members")
async def members(ctx: Ctx = Depends(UM)):
    team = await ctx.list("team", sort=[("name", 1)])
    users = {u["user_id"]: u for u in await ra._staff(ctx)}
    profs = await ctx.list("access_profiles", sort=[("created_at", 1)])
    by_role = {p["base_role"]: p["id"] for p in profs if p.get("base_role")}
    rows, seen = [], set()
    locked = {p["id"] for p in profs if p.get("locked")}
    is_admin = lambda u: (u.get("access_profile_id") or by_role.get(u.get("role"))) in locked and u.get("status") not in OFF  # noqa: E731
    admins = sum(1 for u in users.values() if is_admin(u))

    def block(u):
        if not ctx.can("users:delete"):
            return "Votre profil ne permet pas de supprimer un membre"
        if u and u["user_id"] == ctx.member["user_id"]:
            return "Vous ne pouvez pas supprimer votre propre compte"
        if u and is_admin(u) and admins <= 1:
            return "Dernier administrateur : nommez-en un autre avant"
        return ""
    for t in team:
        u = users.get(t.get("user_id"))
        if u:
            seen.add(u["user_id"])
            status = u.get("status") if u.get("status") in OFF else "active"
        else:
            status = "disabled" if not t.get("active", True) else "invited"
        fn, ln = (t.get("first_name"), t.get("last_name")) if t.get("first_name") is not None else split(t["name"])
        h = await history(ctx, t["id"], t.get("user_id"))
        rows.append({"id": t["id"], "user_id": (u or {}).get("user_id", ""), "name": t["name"], "first_name": fn, "last_name": ln, "email": t.get("email", ""), "phone": t.get("phone", ""), "photo": t.get("photo", ""), "job": t.get("job", ""),
                     "contract_type": t.get("contract_type", "cdi"), "start_date": t.get("start_date", ""), "end_date": t.get("end_date", ""), "language": t.get("language", "fr-FR"), "access_role": (u or {}).get("role") or t.get("access_role"),
                     "profile_id": (u or {}).get("access_profile_id") or by_role.get(t.get("access_role"), ""), "status": status, "invite": "" if u else t.get("invite_status") or "none", "invite_error": t.get("invite_error", ""),
                     "delete_block": block(u), "history": h, "is_self": bool(u) and u["user_id"] == ctx.member["user_id"], "overrides": (u or {}).get("permission_overrides") or [], "last_login_at": (u or {}).get("last_login_at", "")})
    for uid, u in users.items():
        if uid not in seen and u.get("status") != "deleted":
            fn, ln = split(u.get("name", ""))
            rows.append({"id": "", "user_id": uid, "name": u.get("name", ""), "first_name": fn, "last_name": ln, "email": u.get("email", ""), "access_role": u["role"], "profile_id": u.get("access_profile_id", ""), "status": u.get("status") if u.get("status") in OFF else "active",
                         "invite": "", "delete_block": block(u), "history": ["compte sans fiche Équipe"], "is_self": uid == ctx.member["user_id"], "overrides": u.get("permission_overrides") or [], "last_login_at": u.get("last_login_at", "")})
    return {"rows": rows, "profiles": [{"id": p["id"], "name": p["name"], "locked": bool(p.get("locked")), "base_role": p.get("base_role", "")} for p in profs], "can_delete": ctx.can("users:delete"), "my_locked": bool((ctx.profile or {}).get("locked"))}


@router.post("/members/{uid}/sheet")
async def ensure_sheet(uid: str, ctx: Ctx = Depends(UM)):
    """Compte sans fiche Équipe : crée la fiche pour qu'il suive le même circuit (corbeille, restauration)."""
    u = await db.users.find_one({"user_id": uid, "org_id": ctx.org_id, "role": {"$in": ROLES}, **IN_ENV}, {"_id": 0})
    if not u:
        raise HTTPException(404, "Introuvable")
    t = await db.team.find_one(ctx.q({"user_id": uid}), {"_id": 0})
    if not t:
        fn, ln = split(u.get("name", ""))
        t = await ctx.insert("team", {"name": u.get("name") or u.get("email", ""), "first_name": fn, "last_name": ln, "email": u.get("email", ""), "phone": "", "job": "", "active": True, "access_role": u["role"], "user_id": uid, "deleted_at": None})
        await db.users.update_one({"user_id": uid, "org_id": ctx.org_id}, {"$set": {"team_id": t["id"]}})
    return {"id": t["id"]}


class MemberIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field("", max_length=60)
    email: str = Field("", max_length=160)
    phone: str = Field("", max_length=30)
    photo: str = Field("", max_length=80)
    job: str = Field("", max_length=120)
    contract_type: Literal["cdi", "cdd", "cddu", "alternance", "stage", "independant", "externe", "autre"] = "cdi"
    start_date: str = Field("", pattern=D)
    end_date: str = Field("", pattern=D)
    language: str = Field("fr-FR", max_length=10)
    profile_id: str = ""
    status: Literal["active", "invited", "suspended", "disabled"] = "active"


async def orphan_clerk(email: str, token_id: str = "") -> None:
    """Invalide le lien d'invitation et retire le compte Clerk s'il n'est rattaché à aucun compte de l'application."""
    import portal_core as po
    if token_id:
        try:
            await po.clerk("POST", f"/sign_in_tokens/{token_id}/revoke")
        except HTTPException:
            pass
    if email:
        for cu in await po.clerk("GET", "/users", params={"email_address": email}):
            if not await db.users.find_one({"user_id": cu["id"]}):
                await po.clerk("DELETE", f"/users/{cu['id']}")


@router.put("/members/{tid}")
async def edit_member(tid: str, body: MemberIn, request: Request, ctx: Ctx = Depends(UM)):
    import portal_core as po
    from routes_main import _member_invite
    cur = await ctx.get("team", tid)
    uid = cur.get("user_id")
    u = await db.users.find_one({"user_id": uid, "org_id": ctx.org_id, **IN_ENV}, {"_id": 0}) if uid else None
    me = bool(u) and uid == ctx.member["user_id"]
    if u and not me:
        await ra._target(ctx, uid)
    email = body.email.strip().lower()
    data = body.model_dump(exclude={"profile_id", "status", "email"})
    data.update(name=" ".join(filter(None, [body.first_name.strip(), body.last_name.strip()])), email=email)
    if email != (cur.get("email") or ""):
        if email and not po.pc.MAIL_RE.match(email):
            raise HTTPException(400, "Adresse e-mail invalide")
        if email and await db.team.find_one(ctx.q({"email": email, "id": {"$ne": tid}})):
            raise HTTPException(409, "Un membre utilise déjà cet e-mail")
        if u:
            if not email:
                raise HTTPException(400, "Un membre qui a un compte doit garder une adresse e-mail")
            await po.clerk("POST", "/email_addresses", json={"user_id": uid, "email_address": email, "verified": True, "primary": True})
            for e in (await po.clerk("GET", f"/users/{uid}")).get("email_addresses", []):
                if e["email_address"].lower() != email:
                    await po.clerk("DELETE", f"/email_addresses/{e['id']}")
            await db.users.update_one({"user_id": uid}, {"$set": {"email": email}})
        else:
            await orphan_clerk(cur.get("email", ""), cur.get("invite_token_id", ""))
            data.update(invite_link="", invite_token_id="", invite_status="none")
    prof_before = (u or {}).get("access_profile_id") or ""
    if body.profile_id and u and body.profile_id != prof_before:
        await ra.assign_profile(uid, ra.AssignIn(profile_id=body.profile_id), ctx)
    elif body.profile_id and not u:
        p = await ctx.get("access_profiles", body.profile_id)
        if not p.get("base_role"):
            raise HTTPException(400, "Un profil personnalisé s'attribue après la première connexion du membre")
        if p.get("locked") and not (ctx.profile or {}).get("locked"):
            raise HTTPException(403, "Seul un administrateur peut attribuer le profil Administrateur")
        data["access_role"] = p["base_role"]
    st_before = (u.get("status") if u.get("status") in OFF else "active") if u else ("disabled" if not cur.get("active", True) else "invited")
    want = body.status if body.status != "invited" or not u else "active"
    if u and want != st_before:
        if me:
            raise HTTPException(403, "Vous ne pouvez pas changer votre propre statut")
        await ra.member_action(uid, {"active": "reactivate", "suspended": "suspend", "disabled": "disable"}[want], ctx)
    elif not u and want in ("disabled", "active", "invited"):
        data["active"] = want != "disabled"
        if want == "disabled":
            await orphan_clerk("", cur.get("invite_token_id", ""))
            data["invite_link"] = ""
    if data["end_date"] != (cur.get("end_date") or ""):
        data.update(end_reminded=False, contract_ended=False)
    await ctx.update("team", tid, data)
    if u:
        await db.users.update_one({"user_id": uid}, {"$set": {"name": data["name"]}})
    resent = False
    if not u and email and email != (cur.get("email") or "") and data.get("active", True):
        from routes_comms import base_url
        await _member_invite(ctx, await ctx.get("team", tid), base_url(request))
        resent = True
    keys = ("name", "email", "phone", "job", "contract_type", "start_date", "end_date", "language", "photo", "access_role")
    diff = [f"{k} : {cur.get(k) or '∅'} → {data[k] or '∅'}" for k in keys if k in data and (cur.get(k) or "") != (data[k] or "")]
    diff += [f"statut : {st_before} → {want}"] if want != st_before and not (st_before == "invited" and want == "active") else []
    diff += [f"profil : {prof_before or '∅'} → {body.profile_id}"] if u and body.profile_id and body.profile_id != prof_before else []
    if diff:
        await audit(ctx.org_id, ctx.member, "member_updated", data["name"], " | ".join(diff)[:900])
    return {"ok": True, "invitation_resent": resent}
