"""Iter 42 — Messagerie : boîte complète, libellés, vues, actions groupées. Gmail simulé dans la société QA uniquement."""
import asyncio
import os
import subprocess
import sys
import time
import uuid

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
from pymongo import MongoClient  # noqa: E402

import gmail_fake  # noqa: E402

API = next(l.split("=", 1)[1].strip() for l in open("/app/frontend/.env") if l.startswith("REACT_APP_BACKEND_URL")) + "/api"
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
QA = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
AID = f"TEST_M42_{uuid.uuid4().hex[:8]}"
ACC = {"id": AID, "email": f"{AID.lower()}@example.com"}
M = f"/{API}/messaging".replace("//", "/", 1).replace("http:/", "http://")
S = {}
run = lambda c: asyncio.get_event_loop().run_until_complete(c)  # noqa: E731


def sess(role="admin"):
    x = requests.Session()
    x.headers["Authorization"] = "Bearer " + subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip().splitlines()[-1]
    return x


def wait(fn, secs=60):
    end = time.time() + secs
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(1)
    raise AssertionError("délai dépassé")


def fake(gid):
    return DB.fake_gmail.find_one({"account_id": AID, "kind": "message", "id": gid})["labelIds"]


@pytest.fixture(scope="module")
def s():
    assert not DB.channel_accounts.find_one({"org_id": QA}), "une boîte existe déjà en QA"
    DB.channel_accounts.insert_one({**ACC, "org_id": QA, "channel": "gmail", "status": "connected", "fake": True, "created_at": "2026-11-23T00:00:00+00:00", "import": {"status": "done", "listed": True}})
    S["a"] = run(gmail_fake.add(AID, "Julie Martin <julie.m42@client.fr>", "Devis mariage juin", "Bonjour, pouvez-vous m'envoyer un devis ?", ["INBOX", "UNREAD", "CATEGORY_PERSONAL"], days_ago=1))
    S["b"] = run(gmail_fake.add(AID, "Promo <newsletter@shop-m42.com>", "Soldes -50 %", "Profitez-en", ["INBOX", "UNREAD", "CATEGORY_PROMOTIONS"], days_ago=2, headers={"List-Unsubscribe": "<mailto:x@shop.com>"},
                                html='<p>Soldes</p><img src="https://example.com/pixel.png">'))
    S["c"] = run(gmail_fake.add(AID, "Ancien <ancien.m42@client.fr>", "Question de l'an dernier", "Un vieux message", ["INBOX"], days_ago=200))
    S["spam0"] = run(gmail_fake.add(AID, "Arnaque <x@spam-m42.biz>", "Gagnez", "spam", ["SPAM"], days_ago=3))
    run(gmail_fake.call(ACC, "POST", "/labels", json={"name": "Clients/Mariages"}))
    yield sess()
    f = {"org_id": QA, "account_id": AID}
    DB.messages.delete_many(f)
    DB.conversations.delete_many(f)
    DB.mail_labels.delete_many(f)
    DB.sync_queue.delete_many({"account_id": AID})
    DB.fake_gmail.delete_many({"account_id": AID})
    DB.job_locks.delete_many({"_id": f"sync:{AID}"})
    DB.channel_accounts.delete_many({"id": AID, "org_id": QA, "fake": True})


def conv(s, key, **params):
    rows = s.get(f"{API}/messaging/conversations", params={"box": "all", "limit": 100, **params}).json()
    return next((r for r in rows if r["thread_id"] == S[key]["threadId"]), None)


def test_full_import_and_views(s):
    assert sess("commercial").post(f"{API}/messaging/import-full").status_code == 403
    assert s.post(f"{API}/messaging/import-full").json() == {"ok": True, "days": 365}
    st = wait(lambda: (lambda d: d if d["account"]["import"]["status"] == "done" else None)(s.get(f"{API}/messaging/status").json()))
    assert st["import_days"] == 365 and st["full_import"] and [x["name"] for x in st["labels"]] == ["Clients/Mariages"] and st["gmail_categories"]["promotions"] == "Promotions"
    inbox = {r["thread_id"] for r in s.get(f"{API}/messaging/conversations", params={"box": "inbox"}).json()}
    assert {S[k]["threadId"] for k in "abc"} <= inbox and S["spam0"]["threadId"] not in inbox
    promo = s.get(f"{API}/messaging/conversations", params={"box": "inbox", "gcat": "promotions"}).json()
    assert [r["thread_id"] for r in promo] == [S["b"]["threadId"]] and promo[0]["bulk"] is True and promo[0]["category"] is None and promo[0]["contact_id"] is None
    a = conv(s, "a", unlinked=True)
    assert a and a["gmail_category"] == "primary" and a["contact_id"] is None and a["unread"]
    assert DB.contacts.count_documents({"org_id": QA, "email": {"$in": ["julie.m42@client.fr", "newsletter@shop-m42.com"]}}) == 0
    assert conv(s, "a", q="from:julie.m42") and not conv(s, "b", q="from:julie.m42") and not conv(s, "a", q="has:attachment")
    assert conv(s, "a", box="unread") and not conv(s, "c", box="unread")
    S.update(A=a["id"], B=promo[0]["id"], C=conv(s, "c")["id"])


