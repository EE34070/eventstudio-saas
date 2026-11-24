"""Sauvegarde chiffrée de la base MongoDB, à lancer chaque jour (tâche planifiée Render).

  python3 scripts/backup_mongo.py backup         -> export chiffré, envoyé sur R2 (S3_*) ou, sans R2, écrit dans backups/
  python3 scripts/backup_mongo.py restore-test   -> restaure la dernière sauvegarde dans une base temporaire, compare les volumes, supprime la base temporaire

Variables : MONGO_URL, DB_NAME, BACKUP_ENCRYPTION_KEY (clé Fernet), S3_ENDPOINT / S3_BUCKET / S3_ACCESS_KEY / S3_SECRET_KEY, BACKUP_KEEP_DAYS (défaut 30).
"""
import gzip
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bson import json_util
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / "backend" / ".env")
PREFIX, LOCAL = "backups/mongo/", ROOT / "backups" / "mongo"
S3 = all(os.environ.get(k) for k in ("S3_ENDPOINT", "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY"))


def s3():
    import boto3
    return boto3.client("s3", endpoint_url=os.environ["S3_ENDPOINT"], aws_access_key_id=os.environ["S3_ACCESS_KEY"], aws_secret_access_key=os.environ["S3_SECRET_KEY"], region_name=os.environ.get("S3_REGION", "auto"))


def names() -> list:
    if S3:
        return sorted(o["Key"][len(PREFIX):] for o in s3().list_objects_v2(Bucket=os.environ["S3_BUCKET"], Prefix=PREFIX).get("Contents", []))
    return sorted(p.name for p in LOCAL.glob("*.enc"))


def backup(db, key: Fernet) -> None:
    data = {c: list(db[c].find()) for c in db.list_collection_names()}
    blob = key.encrypt(gzip.compress(json_util.dumps(data).encode()))
    name = f"{os.environ['DB_NAME']}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json.gz.enc"
    limit = f"{os.environ['DB_NAME']}-{datetime.now(timezone.utc) - timedelta(days=int(os.environ.get('BACKUP_KEEP_DAYS') or 30)):%Y%m%d}"
    old = [n for n in names() if n < limit]
    if S3:
        s3().put_object(Bucket=os.environ["S3_BUCKET"], Key=PREFIX + name, Body=blob)
        for n in old:
            s3().delete_object(Bucket=os.environ["S3_BUCKET"], Key=PREFIX + n)
    else:
        LOCAL.mkdir(parents=True, exist_ok=True)
        (LOCAL / name).write_bytes(blob)
        for n in old:
            (LOCAL / n).unlink()
    print(f"Sauvegarde {name} : {len(data)} collections, {sum(map(len, data.values()))} documents, {len(blob) // 1024} Ko, {'R2' if S3 else 'dossier local backups/mongo (R2 non configuré)'}")


def restore_test(client, db, key: Fernet) -> None:
    all_names = names()
    if not all_names:
        sys.exit("Aucune sauvegarde trouvée.")
    name = all_names[-1]
    blob = s3().get_object(Bucket=os.environ["S3_BUCKET"], Key=PREFIX + name)["Body"].read() if S3 else (LOCAL / name).read_bytes()
    data = json_util.loads(gzip.decompress(key.decrypt(blob)))
    scratch = f"{os.environ['DB_NAME']}_restore_test"[:60]
    if scratch in client.list_database_names():
        sys.exit(f"La base temporaire {scratch} existe déjà : vérifiez-la et supprimez-la à la main avant de relancer.")
    tmp = client[scratch]
    try:
        for c, docs in data.items():
            if docs:
                tmp[c].insert_many(docs)
        bad = [c for c, docs in data.items() if tmp[c].count_documents({}) != len(docs)]
        sample = next((c for c, d in data.items() if d), None)
        same = not sample or tmp[sample].find_one({"_id": data[sample][0]["_id"]}) == data[sample][0]
    finally:
        client.drop_database(scratch)
    if bad or not same:
        sys.exit(f"ÉCHEC de la restauration de {name} : {bad or 'contenu différent'}")
    print(f"Restauration testée avec succès : {name}, {len(data)} collections, {sum(map(len, data.values()))} documents relus à l'identique. Base temporaire supprimée.")


if __name__ == "__main__":
    if not os.environ.get("BACKUP_ENCRYPTION_KEY"):
        sys.exit("BACKUP_ENCRYPTION_KEY manquante.")
    k = Fernet(os.environ["BACKUP_ENCRYPTION_KEY"].encode())
    cl = MongoClient(os.environ["MONGO_URL"])
    d = cl[os.environ["DB_NAME"]]
    {"backup": lambda: backup(d, k), "restore-test": lambda: restore_test(cl, d, k)}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
