"""Devis & contrats — Devis avancés (sections, emplacements, plages de dates), packs, CGV multilingues, signature électronique."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='quotes',
    name='Devis & contrats',
    category='ventes',
    description='Devis avancés (sections, emplacements, plages de dates), packs, CGV multilingues, signature électronique',
    depends_on=['contacts', 'events', 'catalog'],
    permissions=["read", "write"],
    status='beta',
    market=None,
)