def test_labels_and_bulk_app_to_gmail(s):
    assert sess("technicien").get(f"{API}/messaging/labels").status_code == 403
    labs = s.post(f"{API}/messaging/labels", json={"name": "TEST_M42 / Devis"})
    assert labs.status_code == 200, labs.text
    lab = next(x for x in labs.json() if x["name"] == "TEST_M42/Devis")
    assert s.post(f"{API}/messaging/labels", json={"name": "TEST_M42/Devis"}).status_code == 409 and s.post(f"{API}/messaging/labels", json={"name": "INBOX"}).status_code == 400
    assert s.post(f"{API}/messaging/conversations/bulk", json={"ids": [S["A"]], "add_label_ids": ["Label_inconnu"]}).status_code == 400
    r = s.post(f"{API}/messaging/conversations/bulk", json={"ids": [S["A"], S["B"]], "add_label_ids": [lab["gmail_id"]], "archive": True})
    assert r.json() == {"updated": 2}
    for k in "ab":
        assert lab["gmail_id"] in fake(S[k]["id"]) and "INBOX" not in fake(S[k]["id"])
    assert conv(s, "a", box="archived") and conv(s, "b", label_id=lab["gmail_id"]) and conv(s, "a", q="label:TEST_M42") and not conv(s, "c", q="label:TEST_M42")
    s.post(f"{API}/messaging/conversations/bulk", json={"ids": [S["A"], S["B"]], "action": "read"})
    assert "UNREAD" not in fake(S["a"]["id"]) and not conv(s, "a")["unread"]
    d = s.patch(f"{API}/messaging/conversations/{S['A']}", json={"starred": True}).json()
    assert d["is_starred"] and "STARRED" in fake(S["a"]["id"]) and conv(s, "a", box="starred")
    s.patch(f"{API}/messaging/conversations/{S['B']}", json={"spam": True})
    assert "SPAM" in fake(S["b"]["id"]) and conv(s, "b", box="spam") and not conv(s, "b")
    s.patch(f"{API}/messaging/conversations/{S['B']}", json={"spam": False})
    assert conv(s, "b", box="inbox")
    assert s.delete(f"{API}/messaging/conversations/{S['A']}").status_code == 200 and "TRASH" in fake(S["a"]["id"])
    assert s.post(f"{API}/messaging/conversations/{S['A']}/restore").status_code == 200 and "TRASH" not in fake(S["a"]["id"]) and conv(s, "a")
    S["lab"] = lab


def test_gmail_to_app_and_label_lifecycle(s):
    gl = next(x for x in s.get(f"{API}/messaging/labels").json() if x["name"] == "Clients/Mariages")
    run(gmail_fake.call(ACC, "POST", f"/threads/{S['c']['threadId']}/modify", json={"addLabelIds": [gl["gmail_id"], "STARRED"], "removeLabelIds": ["INBOX"]}))
    S["spam1"] = run(gmail_fake.add(AID, "Arnaque <y@spam-m42.biz>", "Encore", "spam", ["SPAM"]))
    S["new"] = run(gmail_fake.add(AID, "Julie Martin <julie.m42@client.fr>", "Devis mariage juin", "Merci !", ["INBOX", "UNREAD", "CATEGORY_PERSONAL"], thread=S["a"]["threadId"]))
    run(gmail_fake.call(ACC, "POST", "/labels", json={"name": "Depuis Gmail"}))
    assert s.post(f"{API}/messaging/sync").status_code == 200
    c = wait(lambda: (lambda x: x if x and gl["gmail_id"] in x["label_ids"] else None)(conv(s, "c")))
    assert c["box"] == "archived" and c["is_starred"]
    wait(lambda: conv(s, "spam1", box="spam"))
    assert not conv(s, "spam1") and conv(s, "a")["message_count"] == 2 and conv(s, "a", box="inbox")
    assert "Depuis Gmail" in wait(lambda: (lambda n: n if "Depuis Gmail" in n else None)([x["name"] for x in s.get(f"{API}/messaging/status").json()["labels"]]))
    ren = s.put(f"{API}/messaging/labels/{S['lab']['id']}", json={"name": "TEST_M42/Devis envoyés"})
    assert ren.status_code == 200 and "TEST_M42/Devis envoyés" in [x["name"] for x in ren.json()]
    assert sess("commercial").delete(f"{API}/messaging/labels/{S['lab']['id']}").status_code == 403
    left = s.delete(f"{API}/messaging/labels/{S['lab']['id']}")
    assert left.status_code == 200 and S["lab"]["gmail_id"] not in [x["gmail_id"] for x in left.json()]
    assert S["lab"]["gmail_id"] not in conv(s, "a")["label_ids"] and S["lab"]["gmail_id"] not in fake(S["a"]["id"])
    full = s.get(f"{API}/messaging/conversations/{S['B']}").json()
    assert "<img" in full["messages"][0]["html"] and full["messages"][0]["bulk"] is True
