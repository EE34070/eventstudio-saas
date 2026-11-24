import hmac
import secrets
import os
import uuid
from datetime import datetime, timedelta, timezone

import requests

from fastapi import Depends, HTTPException, Request
from pymongo import ReturnDocument
from starlette.concurrency import run_in_threadpool

try:
    from backend.clerk_auth import require_user
except ModuleNotFoundError:
    from clerk_auth import require_user
import access_grid as ag
from security import COST_PATHS, PROD, link_token, sha256

import tenant_router as tenants

# Une base par société : `db` route chaque collection vers la base plateforme ou vers la
# base de la société active (voir tenant_router.py). Aucun changement dans les routes.
if tenants.CLUSTERS is None:
    tenants.init(tenants.Clusters.from_env())
client = tenants.CLUSTERS.clients["default"]
raw_db = tenants.RoutedDatabase()
# Collections soumises à la Corbeille : toute lecture exclut par défaut les éléments supprimés (deleted_at renseigné).
TRASHED = {"team", "social_managers", "provider_profiles", "contacts", "venues", "equipment", "packs", "kits", "vehicles", "warehouses", "events", "quotes", "invoices", "tasks", "expense_reports",
           "subscriptions", "purchase_invoices", "access_profiles", "media_assets", "comm_posts", "logistics_missions", "dj_bookings"}


def _live(f):
    f = f or {}
    return f if "deleted_at" in f else {**f, "deleted_at": None}


class _SoftColl:
    def __init__(self, c):
        self._c = c

    def __getattr__(self, n):
        return getattr(self._c, n)

    def _call(self, name, a, k):
        if a:
            a = (_live(a[0]),) + a[1:]
        else:
            k["filter"] = _live(k.get("filter"))
        return getattr(self._c, name)(*a, **k)

    def find(self, *a, **k):
        return self._call("find", a, k)

    def find_one(self, *a, **k):
        return self._call("find_one", a, k)

    def count_documents(self, *a, **k):
        return self._call("count_documents", a, k)

    def update_one(self, *a, **k):
        return self._call("update_one", a, k)

    def update_many(self, *a, **k):
        return self._call("update_many", a, k)

    def find_one_and_update(self, *a, **k):
        return self._call("find_one_and_update", a, k)

    def distinct(self, key, filter=None, **k):
        return self._c.distinct(key, _live(filter), **k)

    def aggregate(self, pipeline, *a, **k):
        return self._c.aggregate([{"$match": {"deleted_at": None}}, *pipeline], *a, **k)


class _SoftDB:
    def __init__(self, d):
        self._d = d

    def __getitem__(self, n):
        return _SoftColl(self._d[n]) if n in TRASHED else self._d[n]

    def __getattr__(self, n):
        return self[n] if n in TRASHED else getattr(self._d, n)


db = _SoftDB(raw_db)

ROLES = ["admin", "gerant", "chef_projet", "commercial", "comptable", "technicien"]
ROLE_LABELS = {"admin": "Admin", "gerant": "Gérant", "chef_projet": "Chef de projet",
               "commercial": "Commercial", "comptable": "Comptable", "technicien": "Technicien"}
DEFAULT_ROLE = "technicien"
RETIRED_ROLES: dict = {}
RANK = {r: len(ROLES) - i for i, r in enumerate(ROLES)}
PORTAL_ROLES = ["client", "provider"]
RANK.update({r: 0 for r in PORTAL_ROLES})
ROLE_LABELS.update({"client": "Client", "provider": "Prestataire"})
STAFF_2FA = os.environ.get("STAFF_2FA_REQUIRED", "false").strip().lower() == "true"
ENV = "live" if os.environ.get("CLERK_PUBLISHABLE_KEY", "").startswith("pk_live_") else "preview"
IN_ENV = {"env": {"$in": [ENV, None]}}
DEMO_SLUG = "exclusivity-events"
MODULE_IDS = ["dj", "son_lumiere", "photobooth", "photographe", "wedding_planner", "agence", "loueur_materiel"]

