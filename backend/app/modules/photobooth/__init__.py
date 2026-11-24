"""Photobooth — Habillage, galerie, partage, statistiques."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='photobooth',
    name='Photobooth',
    category='metiers',
    description='Habillage, galerie, partage, statistiques',
    depends_on=['events'],
    permissions=["read", "write"],
    status='planned',
    market=None,
)
