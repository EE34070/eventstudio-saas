"""Wedding planner — Timeline, plan de table, coordination prestataires."""
from app.core.modules import ModuleManifest

MANIFEST = ModuleManifest(
    key='wedding_planner',
    name='Wedding planner',
    category='metiers',
    description='Timeline, plan de table, coordination prestataires',
    depends_on=['events', 'planning'],
    permissions=["read", "write"],
    status='planned',
    market=None,
)
