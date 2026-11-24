"""Contacts — personnes et structures (clients, organisateurs, lieux, prestataires). Module core."""
from app.core.modules import ModuleManifest

from .router import router

MANIFEST = ModuleManifest(
    key="contacts",
    name="Contacts",
    category="core",
    description="Personnes, structures (gérante, assistante…), rôles, langue de communication",
    is_core=True,
    permissions=["read", "write"],
    collections=["contacts"],
    indexes={"contacts": [[("org_id", 1), ("kind", 1), ("display_name", 1)], [("org_id", 1), ("email", 1)]]},
    router=router,
    status="stable",
)
