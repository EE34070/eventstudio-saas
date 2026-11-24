"""Copie les fichiers du stockage Emergent vers un bucket S3 / Cloudflare R2, en gardant les mêmes clés.

À lancer depuis backend/, dans l'environnement Emergent (EMERGENT_LLM_KEY présent), avec S3_ENDPOINT, S3_BUCKET,
S3_ACCESS_KEY et S3_SECRET_KEY dans l'environnement :
    python scripts/copy_files_to_s3.py --mongo-url ... --db ...
"""
import argparse
import os
import sys

a = argparse.ArgumentParser()
a.add_argument("--mongo-url", required=True)
a.add_argument("--db", required=True)
args = a.parse_args()
os.environ["MONGO_URL"], os.environ["DB_NAME"] = args.mongo_url, args.db
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient  # noqa: E402

import routes_files as rf  # noqa: E402

ok = ko = 0
for f in MongoClient(args.mongo_url)[args.db].files.find({"is_deleted": False}):
    try:
        data = rf._call("GET", f["storage_path"]).content
        rf.s3_client().put_object(Bucket=os.environ["S3_BUCKET"], Key=f["storage_path"], Body=data, ContentType=f["content_type"])
        ok += 1
    except Exception as exc:
        ko += 1
        print(f"ÉCHEC {f['storage_path']}: {exc}")
print(f"{ok} fichier(s) copié(s), {ko} échec(s)")
