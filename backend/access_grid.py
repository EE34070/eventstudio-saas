"""Grille module × action des profils d'accès : classement de chaque route et correspondance avec les droits historiques."""
import re

ACTIONS = ("view", "create", "update", "delete", "export", "validate")
BASE = {None, "events:read"}
MODULES = [("events", "Événements", "Events"), ("contacts", "Contacts", "Contacts"), ("crm", "CRM", "CRM"), ("quotes", "Devis", "Quotes"),
           ("invoices", "Facturation clients", "Invoicing"), ("accounting", "Relances & comptabilité", "Reminders & accounting"), ("finance", "Finance & pilotage", "Finance"), ("social", "Pôle Social (RH, paie, congés)", "HR & payroll"),
           ("purchases", "Achats (factures d'achat, abonnements)", "Purchases"), ("expenses", "Notes de frais", "Expenses"),
           ("catalog", "Matériel & catalogue", "Equipment"), ("stock", "Stock & entrepôts", "Stock & warehouses"),
           ("logistics", "Logistique, chargement, livraison & planning", "Logistics & planning"), ("works", "Travaux internes", "Internal works"), ("vehicles", "Véhicules", "Vehicles"), ("venues", "Lieux", "Venues"),
           ("providers", "Prestataires", "Providers"), ("staff", "Staff & missions", "Staff & jobs"), ("music", "Ma musique (DJ)", "Music"),
           ("messages", "Messagerie", "Messaging"), ("communication", "Communication (médiathèque, collectes, publications)", "Communication"), ("inbound", "Saisie rapide IA", "Quick AI entry"), ("tasks", "To-do", "To-do"), ("team", "Équipe", "Team"),
           ("portals", "Espaces clients & portails", "Client portals"), ("users", "Membres & accès", "Members & access"), ("settings", "Paramètres", "Settings")]
KEYS = [m[0] for m in MODULES]
SCOPES = {"events": ["all", "assigned"], "tasks": ["all", "own"], "expenses": ["all", "own"], "works": ["all", "own"]}
FIRST = {"finance": "finance", "social": "social", "communication": "communication", "events": "events", "contacts": "contacts", "organizers": "contacts", "contact-statuses": "contacts", "contact-people": "contacts", "contact-roles": "contacts", "wedding-planners": "contacts", "wedding": "events", "opportunities": "crm", "crm": "crm",
         "quotes": "quotes", "quote-templates": "quotes", "quote-section-templates": "quotes", "quote-views": "quotes", "dj": "providers", "supplier-quotes": "quotes", "margin-rules": "settings", "invoices": "invoices", "reminders": "accounting",
         "purchase-invoices": "purchases", "purchase-needs": "purchases", "shortages": "logistics", "partner-requests": "logistics", "subscriptions": "purchases", "loans": "purchases", "contracts": "purchases", "contract-documents": "purchases", "bank-accounts": "purchases", "subscription-invoices": "purchases", "debits": "purchases", "expenses": "expenses",
         "equipment": "catalog", "catalog": "catalog", "supplier-products": "catalog", "catalogue-import": "catalog", "uoms": "catalog", "kits": "catalog", "attribute-templates": "catalog", "packs": "catalog", "product-documents": "catalog", "requirement-templates": "catalog", "stock": "stock", "warehouses": "stock",
         "logistics": "logistics", "loading": "logistics", "deliveries": "logistics", "planning": "logistics", "work-orders": "works", "work-templates": "works", "work-recurrences": "works", "work-types": "works", "work-planning": "works", "vehicles": "vehicles", "venues": "venues", "geocode": "venues",
         "providers": "providers", "provider-categories": "providers", "provider-documents": "providers", "provider-unavailabilities": "providers", "service-requests": "providers",
         "message-templates": "providers", "missions": "providers", "staff": "staff", "staff-teams": "staff", "positions": "staff", "applications": "staff", "timesheets": "staff",
         "payroll-export": "staff", "provider-invoices": "staff", "music-plans": "music", "messaging": "messages", "inbound-requests": "inbound", "tasks": "tasks", "team": "team",
         "portal-users": "portals", "portal-modules": "portals", "portal-settings": "portals", "portal-requests": "portals", "email-templates": "portals", "profile-changes": "portals",
         "gdpr-requests": "portals", "client-documents": "events", "access-profiles": "users", "users": "users", "members": "users", "audit-logs": "users",
         "org": "settings", "brand-templates": "settings", "document-pages": "settings"}