ALL_PERMS = {"events:read", "events:write", "events:delete", "finance:read", "finance:write",
             "catalog:read", "catalog:write", "contacts:read", "contacts:write", "venues:read",
             "venues:write", "team:read", "team:write", "org:write", "users:manage", "messages:read", "messages:write", "providers:manage", "crm:manage", "finance:costs", "pilot:view", "pilot:manage", "comms:view", "comms:manage", "social:view", "social:manage", "users:delete"}
PERMS = {
    "admin": ALL_PERMS,
    "gerant": ALL_PERMS - {"users:delete"},
    "chef_projet": {"events:read", "events:write", "finance:read", "catalog:read", "catalog:write",
                    "contacts:read", "contacts:write", "venues:read", "venues:write", "team:read", "messages:read", "messages:write"},
    "commercial": {"events:read", "events:write", "finance:read", "catalog:read", "contacts:read",
                   "contacts:write", "venues:read", "venues:write", "team:read", "messages:read", "messages:write", "crm:manage"},
    "comptable": {"pilot:view", "social:view", "events:read", "finance:read", "finance:write", "catalog:read", "contacts:read",
                  "venues:read", "team:read", "messages:read"},
    "technicien": {"events:read", "catalog:read", "venues:read", "team:read"},
    "client": {"portal:client", "portal:any"},
    "provider": {"portal:provider", "portal:any"},
}


async def profile_of(member: dict) -> dict | None:
    """Profil d'accès du membre ; None tant que les profils ne sont pas activés pour sa société (droits du rôle historique)."""
    if not member.get("org_id") or member.get("role") not in ROLES:
        return None
    pid = member.get("access_profile_id")
    if not pid:
        p = await db.access_profiles.find_one({"org_id": member["org_id"], "is_system": True, "base_role": member["role"]}, {"_id": 0})
        if p:
            await db.users.update_one({"user_id": member["user_id"]}, {"$set": {"access_profile_id": p["id"]}})
        return p
    return await db.access_profiles.find_one({"org_id": member["org_id"], "id": pid}, {"_id": 0})


def perms_of(member: dict, prof: dict | None) -> set:
    if not prof:
        return PERMS.get(member.get("role"), set())
    if prof.get("locked"):
        return ALL_PERMS
    perms, day = set(prof.get("perms") or []) - {"finance:costs"}, datetime.now(timezone.utc).date().isoformat()
    if (prof.get("sensitive") or {}).get("finance_costs") is True:
        perms.add("finance:costs")
    if prof.get("is_system") and prof.get("base_role") and "finance" not in (prof.get("permissions") or {}):
        perms |= PERMS[prof["base_role"]] & {"pilot:view", "pilot:manage"}
    if prof.get("is_system") and prof.get("base_role") and "communication" not in (prof.get("permissions") or {}):
        perms |= PERMS[prof["base_role"]] & {"comms:view", "comms:manage"}
    if prof.get("is_system") and prof.get("base_role") and "social" not in (prof.get("permissions") or {}):
        perms |= PERMS[prof["base_role"]] & {"social:view", "social:manage"}
    for o in member.get("permission_overrides") or []:
        if not o.get("expires_at") or o["expires_at"] >= day:
            (perms.add if o.get("grant") else perms.discard)(o["perm"])
    return perms & ALL_PERMS


def granted_of(member: dict) -> set:
    day = datetime.now(timezone.utc).date().isoformat()
    return {o["perm"] for o in member.get("permission_overrides") or [] if o.get("grant") and (not o.get("expires_at") or o["expires_at"] >= day)}


SENSITIVE = ("sale_prices", "costs_margins", "client_contacts", "hr_data")


