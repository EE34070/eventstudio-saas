"""Déroulé & rétroplanning — Import IA de plannings organisateur, étapes internes, feuilles de mission hors ligne."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='planning',
    name='Déroulé & rétroplanning',
    category='operations',
    description='Import IA de plannings organisateur, étapes internes, feuilles de mission hors ligne',
    depends_on=['events'],
    permissions=["read", "write"],
    status='planned',
    market=None,
)
