"""Purge des données de démonstration d'une société.

Usage :
  python3 scripts/purge_demo.py --org <org_id> --dry-run [--keep-contact <id> ...]
  python3 scripts/purge_demo.py --org <org_id> --apply   [--keep-contact <id> ...]
  python3 scripts/purge_demo.py --list-orgs

Base cible : variables MONGO_URL et DB_NAME (à défaut, backend/.env).
Conserve : société et paramètres, utilisateurs, membres d'équipe liés à un compte, connexion Gmail, conversations et messages,
métiers, modèles de message, modules. --apply sauvegarde d'abord en JSON dans backups/.
"""
import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from bson import json_util
from dotenv import load_dotenv
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / "backend" / ".env")
ALL = ["events", "event_modules", "venues", "equipment", "packs", "vehicles", "quotes", "invoices", "loadings", "deliveries", "missions",
       "service_requests", "request_recipients", "provider_unavailabilities", "provider_documents"]
COUNTERS = {"key": {"$regex": "^(event|quote|invoice)-"}}


def refs(value, out: set) -> set:
    if isinstance(value, dict):
        for v in value.values():
            refs(v, out)
    elif isinstance(value, list):
        for v in value:
            refs(v, out)
    elif isinstance(value, str) and value.startswith("file:"):
        out.add(value[5:])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--org")
    ap.add_argument("--keep-contact", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--list-orgs", action="store_true")
    ap.add_argument("--test-orgs", action="store_true", help="sociétés dont le nom commence par TEST_ (créées par les tests automatiques)")
    a = ap.parse_args()
    db = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    if a.list_orgs:
        for o in db.orgs.find({}, {"id": 1, "name": 1, "slug": 1}):
            print(o["id"], "|", o.get("name"), "|", o.get("slug", ""), "| événements :", db.events.count_documents({"org_id": o["id"]}))
        return
    if a.test_orgs and a.dry_run != a.apply:
        ids = [x["id"] for x in db.orgs.find({"name": {"$regex": "^TEST_"}})]
        f = {"org_id": {"$in": ids}}
        cols = [c for c in sorted(db.list_collection_names()) if db[c].count_documents(f)]
        print(f"Base : {db.name} — sociétés TEST_ : {len(ids)} — mode : {'APPLY' if a.apply else 'DRY-RUN'}")
        for c in cols:
            print(f"{c:28}{db[c].count_documents(f):>12}{db[c].count_documents({'org_id': {'$nin': ids}}):>10}")
        if a.apply:
            out = ROOT / "backups" / f"purge-test-orgs-{db.name}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
            out.mkdir(parents=True)
            (out / "orgs.json").write_text(json_util.dumps(list(db.orgs.find({"id": {"$in": ids}}))))
            for c in cols:
                (out / f"{c}.json").write_text(json_util.dumps(list(db[c].find(f))))
                db[c].delete_many(f)
            print("Sociétés supprimées :", db.orgs.delete_many({"id": {"$in": ids}, "name": {"$regex": "^TEST_"}}).deleted_count, "— sauvegarde :", out)
        return
    if not a.org or a.dry_run == a.apply:
        sys.exit("Indiquez --org <id> et soit --dry-run, soit --apply")
    org = db.orgs.find_one({"id": a.org})
    if not org:
        sys.exit("Société introuvable")
    o = {"org_id": a.org}
    sent = [i["number"] for i in db.invoices.find(o) if i.get("sent_at") or i.get("sent_to") or i.get("reminders")]
    if sent:
        sys.exit(f"ARRÊT : des factures ont été envoyées ({', '.join(sent)}). La numérotation FAC ne doit pas être réinitialisée.")
    keep_profiles = [p["id"] for p in db.provider_profiles.find({**o, "contact_id": {"$in": a.keep_contact}})]
    keep_files = refs(org, set())
    for p in db.provider_profiles.find({**o, "id": {"$in": keep_profiles}}):
        refs(p, keep_files)
    plan = {c: dict(o) for c in ALL}
    plan["provider_documents"] = {**o, "provider_id": {"$nin": keep_profiles}}
    plan["provider_unavailabilities"] = {**o, "provider_id": {"$nin": keep_profiles}}
    plan["contacts"] = {**o, "id": {"$nin": a.keep_contact}}
    plan["provider_profiles"] = {**o, "id": {"$nin": keep_profiles}}
    plan["team"] = {**o, "user_id": {"$in": [None, ""]}}
    plan["files"] = {**o, "id": {"$nin": sorted(keep_files)}}
    plan["counters"] = {**o, **COUNTERS}
    print(f"Base : {db.name} — société : {org.get('name')} ({a.org}) — mode : {'APPLY' if a.apply else 'DRY-RUN'}")
    print(f"{'collection':28}{'à supprimer':>12}{'conservé':>10}")
    for c, f in plan.items():
        n = db[c].count_documents(f)
        print(f"{c:28}{n:>12}{db[c].count_documents(o) - n:>10}")
    links = db.conversations.count_documents({**o, "$or": [{"contact_id": {"$nin": [None, *a.keep_contact]}}, {"event_id": {"$ne": None}}]})
    print(f"{'conversations (liens retirés)':28}{links:>12}{db.conversations.count_documents(o):>10}")
    for c in ("messages", "channel_accounts", "users", "provider_categories", "message_templates"):
        print(f"{c:28}{0:>12}{db[c].count_documents(o):>10}")
    if not a.apply:
        return
    out = ROOT / "backups" / f"purge-{db.name}-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    out.mkdir(parents=True)
    for c in [*plan, "conversations"]:
        (out / f"{c}.json").write_text(json_util.dumps(list(db[c].find(o))))
    print("Sauvegarde :", out)
    paths = [f["storage_path"] for f in db.files.find(plan["files"]) if f.get("storage_path")]
    if os.environ.get("S3_BUCKET") and paths:
        import boto3
        s3 = boto3.client("s3", endpoint_url=os.environ.get("S3_ENDPOINT") or None, aws_access_key_id=os.environ.get("S3_ACCESS_KEY_ID"),
                          aws_secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY"), region_name=os.environ.get("S3_REGION", "auto"))
        for i in range(0, len(paths), 500):
            s3.delete_objects(Bucket=os.environ["S3_BUCKET"], Delete={"Objects": [{"Key": k} for k in paths[i:i + 500]]})
        print("Fichiers supprimés du stockage :", len(paths))
    elif paths:
        (out / "storage_paths.txt").write_text("\n".join(paths))
        print(f"Stockage S3 non configuré : {len(paths)} fichier(s) restent dans le stockage (liste dans storage_paths.txt)")
    db.conversations.update_many({**o, "contact_id": {"$nin": [None, *a.keep_contact]}}, {"$set": {"contact_id": None}})
    db.conversations.update_many({**o, "event_id": {"$ne": None}}, {"$set": {"event_id": None}})
    for c, f in plan.items():
        print(f"{c:28}{db[c].delete_many(f).deleted_count:>8} supprimé(s)")


if __name__ == "__main__":
    main()
