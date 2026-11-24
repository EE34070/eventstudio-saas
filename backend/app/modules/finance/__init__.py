"""Finance & prévisionnel — Trésorerie, prévisionnel 3 ans, rentabilité produits/packs, dossier banquier."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='finance',
    name='Finance & prévisionnel',
    category='gestion',
    description='Trésorerie, prévisionnel 3 ans, rentabilité produits/packs, dossier banquier',
    depends_on=['invoicing'],
    permissions=["read", "write"],
    status='planned',
    market=None,
)
