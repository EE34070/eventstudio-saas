"""Traiteur — Devis par convive, 14 allergènes."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='catering',
    name='Traiteur',
    category='metiers',
    description='Devis par convive, 14 allergènes',
    depends_on=['quotes'],
    permissions=["read", "write"],
    status='planned',
    market=None,
)
