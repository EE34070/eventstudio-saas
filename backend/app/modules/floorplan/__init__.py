"""Plans d'implantation 2D — Plans annotables, implantation du matériel."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='floorplan',
    name="Plans d'implantation 2D",
    category='operations',
    description='Plans annotables, implantation du matériel',
    depends_on=['events'],
    permissions=["read", "write"],
    status='planned',
    market=None,
)
