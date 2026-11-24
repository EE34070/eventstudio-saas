"""Import idempotent du catalogue Odoo (upsert par `ref`).

  python backend/scripts/import_catalogue_odoo.py --file chemin.json --org exclusivity-events --dry-run
  python backend/scripts/import_catalogue_odoo.py --file chemin.json --org exclusivity-events --apply

Utilise MONGO_URL et DB_NAME de l'environnement (ou backend/.env). Aucune autre variable requise.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def show(rep: dict) -> None:
    print(f"\n=== {'IMPORT APPLIQUÉ' if rep['applied'] else 'SIMULATION (dry-run) : rien n a été écrit'} ===")
    print(f"Lignes lues : {rep['total']} | créés : {rep['created']} | mis à jour : {rep['updated']} | ignorés (inchangés) : {rep['unchanged']} | refusés : {len(rep['refused'])}")
    print(f"Niveaux de stock > 0 : {rep['stock_levels']} ({rep['stock_units']} unités) dans « {rep['warehouse']} »")
    print(f"Prix à définir : {rep['price_missing']} | à vérifier : {rep['to_check']} | catégories : {len(rep['by_category'])} | sous-catégories : {rep['subcategories']}")
    for title, key in (("Par type", "by_type"), ("Par catégorie", "by_category")):
        print(f"\n{title} (créés / mis à jour / inchangés)")
        for k, v in sorted(rep[key].items()):
            print(f"  {k:<28} {v['created']:>4} / {v['updated']:>4} / {v['unchanged']:>4}")
    if rep["rounded"]:
        print("\nStocks décimaux arrondis à l'entier inférieur : " + " ; ".join(rep["rounded"]))
    if rep["existing_not_imported"]:
        print("\nProduits déjà présents (non issus de l'import) qui seraient mis à jour : " + ", ".join(rep["existing_not_imported"]))
    for r in rep["refused"]:
        print(f"REFUSÉ ligne {r['line']} ({r['ref']}) : {r['reason']}")
    print("\nChamps ajoutés à la fiche produit : " + ", ".join(rep["new_fields"]))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--org", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    import catalogue_import as ci
    if a.org not in ci.ALLOWED_SLUGS:
        print(f"Refusé : seule la société {ci.ALLOWED_SLUGS[0]} peut recevoir cet import (reçu : {a.org}).")
        return 2
    rows = json.loads(Path(a.file).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        print("Refusé : le fichier doit contenir une liste JSON de produits.")
        return 2
    if a.apply:
        from core import db
    else:
        from motor.motor_asyncio import AsyncIOMotorClient
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    orgs = await db.orgs.find({"slug": a.org}, {"_id": 0, "id": 1, "name": 1}).to_list(5)
    if len(orgs) != 1:
        print(f"Refusé : {len(orgs)} société(s) avec le slug {a.org} (une seule attendue).")
        return 2
    print(f"Société : {orgs[0]['name']} ({a.org}) | base : {os.environ['DB_NAME']}")
    show(await ci.run(db, orgs[0]["id"], rows, apply=a.apply))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
