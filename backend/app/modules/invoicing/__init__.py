"""Facturation & paiements — Factures depuis devis acceptés, acomptes/soldes, réception des paiements, Stripe, export comptable, e-facturation via PDP partenaire."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='invoicing',
    name='Facturation & paiements',
    category='ventes',
    description='Factures depuis devis acceptés, acomptes/soldes, réception des paiements, Stripe, export comptable, e-facturation via PDP partenaire',
    depends_on=['quotes'],
    permissions=["read", "write"],
    status='beta',
    market=None,
)