def hidden_of(prof: dict | None) -> set:
    return set() if not prof or prof.get("locked") else {k for k in SENSITIVE if (prof.get("sensitive") or {}).get(k) is False}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def effective_role(role) -> str:
    role = RETIRED_ROLES.get(role, role)
    return role if role in ROLES or role in PORTAL_ROLES else DEFAULT_ROLE


def _clerk_user(user_id: str) -> dict:
    r = requests.get(f"https://api.clerk.com/v1/users/{user_id}", timeout=10,
                     headers={"Authorization": f"Bearer {os.environ['CLERK_SECRET_KEY']}", "User-Agent": "emergent-app"})
    r.raise_for_status()
    return r.json()


def _admin_emails() -> set:
    return {e.strip().lower() for e in os.environ.get("ADMIN_EMAIL", "").split(",") if e.strip()}


async def _first_sign_in(uid: str) -> None:
    cu = await run_in_threadpool(_clerk_user, uid)
    emails = [e["email_address"].lower() for e in cu.get("email_addresses", [])
              if (e.get("verification") or {}).get("status") == "verified"]
    all_emails = [e["email_address"].lower() for e in cu.get("email_addresses", [])]
    name = " ".join(filter(None, [cu.get("first_name"), cu.get("last_name")])) or (all_emails[0] if all_emails else "Utilisateur")
    org_id, role, team_id = None, None, None
    day = datetime.now(timezone.utc).date().isoformat()
    team = None
    if emails:  # invitation en attente : cherchée dans la base de chaque société (1re connexion uniquement)
        _, team = await tenants.find_in_orgs("team", {"email": {"$in": emails}, "user_id": None, "$or": [{"end_date": {"$in": [None, ""]}}, {"end_date": {"$gte": day}}]}, {"_id": 0})
    if team:
        org_id, role, team_id = team["org_id"], effective_role(team.get("access_role")), team["id"]
    elif _admin_emails() & set(emails):
        org = await db.orgs.find_one({"slug": DEMO_SLUG}, {"_id": 0})
        if org:
            org_id, role = org["id"], "admin"
            tenants.pin_org(org_id)
            t = await db.team.find_one({"org_id": org_id, "email": {"$in": emails}}, {"_id": 0})
            team_id = t["id"] if t else None
    doc = {"user_id": uid, "email": all_emails[0] if all_emails else "", "name": name, "org_id": org_id,
           "role": role, "team_id": team_id, "env": ENV, "created_at": now_iso()}
    res = await db.users.update_one({"user_id": uid}, {"$setOnInsert": doc}, upsert=True)
    if res.upserted_id is not None and team_id:
        await db.team.update_one({"id": team_id}, {"$set": {"user_id": uid}})


AZP = [o.strip().rstrip("/") for o in os.environ.get("CLERK_AUTHORIZED_PARTIES", "").split(",") if o.strip()]
ISSUER = os.environ.get("CLERK_ISSUER", "").strip().rstrip("/")


def check_claims(claims: dict) -> None:
    """En plus de la signature et de l'expiration (clerk_auth) : émetteur et domaine d'origine du jeton."""
    azp = (claims.get("azp") or "").rstrip("/")
    if (ISSUER and (claims.get("iss") or "").rstrip("/") != ISSUER) or (AZP and (azp not in AZP if azp else PROD)):
        raise HTTPException(401, "Invalid or expired session")


