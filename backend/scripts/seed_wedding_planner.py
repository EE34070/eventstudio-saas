"""Crée l'organisation de démonstration « Manon Jeanjean Wedding Planner » (données fictives).

python -m scripts.seed_wedding_planner --owner user_XXXX [--slug manon-jeanjean]
"""
import argparse
import asyncio

from app.core.db import ClusterRouter, ensure_control_indexes
from app.core.provisioning import create_org

BRANDING = {"app_name": "Manon Jeanjean", "layout": "focus", "home_path": "/mariages",
            "primary_color": "#1F3D2B", "background": "#F2F1EB", "surface": "#FAF9F5", "ink": "#4b5c4c",
            "muted": "#6b7a63", "line": "#cdd6c6", "soft": "#a9c0ac", "alert": "#9a3b2e",
            "font_display": "Cormorant Garamond", "font_body": "Montserrat"}


async def main(a: argparse.Namespace) -> None:
    router = ClusterRouter.from_settings()
    await ensure_control_indexes(router.control)
    org = await create_org(router, name="Manon Jeanjean Wedding Planner", slug=a.slug, owner_user_id=a.owner,
                           plan="essentiel", status="active")
    await router.control.orgs.update_one({"_id": org["_id"]}, {"$set": {
        "branding": BRANDING, "subscription.metier_modules": ["wedding_planner"]}})
    print(f"Organisation {org['_id']} prête, module wedding_planner actif.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--owner", required=True, help="identifiant utilisateur Clerk de l'organisatrice")
    p.add_argument("--slug", default="manon-jeanjean")
    asyncio.run(main(p.parse_args()))
