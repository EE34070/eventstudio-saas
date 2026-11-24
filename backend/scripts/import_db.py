"""Importe un export JSON : python scripts/import_db.py --mongo-url ... --db ... [--in dump]

Refuse d'écrire dans une collection non vide (aucune suppression, aucun écrasement)."""
import argparse
import glob
import os

from bson import json_util
from pymongo import MongoClient

a = argparse.ArgumentParser()
a.add_argument("--mongo-url", required=True)
a.add_argument("--db", required=True)
a.add_argument("--in", dest="src", default="dump")
a.add_argument("--skip", default="", help="collections à ignorer, séparées par des virgules")
a.add_argument("--reset-clerk-links", action="store_true", help="détache les fiches Équipe des anciens comptes Clerk")
args = a.parse_args()
skip = {x.strip() for x in args.skip.split(",") if x.strip()}

db = MongoClient(args.mongo_url)[args.db]
for path in sorted(glob.glob(os.path.join(args.src, "*.json"))):
    name = os.path.splitext(os.path.basename(path))[0]
    if name in skip:
        print(f"{name}: ignorée (--skip)")
        continue
    with open(path, encoding="utf-8") as fh:
        docs = json_util.loads(fh.read())
    if db[name].estimated_document_count():
        print(f"{name}: collection non vide, ignorée")
        continue
    if name == "team" and args.reset_clerk_links:
        for d in docs:
            d["user_id"] = None
    if docs:
        db[name].insert_many(docs)
    print(f"{name}: {len(docs)} document(s) importé(s)")
