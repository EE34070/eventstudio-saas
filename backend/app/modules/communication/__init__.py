"""Communication — Publication Instagram/Facebook, calendrier éditorial, collecte photos prestataires."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='communication',
    name='Communication',
    category='gestion',
    description='Publication Instagram/Facebook, calendrier éditorial, collecte photos prestataires',
    depends_on=['events'],
    permissions=["read", "write"],
    status='planned',
    market=None,
)
