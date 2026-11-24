"""Iter 42 UI — live checks against seeded QA box (do not touch pytest test_iter42_gmail_full.py).
Verifies security 403s and current state of the simulated box TEST_M42UI without mutating data irreversibly.
"""
import os
import subprocess
import requests
import pytest

API = next(l.split("=", 1)[1].strip() for l in open("/app/frontend/.env") if l.startswith("REACT_APP_BACKEND_URL")) + "/api"


def tok(role):
    return subprocess.check_output(["python3", "/app/scripts/qa_token.py", role], text=True).strip().splitlines()[-1]


def sess(role):
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + tok(role)
    return s


@pytest.fixture(scope="module")
def admin():
    return sess("admin")


# -------------------- Security matrix --------------------

def test_technicien_forbidden_on_labels_and_conversations():
    t = sess("technicien")
    assert t.get(f"{API}/messaging/labels").status_code == 403
    assert t.get(f"{API}/messaging/conversations?box=inbox").status_code == 403


def test_commercial_forbidden_on_import_full_and_label_delete(admin):
    c = sess("commercial")
    assert c.post(f"{API}/messaging/import-full").status_code == 403
    labs = admin.get(f"{API}/messaging/labels").json()
    lab_id = labs[0]["id"]
    assert c.delete(f"{API}/messaging/labels/{lab_id}").status_code == 403


def test_no_token_returns_401():
    r = requests.get(f"{API}/messaging/status")
    assert r.status_code in (401, 403)


# -------------------- State checks (read-only) --------------------

def test_status_shows_seeded_box_and_full_import(admin):
    st = admin.get(f"{API}/messaging/status").json()
    assert st["account"]["email"] == "test_m42ui@example.com"
    assert st["account"]["import"]["status"] == "done"
    assert st["full_import"] is True
    assert st["import_days"] == 365
    names = sorted(x["name"] for x in st["labels"])
    assert "Clients/Mariages" in names and "Fournisseurs" in names
    assert st["unread"] == 22
    assert st["gmail_categories"]["promotions"] == "Promotions"


def test_views_inbox_unread_all_spam(admin):
    inbox = admin.get(f"{API}/messaging/conversations?box=inbox&limit=200").json()
    assert len(inbox) >= 23  # 22 demandes + 1 soldes (promo) at least
    subs_inbox = {r["subject"] for r in inbox}
    assert any("TEST_M42UI Demande" in s for s in subs_inbox)
    assert "TEST_M42UI Soldes" in subs_inbox
    assert "TEST_M42UI Spam" not in subs_inbox

    unread = admin.get(f"{API}/messaging/conversations?box=unread&limit=200").json()
    assert sum(1 for r in unread if "TEST_M42UI Demande" in r["subject"]) == 22

    allv = admin.get(f"{API}/messaging/conversations?box=all&limit=500").json()
    subs_all = {r["subject"] for r in allv}
    assert "TEST_M42UI Vieux message" in subs_all
    assert "TEST_M42UI Spam" not in subs_all  # spam exclu de "Tous"

    spam = admin.get(f"{API}/messaging/conversations?box=spam&limit=200").json()
    assert any(r["subject"] == "TEST_M42UI Spam" for r in spam)


def test_promotions_tab_shows_only_soldes(admin):
    promo = admin.get(f"{API}/messaging/conversations?box=inbox&gcat=promotions&limit=200").json()
    assert [r["subject"] for r in promo] == ["TEST_M42UI Soldes"]
    assert promo[0]["contact_id"] is None
    assert promo[0]["bulk"] is True


def test_search_from_client3(admin):
    res = admin.get(f"{API}/messaging/conversations?box=all&q=from:client3.m42ui&limit=50").json()
    assert len(res) == 1
    assert "Demande 3" in res[0]["subject"]


def test_unlinked_filter_and_no_auto_contact(admin):
    # expéditeurs inconnus : aucun contact créé
    from pymongo import MongoClient
    DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    assert DB.contacts.count_documents({"email": {"$regex": "m42ui", "$options": "i"}}) == 0
    inbox_unlinked = admin.get(f"{API}/messaging/conversations?box=inbox&unlinked=true&limit=200").json()
    # toutes les demandes doivent être non-rattachées (contact_id is None)
    for r in inbox_unlinked:
        assert r["contact_id"] is None