async def current_member(user: dict = Depends(require_user)) -> dict:
    check_claims(user["claims"])
    uid = user["user_id"]
    member = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if member is None:
        await _first_sign_in(uid)
        member = await db.users.find_one({"user_id": uid}, {"_id": 0})
    if member.get("org_id"):
        tenants.pin_org(member["org_id"])  # toute la requête utilise la base de SA société
    if member.get("env") != ENV:
        await db.users.update_one({"user_id": uid}, {"$set": {"env": ENV}})
    rev = member.get("sessions_revoked_at")
    if rev and (user["claims"].get("iat") or 0) <= rev:
        raise HTTPException(401, "Session révoquée")
    now = now_iso()
    if member.get("status") == "invited":
        if (member.get("invite_expires_at") or "9") < now:
            raise HTTPException(403, "Invitation expirée : demandez un nouveau lien")
        member["status"] = "active"
        await db.users.update_one({"user_id": uid}, {"$set": {"status": "active", "last_login_at": now}})
    elif (member.get("last_login_at") or "")[:15] != now[:15]:
        if (member.get("last_login_at") or "")[:10] != now[:10] and member.get("org_id"):
            await audit(member["org_id"], member, "login", member.get("email", ""))
        await db.users.update_one({"user_id": uid}, {"$set": {"last_login_at": now}})
    member["role"] = effective_role(member.get("role")) if member.get("org_id") else None
    return member


EXPIRED = "Ce lien a expiré. Contactez l'entreprise qui vous l'a envoyé pour en recevoir un nouveau."


