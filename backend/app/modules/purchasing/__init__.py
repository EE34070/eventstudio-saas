"""Achats — Factures d'achat (OCR IA), abonnements, projets d'achat, mise à jour du stock."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='purchasing',
    name='Achats',
    category='gestion',
    description="Factures d'achat (OCR IA), abonnements, projets d'achat, mise à jour du stock",
    depends_on=['catalog'],
    permissions=["read", "write"],
    status='planned',
    market=None,
)
