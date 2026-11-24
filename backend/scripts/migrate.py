"""Applique les migrations à toutes les bases sociétés. Lancé à chaque déploiement
(Render : preDeployCommand). Rejouable sans risque."""
import asyncio

from app.core.db import ClusterRouter, ensure_control_indexes
from app.core.provisioning import migrate_all


async def main() -> None:
    router = ClusterRouter.from_settings()
    await ensure_control_indexes(router.control)
    done = await migrate_all(router)
    print(f"{len(done)} base(s) société à jour")


if __name__ == "__main__":
    asyncio.run(main())
