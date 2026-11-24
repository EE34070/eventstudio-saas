"""Seed QA Messagerie (boîte Gmail simulée TEST_M42UI). `clean` retire uniquement cette boîte simulée et ses données."""
import asyncio, os, sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from pymongo import MongoClient
import gmail_fake
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
AID = "TEST_M42UI_box"; ACC = {"id": AID, "email": "test_m42ui@example.com"}
if sys.argv[1:] == ["clean"]:
    f = {"org_id": QA, "account_id": AID}
    print("cleaned", DB.messages.delete_many(f).deleted_count, DB.conversations.delete_many(f).deleted_count, DB.mail_labels.delete_many(f).deleted_count,
          DB.sync_queue.delete_many({"account_id": AID}).deleted_count, DB.fake_gmail.delete_many({"account_id": AID}).deleted_count, DB.channel_accounts.delete_many({"id": AID, "org_id": QA, "fake": True}).deleted_count)
    sys.exit()
assert not DB.channel_accounts.find_one({"org_id": QA}), "une boîte existe déjà en QA : lancer clean"
DB.channel_accounts.insert_one({**ACC, "org_id": QA, "channel": "gmail", "status": "connected", "fake": True, "created_at": "2026-11-23T00:00:00+00:00", "import": {"status": "done", "listed": True}})
async def main():
    add = gmail_fake.add
    for i in range(1, 23):
        await add(AID, f"Client {i} <client{i}.m42ui@example.fr>", f"TEST_M42UI Demande {i}", f"Bonjour, demande numéro {i}.", ["INBOX", "UNREAD", "CATEGORY_PERSONAL"], days_ago=i / 10)
    await add(AID, "Promo <newsletter@shop-m42ui.com>", "TEST_M42UI Soldes", "Promo", ["INBOX", "CATEGORY_PROMOTIONS"], days_ago=1, headers={"List-Unsubscribe": "<mailto:x@x.com>"}, html='<p>Soldes</p><img src="https://example.com/p.png">')
    await add(AID, "Ancien <ancien.m42ui@example.fr>", "TEST_M42UI Vieux message", "Il y a 200 jours", ["INBOX"], days_ago=200)
    await add(AID, "Arnaque <x@spam-m42ui.biz>", "TEST_M42UI Spam", "spam", ["SPAM"], days_ago=2)
    await gmail_fake.call(ACC, "POST", "/labels", json={"name": "Clients/Mariages"})
    await gmail_fake.call(ACC, "POST", "/labels", json={"name": "Fournisseurs"})
asyncio.run(main())
print("boîte simulée créée : dans l'app, Réglages messagerie > « Importer les 12 derniers mois »")
