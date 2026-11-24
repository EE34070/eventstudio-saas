"""Reprise des devis clients importés. Usage : python3 scripts/fix_imported_quotes.py <slug-société> [--apply]  (sans --apply : simulation, aucune écriture)."""
import asyncio
import json
import sys

sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv  # noqa: E402

load_dotenv("/app/backend/.env")
from core import db  # noqa: E402
import routes_quote_sync  # noqa: E402


async def main() -> None:
    org = await db.orgs.find_one({"slug": sys.argv[1]}, {"_id": 0, "id": 1})
    rep = await routes_quote_sync.repair(org["id"], "--apply" in sys.argv)
    print(json.dumps({"societe": sys.argv[1], "mode": "APPLIQUÉ" if "--apply" in sys.argv else "SIMULATION", **rep}, ensure_ascii=False, indent=1))

asyncio.run(main())
