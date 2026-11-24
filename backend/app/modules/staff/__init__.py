"""Staff & missions — Inscription prestataires, postes, candidatures, heures, factures prestataires."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='staff',
    name='Staff & missions',
    category='operations',
    description='Inscription prestataires, postes, candidatures, heures, factures prestataires',
    depends_on=['events'],
    permissions=["read", "write"],
    status='planned',
    market=None,
)
