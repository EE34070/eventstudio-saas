"""Catalogue produits & services — Produits, services, packs multilingues, unités de mesure, fournisseurs multiples."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='catalog',
    name='Catalogue produits & services',
    category='operations',
    description='Produits, services, packs multilingues, unités de mesure, fournisseurs multiples',
    depends_on=[],
    permissions=["read", "write"],
    status='beta',
    market=None,
)
