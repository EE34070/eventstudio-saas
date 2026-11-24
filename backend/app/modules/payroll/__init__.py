"""Pôle social — Contrats, salaires, heures, congés, CDDU intermittents (droit français)."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='payroll',
    name='Pôle social',
    category='gestion',
    description='Contrats, salaires, heures, congés, CDDU intermittents (droit français)',
    depends_on=['staff'],
    permissions=["read", "write"],
    status='planned',
    market='FR',
)
