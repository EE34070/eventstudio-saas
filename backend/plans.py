"""Offres commerciales du SaaS : rubriques accessibles, modules métier, utilisateurs inclus.

Deux niveaux de modules coexistent dans l'application :
  - les RUBRIQUES (access_grid.MODULES : devis, stock, finance, pôle social…) -> limitées par l'offre
  - les MODULES MÉTIER (orgs.modules : dj, son_lumiere, photobooth…)        -> nombre limité par l'offre

orgs.subscription = {"plan": "pro", "status": "active|trialing|past_due|canceled",
                     "trial_ends_at": "...", "addons": ["finance"], "extra_seats": 0}
Société sans subscription (clients historiques, dont Exclusivity Events) : offre « enterprise ».
Impayé ou résiliation : lecture seule (402 sur toute écriture), les données restent exportables.
"""
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

VENTES = {"events", "contacts", "crm", "quotes", "invoices", "accounting", "catalog", "venues", "providers",
          "messages", "inbound", "tasks", "team", "portals", "users", "settings"}
OPERATIONS = {"stock", "logistics", "vehicles", "staff", "music", "purchases", "expenses"}
GESTION = {"finance", "social", "communication"}

PLANS: dict[str, dict] = {
    "essentiel": {"label": "Essentiel", "sections": VENTES, "business_modules": 1, "seats": 1},
    "pro": {"label": "Pro", "sections": VENTES | OPERATIONS, "business_modules": 99, "seats": 5},
    "agence": {"label": "Agence", "sections": VENTES | OPERATIONS | GESTION, "business_modules": 99, "seats": 15},
    "enterprise": {"label": "Entreprise", "sections": VENTES | OPERATIONS | GESTION, "business_modules": 99, "seats": 9999},
}
READ_ONLY_STATUSES = {"past_due", "canceled", "unpaid"}
TRIAL_DAYS = 14


def subscription(org: dict) -> dict:
    return org.get("subscription") or {"plan": "enterprise", "status": "active"}


def plan_of(org: dict) -> dict:
    return PLANS.get(subscription(org).get("plan"), PLANS["essentiel"])


def sections(org: dict) -> set:
    sub = subscription(org)
    return set(plan_of(org)["sections"]) | set(sub.get("addons") or [])


def seats(org: dict) -> int:
    return plan_of(org)["seats"] + int(subscription(org).get("extra_seats") or 0)


def read_only(org: dict) -> bool:
    sub = subscription(org)
    if sub.get("status") in READ_ONLY_STATUSES:
        return True
    if sub.get("status") == "trialing" and (sub.get("trial_ends_at") or "9999") < datetime.now(timezone.utc).isoformat():
        return True
    return False


def new_trial(plan: str = "pro") -> dict:
    """Offre posée à l'inscription en libre-service."""
    return {"plan": plan, "status": "trialing",
            "trial_ends_at": (datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)).isoformat()}


def enforce(org: dict, section: str | None, method: str) -> None:
    """Appelé pour chaque requête interne authentifiée (core.need)."""
    if method not in ("GET", "HEAD", "OPTIONS") and read_only(org):
        raise HTTPException(402, "Abonnement inactif : votre espace est en lecture seule. Mettez à jour votre abonnement.")
    if section and section not in sections(org):
        raise HTTPException(403, f"La rubrique « {section} » n'est pas incluse dans votre offre {plan_of(org)['label']}.")


def check_business_modules(org: dict, modules: list) -> None:
    limit = plan_of(org)["business_modules"]
    if len(modules) > limit:
        raise HTTPException(403, f"Votre offre {plan_of(org)['label']} inclut {limit} module(s) métier.")


def check_seats(org: dict, active_members: int) -> None:
    if active_members >= seats(org):
        raise HTTPException(403, f"Nombre d'utilisateurs inclus atteint ({seats(org)}) : ajoutez des utilisateurs à votre offre.")


def summary(org: dict) -> dict:
    sub, p = subscription(org), plan_of(org)
    return {"plan": sub.get("plan", "enterprise"), "label": p["label"], "status": sub.get("status", "active"),
            "trial_ends_at": sub.get("trial_ends_at"), "sections": sorted(sections(org)),
            "business_modules": p["business_modules"], "seats": seats(org), "read_only": read_only(org)}
