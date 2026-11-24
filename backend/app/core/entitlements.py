"""Droits commerciaux (entitlements) : quels modules et quelles limites pour une organisation.

modules actifs = modules core
               ∪ modules du plan
               ∪ add-ons achetés
               ∪ forçages « enabled » (support / offre sur mesure)
               − modules désactivés par l'organisation elle-même
puis fermeture par dépendances (activer « logistics » active « inventory »).

Les plans sont définis ici en code (versionnés, testés) ; Stripe ne porte que le prix.
"""
from dataclasses import dataclass, field

from .modules import dependency_closure, registry

VENTES = {"crm", "quotes", "invoicing", "client_portal"}
OPERATIONS = {"catalog", "inventory", "logistics", "staff", "planning", "floorplan"}
METIERS = {"dj", "sound_light", "photobooth", "wedding_planner", "catering"}
GESTION = {"purchasing", "finance", "payroll", "communication", "messaging"}

PLANS: dict[str, dict] = {
    "essentiel": {
        "modules": VENTES | {"catalog"},
        "metier_slots": 1,      # nombre de modules métier au choix
        "limits": {"seats": 1, "storage_gb": 5, "ai_credits": 200, "orgs_brands": 1},
    },
    "pro": {
        "modules": VENTES | OPERATIONS | {"messaging", "purchasing"},
        "metier_slots": 99,
        "limits": {"seats": 5, "storage_gb": 50, "ai_credits": 2000, "orgs_brands": 3},
    },
    "agence": {
        "modules": VENTES | OPERATIONS | GESTION,
        "metier_slots": 99,
        "limits": {"seats": 15, "storage_gb": 200, "ai_credits": 10000, "orgs_brands": 10},
    },
    # Offre sur mesure / déploiement dédié (cluster dédié possible)
    "enterprise": {
        "modules": VENTES | OPERATIONS | GESTION | METIERS,
        "metier_slots": 99,
        "limits": {"seats": 999, "storage_gb": 1000, "ai_credits": 100000, "orgs_brands": 99},
    },
}


@dataclass
class Entitlements:
    plan: str
    modules: set[str]
    limits: dict[str, int] = field(default_factory=dict)
    status: str = "active"  # trialing | active | past_due | canceled

    def has_module(self, key: str) -> bool:
        return key in self.modules

    @property
    def read_only(self) -> bool:
        # Abonnement impayé/annulé : l'organisation garde l'accès en lecture (export RGPD)
        return self.status in {"past_due", "canceled"}


def resolve(org: dict) -> Entitlements:
    sub = org.get("subscription", {})
    plan_key = sub.get("plan", "essentiel")
    plan = PLANS.get(plan_key, PLANS["essentiel"])
    reg = registry()

    core = {k for k, m in reg.items() if m.is_core}
    if plan["metier_slots"] >= len(METIERS):
        chosen_metiers = METIERS
    else:
        picked = [m for m in sub.get("metier_modules", []) if m in METIERS]
        chosen_metiers = set(picked[: plan["metier_slots"]])

    overrides = org.get("module_overrides", {})
    modules = core | plan["modules"] | chosen_metiers | set(sub.get("addons", []))
    modules |= set(overrides.get("enabled", []))
    modules -= set(overrides.get("disabled", [])) - core  # un module core ne se désactive pas
    modules = dependency_closure(modules) & set(reg)

    limits = {**plan["limits"], **sub.get("limit_overrides", {})}
    return Entitlements(plan=plan_key, modules=modules, limits=limits, status=sub.get("status", "active"))
