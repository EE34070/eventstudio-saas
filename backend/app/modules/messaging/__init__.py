"""Messagerie unifiée — Gmail, WhatsApp, Instagram dans une seule boîte, écran scindé mail/devis."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='messaging',
    name='Messagerie unifiée',
    category='gestion',
    description='Gmail, WhatsApp, Instagram dans une seule boîte, écran scindé mail/devis',
    depends_on=['contacts'],
    permissions=["read", "write"],
    status='planned',
    market=None,
)
