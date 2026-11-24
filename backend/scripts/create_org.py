"""Crée une société et sa base dédiée (en attendant l'inscription en libre-service).

python -m scripts.create_org --name "Exclusivity Events" --slug exclusivity-events \
    --owner user_XXXX --plan enterprise --status active
"""
import argparse
import asyncio

from app.core.db import ClusterRouter, ensure_control_indexes
from app.core.provisioning import create_org


async def main(a: argparse.Namespace) -> None:
    router = ClusterRouter.from_settings()
    await ensure_control_indexes(router.control)
    org = await create_org(router, name=a.name, slug=a.slug, owner_user_id=a.owner, plan=a.plan,
                           status=a.status, dedicated_cluster=a.cluster)
    print(f"Société {org['_id']} prête — base {org['db']['name']} sur le cluster {org['db']['cluster']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True)
    p.add_argument("--slug", required=True)
    p.add_argument("--owner", required=True, help="identifiant utilisateur Clerk du propriétaire")
    p.add_argument("--plan", default="essentiel")
    p.add_argument("--status", default="trialing")
    p.add_argument("--cluster", default=None, help="cluster dédié (offre Entreprise)")
    asyncio.run(main(p.parse_args()))
