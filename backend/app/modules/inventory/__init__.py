"""Stock & matériel — Multi-entrepôts, dépôts sur site, kits/nomenclatures, anti double-réservation, états des lieux."""
from app.core.modules import ModuleManifest

from .router import router

MANIFEST = ModuleManifest(
    key='inventory',
    name='Stock & matériel',
    category='operations',
    description='Multi-entrepôts, dépôts sur site, kits/nomenclatures, anti double-réservation, états des lieux',
    depends_on=['catalog'],
    permissions=["read", "write"],
    collections=["warehouses", "stock_items", "reservations"],
    indexes={"warehouses": [[("org_id", 1), ("name", 1)]]},
    router=router,
    status='beta',
    market=None,
)
