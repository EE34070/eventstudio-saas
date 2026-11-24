"""Logistique & tournées — Chargement, livraisons/retraits, rotations, véhicules, réemploi du matériel déplacé."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='logistics',
    name='Logistique & tournées',
    category='operations',
    description='Chargement, livraisons/retraits, rotations, véhicules, réemploi du matériel déplacé',
    depends_on=['inventory', 'events'],
    permissions=["read", "write"],
    status='planned',
    market=None,
)
