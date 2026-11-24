"""Événements — fiche événement unique partagée par tous les modules. Module core."""
from app.core.modules import ModuleManifest

from .router import router

MANIFEST = ModuleManifest(
    key="events",
    name="Événements & agenda",
    category="core",
    description="Fiche événement, client + organisateur, lieux et contacts sur place, plages de dates, modules activés par événement",
    is_core=True,
    depends_on=["contacts"],
    permissions=["read", "write"],
    collections=["events"],
    indexes={"events": [[("org_id", 1), ("starts_at", 1)], [("org_id", 1), ("status", 1), ("starts_at", 1)]]},
    router=router,
    status="stable",
)