EVENT_SUB = {"dj": "providers", "quotes": "quotes", "quote-candidates": "quotes", "positions": "staff", "music": "music",
             "logistics": "logistics", "shortages": "logistics", "partner-requests": "logistics", "allocations": "stock", "origin": "stock", "stock-return": "stock"}
ER, EW, FR, FW, CR, CW, PM, UM, OW = "events:read", "events:write", "finance:read", "finance:write", "catalog:read", "catalog:write", "providers:manage", "users:manage", "org:write"
# droit historique principal de chaque module : (voir, écrire) ; None = seule la grille décide
PRIM = {"finance": ("pilot:view", "pilot:manage"), "social": ("social:view", "social:manage"), "communication": ("comms:view", "comms:manage"), "events": (ER, EW), "contacts": ("contacts:read", "contacts:write"), "crm": ("crm:manage", "crm:manage"), "quotes": (FR, FR), "invoices": (FR, FW), "accounting": (FR, FW),
        "purchases": (FR, FW), "expenses": (ER, None), "catalog": (CR, CW), "stock": (CR, CW), "logistics": (ER, EW), "works": (ER, CW), "vehicles": (ER, CW), "venues": ("venues:read", "venues:write"),
        "providers": (PM, PM), "staff": (PM, PM), "music": (ER, None), "messages": ("messages:read", "messages:write"), "inbound": (ER, EW), "tasks": (ER, None),
        "team": ("team:read", "team:write"), "portals": (UM, UM), "users": (UM, UM), "settings": (OW, OW)}
SPECIAL = {("events", "delete"): "events:delete", ("expenses", "validate"): FW}


def prim(m: str, a: str):
    if (m, a) in SPECIAL:
        return SPECIAL[(m, a)]
    return PRIM[m][0 if a in ("view", "export") else 1]


P = r"\{\w+\}"
TO_INVOICE = re.compile(rf"^quotes/{P}/invoice$")
CREATE = re.compile(rf"^(quotes/direct|events/{P}/(quotes|positions)|tasks/quick|quotes/{P}/(duplicate|new-version)|quote-templates/{P}/use)$")
VALIDATE = re.compile(r"(/status$|validate|approve|reject)")
WITH_VALIDATE = {"quotes", "invoices", "expenses", "staff", "purchases", "providers", "portals"}
SEND_QUOTES = re.compile(rf"^(quotes/{P}/(send|signature|share|invoice)|invoices/{P}/remind)$")
SEND_MESSAGES = re.compile(rf"^(messaging/send|messaging/conversations/{P}/reply|events/{P}/portal/messages)$")
CELLS: dict = {}


def _rel(path: str) -> str:
    return path.removeprefix("/api/").removeprefix("crm/").strip("/")


def classify(method: str, path: str, fmt: str = "") -> tuple:
    p = _rel(path)
    segs = p.split("/")
    mod = FIRST.get(segs[0])
    if segs[0] == "events" and len(segs) > 2:
        mod = EVENT_SUB.get(segs[2], "events")
    if not mod:
        return None, None
    if p.endswith("installation/pdf"):
        return "logistics", "view"
    if method == "GET" and segs[0] == "events" and mod == "quotes":
        mod = "events"
    if p.endswith("/sync"):
        return mod, "view"
    if method == "GET":
        return mod, "export" if "export" in p or fmt in ("csv", "xlsx") else "view"
    if method == "DELETE":
        return mod, "delete"
    if method == "POST":
        if TO_INVOICE.search(p):
            return "invoices", "create"
        if mod in WITH_VALIDATE and VALIDATE.search(p):
            return mod, "validate"
        if len(segs) == 1 or CREATE.search(p):
            return mod, "create"
    return mod, "update"


