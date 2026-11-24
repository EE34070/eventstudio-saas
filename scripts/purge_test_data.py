"""Purge des données de test avant la mise en production.

  python3 scripts/purge_test_data.py --dry-run            -> rapport seul, rien n'est modifié
  python3 scripts/purge_test_data.py --apply --yes        -> sauvegarde JSON dans backups/ puis suppression

Supprime uniquement : les sociétés de test (slug qa-sandbox ou nom commençant par TEST_) avec toutes leurs données, et les comptes +clerk_test rattachés à ces sociétés.
Ne supprime JAMAIS rien dans une société réelle : les éléments TEST_ ou comptes de test qui s'y trouvent sont seulement listés, à traiter à la main.
Base cible : MONGO_URL et DB_NAME (à défaut, backend/.env).
"""
import argparse
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from bson import json_util
from dotenv import load_dotenv
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / "backend" / ".env")
TEST_USER = re.compile(r"\+clerk_test@|^(qa|test)_.*@example\.com$", re.I)
NAMED = {"events": "title", "contacts": "company", "equipment": "name", "venues": "name", "tasks": "title", "access_profiles": "name", "team": "name"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    if a.apply == a.dry_run:
        ap.error("choisir --dry-run ou --apply")
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    orgs = list(db.orgs.find({"$or": [{"slug": "qa-sandbox"}, {"name": {"$regex": "^TEST_"}}]}, {"_id": 0, "id": 1, "name": 1, "slug": 1}))
    ids = [o["id"] for o in orgs]
    colls = sorted(c for c in db.list_collection_names() if c != "orgs")
    plan = {c: db[c].count_documents({"org_id": {"$in": ids}}) for c in colls}
    plan = {c: n for c, n in plan.items() if n}
    print(f"Base {os.environ['DB_NAME']} — sociétés de test : {[(o['name'], o.get('slug')) for o in orgs] or 'aucune'}")
    for c, n in plan.items():
        print(f"  à supprimer  {c:32} {n}")
    print("À traiter à la main dans les sociétés réelles (jamais supprimé par ce script) :")
    real = {"org_id": {"$nin": ids}}
    for u in db.users.find(real, {"_id": 0, "email": 1, "org_id": 1}):
        if TEST_USER.search(u.get("email") or ""):
            print(f"  compte de test  {u['email']}  (société {u.get('org_id')})")
    for c, f in NAMED.items():
        n = db[c].count_documents({**real, f: {"$regex": "^TEST_"}})
        if n:
            print(f"  {c}.{f} commençant par TEST_ : {n}")
    if a.dry_run:
        print("Simulation : rien n'a été modifié.")
        return
    if not a.yes:
        raise SystemExit("Ajoutez --yes pour confirmer la suppression.")
    out = ROOT / "backups" / f"purge-test-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    out.mkdir(parents=True)
    (out / "orgs.json").write_text(json_util.dumps(list(db.orgs.find({"id": {"$in": ids}}))))
    for c in plan:
        (out / f"{c}.json").write_text(json_util.dumps(list(db[c].find({"org_id": {"$in": ids}}))))
        db[c].delete_many({"org_id": {"$in": ids}})
    db.orgs.delete_many({"id": {"$in": ids}})
    print(f"Supprimé. Sauvegarde : {out}. Pensez à supprimer les comptes de test dans Clerk.")


if __name__ == "__main__":
    main()
