"""Espaces clients — Accès sans mot de passe par code e-mail, modules activables par événement."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='client_portal',
    name='Espaces clients',
    category='ventes',
    description='Accès sans mot de passe par code e-mail, modules activables par événement',
    depends_on=['events'],
    permissions=["read", "write"],
    status='beta',
    market=None,
)