def switch(method: str, path: str) -> str | None:
    if method != "POST":
        return None
    p = _rel(path)
    return "send_quotes_invoices" if SEND_QUOTES.search(p) else "send_client_messages" if SEND_MESSAGES.search(p) else None


def _perms(dependant):
    for d in dependant.dependencies:
        if hasattr(d.call, "perm"):
            yield d.call.perm
        yield from _perms(d)


def walk(routes):
    for r in routes:
        sub = getattr(r, "original_router", None)
        if sub is not None:
            yield from walk(sub.routes)
        else:
            yield r


def init(app) -> None:
    CELLS.clear()
    for r in walk(app.routes):
        dep = getattr(r, "dependant", None)
        if not dep or not r.path.startswith("/api/"):
            continue
        ps = list(_perms(dep))
        for meth in (r.methods or []) if ps else []:
            m, a = classify(meth, r.path)
            if m:
                CELLS.setdefault(m, {}).setdefault(a, set()).update(ps)
    for row in CELLS.values():
        row.setdefault("export", set()).update(row.get("view", ()))
    import trash
    for m in trash.MODULES:
        CELLS.setdefault(m, {}).setdefault("delete", set()).add("trash")
    if len(CELLS) < len(KEYS):
        raise RuntimeError("Grille de permissions incomplète : les routes n'ont pas été lues")


def actions_of(m: str) -> list:
    return [a for a in ACTIONS if CELLS.get(m, {}).get(a)]


def allowed(grid: dict, m: str, a: str, perm) -> bool:
    """La case de la grille décide pour les routes régies par le droit principal du module ; une route régie par un autre droit ne demande que « Voir »."""
    row = grid.get(m) or {}
    if row.get(a):
        return True
    if a == "view":
        return False
    p = prim(m, a)
    strict = perm == p or (p is None and perm in BASE) or (perm not in BASE and perm in PRIM[m])
    return not strict and bool(row.get("view"))


def grid_from(perms, scope: str = "all") -> dict:
    """Grille équivalente à une liste de droits historiques."""
    perms, g = set(perms), {}
    for m in KEYS:
        view = prim(m, "view") in perms
        row = {"view": view}
        for a in ACTIONS[1:]:
            p = prim(m, a)
            row[a] = view and bool(CELLS.get(m, {}).get(a)) and (p in perms if p else True)
        row["scope"] = "all"
        g[m] = row
    g["events"]["scope"] = scope
    g["tasks"]["scope"] = "own" if scope == "assigned" else "all"
    g["expenses"]["scope"] = "all" if "finance:read" in perms else "own"
    return g


def fill(grid, perms):
    """Module ajouté après la création du profil : ligne déduite des droits, sans écriture en base."""
    if not grid:
        return grid
    out = dict(grid)
    for m, pv, pw in (("finance", "pilot:view", "pilot:manage"), ("social", "social:view", "social:manage"), ("communication", "comms:view", "comms:manage")):
        if m not in out:
            v, w = pv in perms, pw in perms
            out[m] = {"view": v, "create": v and w, "update": v and w, "delete": v and w, "export": v, "validate": False, "scope": "all"}
    return out


def clean(raw: dict) -> dict:
    g = {}
    for m in KEYS:
        r = raw.get(m) or {}
        row = {a: bool(r.get(a)) and bool(CELLS.get(m, {}).get(a)) for a in ACTIONS}
        if not row["view"]:
            row = {a: False for a in ACTIONS}
        row["scope"] = r.get("scope") if r.get("scope") in SCOPES.get(m, ["all"]) else "all"
        g[m] = row
    return g


def derive(grid: dict) -> set:
    out = {prim(m, a) for m, row in grid.items() for a in ACTIONS if row.get(a)}
    return {p for p in out if p}
