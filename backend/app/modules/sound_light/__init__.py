"""Son & lumière — Configurateur de scène, fiches techniques, alertes puissance électrique."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='sound_light',
    name='Son & lumière',
    category='metiers',
    description='Configurateur de scène, fiches techniques, alertes puissance électrique',
    depends_on=['inventory'],
    permissions=["read", "write"],
    status='planned',
    market=None,
)
