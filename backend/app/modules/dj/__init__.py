"""Module DJ — Playlists par moment, affectation DJ partenaires, disponibilités, conflits, alertes de couverture."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='dj',
    name='Module DJ',
    category='metiers',
    description='Playlists par moment, affectation DJ partenaires, disponibilités, conflits, alertes de couverture',
    depends_on=['events', 'staff'],
    permissions=["read", "write"],
    status='beta',
    market=None,
)
