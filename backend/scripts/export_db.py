"""Exporte chaque collection en JSON : python scripts/export_db.py --mongo-url ... --db ... [--out dump]"""
import argparse
import os

from bson import json_util
from pymongo import MongoClient

a = argparse.ArgumentParser()
a.add_argument("--mongo-url", required=True)
a.add_argument("--db", required=True)
a.add_argument("--out", default="dump")
args = a.parse_args()

db = MongoClient(args.mongo_url)[args.db]
os.makedirs(args.out, exist_ok=True)
for name in sorted(db.list_collection_names()):
    docs = list(db[name].find({}))
    with open(os.path.join(args.out, f"{name}.json"), "w", encoding="utf-8") as fh:
        fh.write(json_util.dumps(docs, ensure_ascii=False))
    print(f"{name}: {len(docs)} document(s)")
