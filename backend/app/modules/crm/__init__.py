"""CRM & pipeline — Prospects, opportunités, étapes, motifs de refus, relances."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='crm',
    name='CRM & pipeline',
    category='ventes',
    description='Prospects, opportunités, étapes, motifs de refus, relances',
    depends_on=['contacts'],
    permissions=["read", "write"],
    status='beta',
    market=None,
)