def _plus(day: str, days: int) -> str:
    return (datetime.strptime((day or "2000-01-01")[:10], "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")


def link_limit(coll: str, d: dict) -> str:
    if coll == "quotes":
        sig = (d.get("signature") or {}).get("signed_at") or d.get("accepted_at") or d.get("updated_at") or d.get("date")
        return _plus(sig, 365) if d.get("status") == "accepte" else (d.get("valid_until") or _plus(d.get("date"), 30))
    if coll == "invoices":
        return _plus(d.get("date") or d.get("created_at"), 365)
    return _plus(d.get("date"), 7) if d.get("date") else "9999"


def check_expiry(limit: str) -> None:
    if datetime.now(timezone.utc).date().isoformat() > limit[:10]:
        raise HTTPException(410, EXPIRED)


async def ensure_link(coll: str, doc: dict, renew: bool = False) -> str:
    if renew or not doc.get("share_nonce") or not doc.get("share_hash"):
        doc["share_nonce"] = secrets.token_urlsafe(16)
        doc["share_hash"] = sha256(link_token(coll, doc))
        await db[coll].update_one({"id": doc["id"], "org_id": doc["org_id"]}, {"$set": {"share_nonce": doc["share_nonce"], "share_hash": doc["share_hash"]}, "$unset": {"share_token": "", "token": ""}})
    return link_token(coll, doc)


async def link_doc(coll: str, token: str) -> dict | None:
    h = sha256(token)
    d = await db[coll].find_one({"share_hash": h}, {"_id": 0}) if 40 <= len(token) <= 64 else None
    if not d or not hmac.compare_digest(d["share_hash"], h):
        return None
    if coll in ("quotes", "invoices", "logistics_missions"):
        check_expiry(link_limit(coll, d))
    return d


async def audit(org_id: str, actor: dict | None, action: str, target: str = "", detail: str = "") -> None:
    a = actor or {}
    await db.audit_logs.insert_one({"id": new_id(), "org_id": org_id, "at": now_iso(), "at_dt": datetime.now(timezone.utc), "actor_id": a.get("user_id", ""),
                                    "actor_name": a.get("name") or a.get("email") or "Système", "actor_role": a.get("role") or "", "action": action, "target": target[:200], "detail": detail[:500]})


class Ctx:
    """Request principal + tenant-scoped data access (every query carries org_id)."""

    def __init__(self, member: dict, prof: dict | None = None):
        self.member = member
        self.org_id = member["org_id"]
        tenants.soft_set_org(self.org_id)
        self.role = member["role"]
        self.profile = prof
        self.perms = perms_of(member, prof)
        self.grid = None if not prof or prof.get("locked") else ag.fill(prof.get("permissions"), self.perms)
        self.granted = granted_of(member) if prof else set()
        self.assigned_only = ((self.grid.get("events") or {}).get("scope") == "assigned" if self.grid else prof.get("scope") == "assigned") if prof else self.role == "technicien"
        self.team_id = member.get("team_id")
        self.contact_id = member.get("contact_id")
        self.preview = False
        self.viewer = member

    def can(self, perm: str) -> bool:
        return perm in self.perms

    def sees(self, module: str) -> bool:
        return not self.grid or bool((self.grid.get(module) or {}).get("view"))

    def own(self, module: str) -> bool:
        return bool(self.grid) and (self.grid.get(module) or {}).get("scope") == "own"

    def q(self, f: dict | None = None) -> dict:
        return {**(f or {}), "org_id": self.org_id}

    def event_scope(self) -> dict:
        if self.assigned_only:
            return {"team.member_id": self.team_id or "__none__"}
        return {}

    async def list(self, coll: str, f: dict | None = None, sort=None, limit: int = 2000) -> list:
        cur = db[coll].find(self.q(f), {"_id": 0})
        if sort:
            cur = cur.sort(sort)
        return await cur.to_list(limit)

    async def get(self, coll: str, id: str, extra: dict | None = None) -> dict:
        d = await db[coll].find_one(self.q({"id": id, **(extra or {})}), {"_id": 0})
        if not d:
            raise HTTPException(404, "Introuvable")
        return d

    async def insert(self, coll: str, data: dict) -> dict:
        doc = {**data, "id": new_id(), "org_id": self.org_id, "created_at": now_iso()}
        await db[coll].insert_one(doc)
        doc.pop("_id", None)
        return doc

    async def update(self, coll: str, id: str, data: dict) -> dict:
        r = await db[coll].find_one_and_update(self.q({"id": id}), {"$set": {**data, "updated_at": now_iso()}},
                                               projection={"_id": 0}, return_document=ReturnDocument.AFTER)
        if not r:
            raise HTTPException(404, "Introuvable")
        return r

    async def delete(self, coll: str, id: str) -> None:
        if coll in TRASHED:
            import trash
            kind = next((k for k, v in trash.KINDS.items() if v[0] == coll), None)
            if kind and not trash.allowed(self, kind):
                raise HTTPException(403, f"Votre profil ne permet pas de supprimer : {trash.KINDS[kind][3]}")
            cur = await db[coll].find_one(self.q({"id": id}), {"_id": 0}) or {}
            if kind:
                await audit(self.org_id, self.member, "trash_deleted", f"{trash.KINDS[kind][3]} : {trash.label(cur)}", "suppression simple")
            r = await db[coll].update_one(self.q({"id": id}), {"$set": {"deleted_at": now_iso(), "deleted_by": self.member.get("name", ""), "purge_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()}})
            if r.matched_count == 0:
                raise HTTPException(404, "Introuvable")
            return
        r = await db[coll].delete_one(self.q({"id": id}))
        if r.deleted_count == 0:
            raise HTTPException(404, "Introuvable")


_QA_ORG: dict = {}


async def twofa_exempt(org_id: str) -> bool:
    """Société de test « QA Sandbox », hors production uniquement : ses comptes de test ne peuvent pas activer la 2FA."""
    if ENV == "live":
        return False
    if "id" not in _QA_ORG:
        _QA_ORG["id"] = (await db.orgs.find_one({"slug": "qa-sandbox"}, {"id": 1}) or {}).get("id")
    return org_id == _QA_ORG["id"]


async def preview_target(request: Request, member: dict, prof: dict | None):
    """« Voir comme ce membre » : aperçu en lecture seule, sans session, réservé à qui gère les membres."""
    target = request.headers.get("x-view-as-member")
    if not target:
        return None
    if member.get("role") not in ROLES or "users:manage" not in perms_of(member, prof):
        raise HTTPException(403, "Action non autorisée pour votre rôle")
    t = await db.users.find_one({"user_id": target, "org_id": member["org_id"], "role": {"$in": ROLES}}, {"_id": 0})
    tp = await profile_of(t) if t else None
    if not t or (tp and tp.get("locked") and not (prof or {}).get("locked")):
        raise HTTPException(404, "Introuvable")
    if request.method != "GET":
        raise HTTPException(403, "Aperçu admin : lecture seule")
    return t, tp


def needs_2fa(member: dict, prof: dict | None, exempt: bool) -> bool:
    return (STAFF_2FA and member.get("role") in ("admin", "gerant") and not exempt) or (prof or {}).get("require_2fa") == "required"


async def _enforce_plan(request: Request, org_id: str, method: str) -> None:
    """Offre SaaS : rubrique incluse et abonnement actif (plans.py)."""
    import plans
    org = await db.orgs.find_one({"id": org_id}, {"_id": 0, "subscription": 1}) or {}
    route = request.scope.get("route")
    section, _ = ag.classify(request.method, route.path if route else request.url.path, request.query_params.get("format") or "")
    plans.enforce(org, section, method)


def need(perm: str | None = None):
    """Single authorization entry point: staff permissions, portal roles (client / provider) and admin read-only preview."""
    portal = (perm or "").startswith("portal:")

    async def dep(request: Request, member: dict = Depends(current_member)) -> Ctx:
        if not member.get("org_id"):
            raise HTTPException(403, "Aucune entreprise associée à ce compte")
        if member.get("status") in ("suspended", "deleted", "disabled"):
            raise HTTPException(403, "Accès suspendu")
        role = member["role"]
        request.state.no_cost = True
        prof = await profile_of(member)
        if portal and role not in PORTAL_ROLES:
            target = request.headers.get("x-view-as")
            if not target or "users:manage" not in perms_of(member, prof):
                raise HTTPException(403, "Action non autorisée pour votre rôle")
            t = await db.users.find_one({"user_id": target, "org_id": member["org_id"], "role": {"$in": PORTAL_ROLES}}, {"_id": 0})
            if not t or perm not in PERMS[t["role"]]:
                raise HTTPException(404, "Introuvable")
            if request.method != "GET":
                raise HTTPException(403, "Aperçu admin : lecture seule")
            ctx = Ctx(t)
            ctx.preview, ctx.viewer = True, member
            return ctx
        if role in PORTAL_ROLES and not portal:
            await audit(member["org_id"], member, "access_denied", request.url.path)
            raise HTTPException(404, "Introuvable")
        if not member.get("two_factor") and needs_2fa(member, prof, await twofa_exempt(member["org_id"])):
            raise HTTPException(403, {"code": "2fa_required", "message": "Activez la double authentification pour continuer"})
        pv = await preview_target(request, member, prof)
        if pv:
            ctx = Ctx(*pv)
            ctx.preview, ctx.viewer, prof = True, member, pv[1]
        else:
            ctx = Ctx(member, prof)
        request.state.hide = hidden_of(prof)
        request.state.no_cost = not ctx.can("finance:costs")
        if request.state.no_cost and request.url.path.startswith(COST_PATHS):
            raise HTTPException(403, "Réservé aux profils autorisés à voir les coûts et les achats")
        if perm and not ctx.can(perm):
            raise HTTPException(403, "Action non autorisée pour votre rôle")
        if prof and not prof.get("locked"):
            route = request.scope.get("route")
            path = route.path if route else request.url.path
            if ctx.grid:
                m, a = ag.classify(request.method, path, request.query_params.get("format") or "")
                if m and not (m == "settings" and a == "view") and perm not in ctx.granted and not ag.allowed(ctx.grid, m, a, perm):
                    raise HTTPException(403, "Action non autorisée pour votre profil d'accès")
            sw = ag.switch(request.method, path)
            if sw and (prof.get("sensitive") or {}).get(sw) is False:
                raise HTTPException(403, "Votre profil d'accès ne permet pas cet envoi")
        await _enforce_plan(request, member["org_id"], "GET" if ctx.preview else request.method)
        return ctx
    dep.perm = perm
    return dep
