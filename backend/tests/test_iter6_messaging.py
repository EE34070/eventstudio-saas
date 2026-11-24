"""Iteration 6 — Unified Gmail messaging module.

Real Gmail OAuth cannot be performed without user consent, so this test suite
seeds a *disconnected* channel_accounts row directly in Mongo for the demo org
and exercises the storage, linking, API, RBAC, trash/purge, cron, webhook and
AI pieces end-to-end against the live backend.
"""
import asyncio
import base64
import fcntl
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv

load_dotenv(Path("/app/backend/.env"))
import sys
sys.path.insert(0, "/app/backend")
import messaging_core as mc  # noqa: E402
from core import db as motor_db  # noqa: E402  async
from pymongo import MongoClient  # noqa: E402

from conftest import API  # noqa: E402

MONGO = MongoClient(os.environ["MONGO_URL"])
DB = MONGO[os.environ["DB_NAME"]]
DEMO_SLUG = "exclusivity-events"

# Use a single persistent event loop for the whole test file so motor's client
# (bound lazily to the first loop it sees) remains valid across tests.
_LOOP = asyncio.new_event_loop()


def arun(coro):
    return _LOOP.run_until_complete(coro)



# ---------- Module-level fixtures (session scope) ----------
@pytest.fixture(scope="module")
def demo_org():
    o = DB.orgs.find_one({"slug": DEMO_SLUG}, {"_id": 0})
    if not o:
        pytest.skip("Demo org absent")
    return o


@pytest.fixture(scope="module")
def seeded(demo_org):
    """Seed a disconnected gmail account + 2 conversations for the demo org.

    Worker-safe across pytest-xdist loadscope: an inter-process file lock ensures
    one worker inserts; the others reuse the TEST_ACC_-prefixed row and share
    conversations via Mongo. Only the worker that actually inserted performs
    teardown (sentinel file). Honors the hard rule: if a non-TEST channel_accounts
    row already exists for the demo org -> skip entire module.
    """
    sentinel = Path("/tmp/iter6_seed.json")
    lock_path = Path("/tmp/iter6_seed.lock")
    lock_fp = open(lock_path, "w")
    fcntl.flock(lock_fp, fcntl.LOCK_EX)
    i_own_teardown = False
    try:
        existing = DB.channel_accounts.find_one({"org_id": demo_org["id"], "channel": "gmail"})
        if existing and not str(existing.get("id", "")).startswith("TEST_ACC_"):
            pytest.skip("channel_accounts row for demo org is user-owned - leaving untouched")
        if existing and sentinel.exists():
            data = json.loads(sentinel.read_text())
        else:
            i_own_teardown = True
            acc_id = f"TEST_ACC_{uuid.uuid4().hex[:8]}"
            account_email = f"TEST_{uuid.uuid4().hex[:6]}@example.com"
            now = int(time.time() * 1000)
            acc_doc = {
                "id": acc_id, "org_id": demo_org["id"], "channel": "gmail",
                "email": account_email, "status": "disconnected",
                "last_error": None, "last_sync_at": None, "connected_by": "TEST",
                "connected_at": mc.now_iso(), "watch_expiration": 0, "watch_error": None,
                "import": {"status": "done", "done": 0, "total": 0},
                "history_id": "1", "created_at": mc.now_iso(),
            }
            DB.channel_accounts.insert_one(acc_doc)

            def b64(s):
                return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")

            sender_email = f"test_prospect_{uuid.uuid4().hex[:6]}@example.com"
            contact_id = f"TEST_CT_{uuid.uuid4().hex[:8]}"
            DB.contacts.insert_one({
                "id": contact_id, "org_id": demo_org["id"], "kind": "particulier", "status": "prospect",
                "first_name": "TEST", "last_name": "Prospect", "email": sender_email, "phone": "",
                "address": "", "city": "", "company": "", "source": "TEST", "tags": [], "notes": "",
                "types": ["client"], "interactions": [], "created_at": mc.now_iso(),
            })
            event_id = f"TEST_EV_{uuid.uuid4().hex[:8]}"
            start_day = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
            DB.events.insert_one({
                "id": event_id, "org_id": demo_org["id"], "code": f"TEST-{uuid.uuid4().hex[:4]}",
                "title": "TEST evenement", "type": "Autre", "status": "confirme",
                "client_id": contact_id, "start": f"{start_day}T18:00", "end": f"{start_day}T22:00",
                "guests": 10, "notes": "", "team": [], "created_at": mc.now_iso(),
            })
            thread_a = f"THREAD_{uuid.uuid4().hex[:10]}"
            gmail_id_a1 = f"MID_{uuid.uuid4().hex[:10]}"
            gmail_id_a2 = f"MID_{uuid.uuid4().hex[:10]}"
            msg_a1 = {"id": gmail_id_a1, "threadId": thread_a,
                "labelIds": ["INBOX", "UNREAD"], "internalDate": str(now - 3600 * 1000),
                "snippet": "Bonjour, je souhaiterais organiser un mariage le ...",
                "payload": {"mimeType": "multipart/mixed",
                    "headers": [
                        {"name": "From", "value": f"TEST Prospect <{sender_email}>"},
                        {"name": "To", "value": account_email},
                        {"name": "Subject", "value": "TEST - Demande de devis mariage"},
                        {"name": "Message-ID", "value": f"<{uuid.uuid4().hex}@example.com>"}],
                    "parts": [
                        {"partId": "0", "mimeType": "multipart/alternative", "parts": [
                            {"partId": "0.0", "mimeType": "text/plain",
                             "body": {"data": b64("Bonjour,\nNous souhaitons organiser un mariage. Pouvez-vous nous faire un devis ?\nCordialement.")}},
                            {"partId": "0.1", "mimeType": "text/html",
                             "body": {"data": b64("<html><body><p>Bonjour,</p><p>Nous souhaitons organiser un mariage.</p></body></html>")}}]},
                        {"partId": "1", "mimeType": "application/pdf", "filename": "cahier.pdf",
                         "body": {"size": 2048, "attachmentId": "ATT_FAKE"}}]}}
            msg_a2 = {"id": gmail_id_a2, "threadId": thread_a,
                "labelIds": ["SENT"], "internalDate": str(now - 1800 * 1000),
                "snippet": "Merci pour votre message ...",
                "payload": {"mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": account_email},
                        {"name": "To", "value": sender_email},
                        {"name": "Subject", "value": "Re: TEST - Demande de devis mariage"},
                        {"name": "Message-ID", "value": f"<{uuid.uuid4().hex}@example.com>"}],
                    "body": {"data": b64("Merci pour votre message, nous vous recontactons sous 48h.")}}}
            thread_b = f"THREAD_{uuid.uuid4().hex[:10]}"
            gmail_id_b1 = f"MID_{uuid.uuid4().hex[:10]}"
            msg_b1 = {"id": gmail_id_b1, "threadId": thread_b,
                "labelIds": ["INBOX"], "internalDate": str(now - 7200 * 1000),
                "snippet": "Newsletter de test ...",
                "payload": {"mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": f"News <news_{uuid.uuid4().hex[:6]}@example.com>"},
                        {"name": "To", "value": account_email},
                        {"name": "Subject", "value": "TEST - Newsletter"},
                        {"name": "Message-ID", "value": f"<{uuid.uuid4().hex}@example.com>"}],
                    "body": {"data": b64("Ceci est une newsletter de test.")}}}

            async def _seed_async():
                for m in (msg_a1, msg_a2, msg_b1):
                    r = await mc.store_message(acc_doc, m)
                    assert r is not None
                cids = {DB.conversations.find_one({"org_id": demo_org["id"], "thread_id": t}, {"id": 1})["id"]
                        for t in (thread_a, thread_b)}
                for cid in cids:
                    await mc.refresh_conv(cid)
                    await mc.link_conv(cid)
            arun(_seed_async())
            conv_a = DB.conversations.find_one({"org_id": demo_org["id"], "thread_id": thread_a}, {"_id": 0})
            conv_b = DB.conversations.find_one({"org_id": demo_org["id"], "thread_id": thread_b}, {"_id": 0})
            data = {
                "acc_id": acc_id, "account_email": account_email,
                "contact_id": contact_id, "event_id": event_id, "sender_email": sender_email,
                "conv_a_id": conv_a["id"], "conv_b_id": conv_b["id"],
                "gmail_ids": [gmail_id_a1, gmail_id_a2, gmail_id_b1],
            }
            sentinel.write_text(json.dumps(data))
    finally:
        fcntl.flock(lock_fp, fcntl.LOCK_UN)
        lock_fp.close()

    data["conv_a"] = DB.conversations.find_one({"id": data["conv_a_id"]}, {"_id": 0})
    data["conv_b"] = DB.conversations.find_one({"id": data["conv_b_id"]}, {"_id": 0})
    yield data

    if not i_own_teardown:
        return
    DB.messages.delete_many({"org_id": demo_org["id"], "gmail_id": {"$in": data["gmail_ids"]}})
    cids = [data["conv_a_id"], data["conv_b_id"]]
    DB.internal_notes.delete_many({"org_id": demo_org["id"], "conversation_id": {"$in": cids}})
    DB.conversations.delete_many({"org_id": demo_org["id"], "id": {"$in": cids}})
    DB.events.delete_many({"org_id": demo_org["id"], "id": data["event_id"]})
    DB.contacts.delete_many({"org_id": demo_org["id"], "id": data["contact_id"]})
    DB.channel_accounts.delete_one({"org_id": demo_org["id"], "id": data["acc_id"]})
    try:
        sentinel.unlink()
    except FileNotFoundError:
        pass


def test_store_parses_and_persists_storage(demo_org, seeded):
    conv = seeded["conv_a"]
    assert conv is not None
    assert "Demande de devis mariage" in conv["subject"]
    assert conv["last_direction"] == "out"  # msg_a2 is SENT and newer
    # Contact + event auto-linked
    assert conv["contact_id"] == seeded["contact_id"]
    assert conv["event_id"] == seeded["event_id"]
    # Box computed from labels (INBOX on A1 -> inbox)
    assert conv["box"] == "inbox"
    assert conv["message_count"] == 2
    assert conv["has_attachments"] is True

def test_parse_message_attachment_storage(demo_org, seeded):
    mid = seeded["gmail_ids"][0]
    m = DB.messages.find_one({"org_id": demo_org["id"], "gmail_id": mid}, {"_id": 0})
    assert m and m["direction"] == "in"
    assert m["from"]["email"] == seeded["sender_email"]
    assert any(a["filename"] == "cahier.pdf" for a in m["attachments"])
    assert "Bonjour" in m["text"]

def test_conv_b_not_linked_storage(demo_org, seeded):
    conv = seeded["conv_b"]
    assert conv["contact_id"] is None
    assert conv["event_id"] is None


# ---------- /messaging/status ----------
def test_status_shape_status(admin, seeded):
    r = admin.get(f"{API}/messaging/status")
    assert r.status_code == 200
    d = r.json()
    for k in ("configured", "account", "settings", "categories", "unread", "trash", "purgeable", "redirect_uri"):
        assert k in d, f"missing key {k}"
    assert d["account"]["status"] == "disconnected"
    assert d["account"]["email"] == seeded["account_email"]
    assert "demande" in d["categories"]


# ---------- Listing / detail ----------
def test_inbox_lists_conv_a_list(admin, seeded):
    r = admin.get(f"{API}/messaging/conversations", params={"box": "inbox"})
    assert r.status_code == 200
    ids = {c["id"] for c in r.json()}
    assert seeded["conv_a"]["id"] in ids

def test_search_filters_list(admin, seeded):
    r = admin.get(f"{API}/messaging/conversations", params={"box": "inbox", "q": "mariage"})
    assert r.status_code == 200
    ids = {c["id"] for c in r.json()}
    assert seeded["conv_a"]["id"] in ids

def test_detail_returns_messages_contact_event_list(admin, seeded):
    cid = seeded["conv_a"]["id"]
    r = admin.get(f"{API}/messaging/conversations/{cid}")
    assert r.status_code == 200
    d = r.json()
    assert len(d["messages"]) == 2
    assert d["contact"]["id"] == seeded["contact_id"]
    assert d["event"]["id"] == seeded["event_id"]
    assert d["can_reply"] is False  # account disconnected
    assert isinstance(d["contact_events"], list)
    assert isinstance(d["notes"], list)


# ---------- PATCH ----------
def test_category_marks_manual_patch(admin, seeded):
    cid = seeded["conv_a"]["id"]
    r = admin.patch(f"{API}/messaging/conversations/{cid}", json={"category": "client"})
    assert r.status_code == 200
    doc = DB.conversations.find_one({"id": cid})
    assert doc["category"] == "client"
    assert doc.get("category_manual") is True

def test_invalid_category_patch(admin, seeded):
    cid = seeded["conv_a"]["id"]
    r = admin.patch(f"{API}/messaging/conversations/{cid}", json={"category": "pas-une-cat"})
    assert r.status_code == 400

def test_archive_local_when_disconnected_patch(admin, seeded):
    cid = seeded["conv_a"]["id"]
    r = admin.patch(f"{API}/messaging/conversations/{cid}", json={"archived": True})
    assert r.status_code == 200
    # Local message labels no longer contain INBOX
    msgs = list(DB.messages.find({"org_id": seeded["conv_a"]["org_id"], "conversation_id": cid}))
    assert all("INBOX" not in (m.get("label_ids") or []) for m in msgs)
    # Un-archive -> INBOX back
    r = admin.patch(f"{API}/messaging/conversations/{cid}", json={"archived": False})
    assert r.status_code == 200

def test_unread_local_patch(admin, seeded):
    cid = seeded["conv_a"]["id"]
    r = admin.patch(f"{API}/messaging/conversations/{cid}", json={"unread": True})
    assert r.status_code == 200
    conv = DB.conversations.find_one({"id": cid})
    assert conv["unread"] is True


# ---------- Trash / restore / purge ----------
def test_trash_and_restore_trash(admin, seeded):
    cid = seeded["conv_b"]["id"]
    r = admin.delete(f"{API}/messaging/conversations/{cid}")
    assert r.status_code == 200
    # Appears in trash with purge_at
    r = admin.get(f"{API}/messaging/conversations", params={"box": "trash"})
    trash = r.json()
    row = next((c for c in trash if c["id"] == cid), None)
    assert row and "purge_at" in row
    # Restore
    r = admin.post(f"{API}/messaging/conversations/{cid}/restore")
    assert r.status_code == 200
    assert DB.conversations.find_one({"id": cid})["deleted_at"] is None

def test_purge_only_expired_trash(admin, seeded, demo_org):
    # Antidate conv_b to >30 days ago
    cid = seeded["conv_b"]["id"]
    old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    DB.conversations.update_one({"id": cid}, {"$set": {"deleted_at": old, "deleted_reason": "user"}})
    before_a = DB.conversations.find_one({"id": seeded["conv_a"]["id"]})
    r = admin.post(f"{API}/messaging/trash/purge")
    assert r.status_code == 200
    assert r.json()["deleted"] >= 1
    assert DB.conversations.find_one({"id": cid}) is None  # purged
    # conv_a (not in trash) untouched
    assert DB.conversations.find_one({"id": seeded["conv_a"]["id"]}) is not None
    # Mark conv_b as None so teardown doesn't try to delete it twice
    seeded["conv_b"] = {"id": cid, "org_id": before_a["org_id"]} if before_a else {"id": cid, "org_id": demo_org["id"]}


# ---------- Notes ----------
def test_add_and_delete_note_notes(admin, seeded):
    cid = seeded["conv_a"]["id"]
    r = admin.post(f"{API}/messaging/conversations/{cid}/notes", json={"text": "TEST note interne"})
    assert r.status_code == 200
    note = r.json()
    assert note["text"] == "TEST note interne"
    r = admin.delete(f"{API}/messaging/notes/{note['id']}")
    assert r.status_code == 200


# ---------- Contact creation from conversation ----------
def test_create_contact_from_conv_contactcreate(admin, seeded, demo_org):
    # Build an orphan conv (no contact) with a known sender e-mail
    now = int(time.time() * 1000)
    orphan_email = f"test_orphan_{uuid.uuid4().hex[:6]}@example.com"

    def b64(s: str) -> str:
        return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")
    gmid = f"MID_{uuid.uuid4().hex[:10]}"
    thread = f"THREAD_{uuid.uuid4().hex[:10]}"
    m = {"id": gmid, "threadId": thread, "labelIds": ["INBOX"], "internalDate": str(now),
         "snippet": "orphan", "payload": {"mimeType": "text/plain",
         "headers": [{"name": "From", "value": f"Orphan Inconnu <{orphan_email}>"},
                     {"name": "To", "value": seeded["account_email"]},
                     {"name": "Subject", "value": "TEST — orphelin"},
                     {"name": "Message-ID", "value": f"<{uuid.uuid4().hex}@example.com>"}],
         "body": {"data": b64("Je cherche un prestataire.")}}}
    acc = DB.channel_accounts.find_one({"id": seeded["acc_id"]}, {"_id": 0})

    async def _run():
        r = await mc.store_message(acc, m)
        await mc.refresh_conv(r[0])
        await mc.link_conv(r[0])
        return r[0]
    cid = arun(_run())
    try:
        r = admin.post(f"{API}/messaging/conversations/{cid}/contact")
        assert r.status_code == 200
        d = r.json()
        assert d["contact"] is not None
        assert d["contact"]["email"] == orphan_email
        new_contact_id = d["contact"]["id"]
        # 2nd call -> 409
        r2 = admin.post(f"{API}/messaging/conversations/{cid}/contact")
        assert r2.status_code == 409
        # cleanup
        DB.contacts.delete_one({"id": new_contact_id})
    finally:
        DB.messages.delete_many({"gmail_id": gmid})
        DB.conversations.delete_one({"id": cid})


# ---------- RBAC ----------
def test_tech_forbidden_rbac(tech, seeded):
    for path in ("/messaging/status", "/messaging/conversations"):
        r = tech.get(f"{API}{path}")
        assert r.status_code == 403, f"{path} should be 403 for technicien, got {r.status_code}"

def test_compta_readonly_rbac(compta, seeded):
    r = compta.get(f"{API}/messaging/status")
    assert r.status_code == 200
    cid = seeded["conv_a"]["id"]
    r = compta.get(f"{API}/messaging/conversations/{cid}")
    assert r.status_code == 200
    r = compta.patch(f"{API}/messaging/conversations/{cid}", json={"category": "autre"})
    assert r.status_code == 403
    r = compta.delete(f"{API}/messaging/conversations/{cid}")
    assert r.status_code == 403

def test_connect_forbidden_commercial_rbac(commercial):
    r = commercial.get(f"{API}/messaging/gmail/connect", params={"return_to": "https://example.com"})
    assert r.status_code == 403


# ---------- gmail/connect validation ----------
def test_foreign_return_to_rejected_connectvalidation(admin):
    if not mc.google_ready():
        r = admin.get(f"{API}/messaging/gmail/connect", params={"return_to": "https://evil.example.com"})
        assert r.status_code in (400, 503)
        return
    r = admin.get(f"{API}/messaging/gmail/connect", params={"return_to": "https://evil.example.com"})
    assert r.status_code == 400

def test_callback_unknown_state_connectvalidation(admin):
    # Public endpoint — use a raw session to avoid auth header interference
    r = requests.get(f"{API}/auth/google/callback", params={"state": "NOPE_" + uuid.uuid4().hex, "code": "x"},
                     allow_redirects=False)
    assert r.status_code == 400


# ---------- Webhook / cron auth ----------
def test_gmail_webhook_no_token_webhookandcron():
    r = requests.post(f"{API}/webhooks/gmail", json={"message": {"data": "", "messageId": "x"}})
    assert r.status_code in (401, 503)

def test_gmail_webhook_bad_token_webhookandcron():
    r = requests.post(f"{API}/webhooks/gmail", json={"message": {"data": "", "messageId": "x"}},
                      headers={"Authorization": "Bearer fake.token.value"})
    assert r.status_code in (401, 503)

def test_cron_sync_no_secret_webhookandcron():
    r = requests.post(f"{API}/cron/messaging-sync", json={"run_id": "x"})
    assert r.status_code == 401

def test_cron_sync_bad_secret_webhookandcron():
    r = requests.post(f"{API}/cron/messaging-sync", json={"run_id": "x"},
                      headers={"Authorization": "Bearer WRONG"})
    assert r.status_code == 401

def test_cron_sync_ok_and_dedup_webhookandcron():
    secret = os.environ.get("WEBHOOK_CRON_SECRET")
    if not secret:
        pytest.skip("WEBHOOK_CRON_SECRET not set")
    rid = f"TEST_{uuid.uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {secret}", "X-Webhook-Id": rid, "Content-Type": "application/json"}
    r1 = requests.post(f"{API}/cron/messaging-sync", json={}, headers=headers)
    assert r1.status_code == 200
    assert r1.json()["ok"] is True
    r2 = requests.post(f"{API}/cron/messaging-sync", json={}, headers=headers)
    assert r2.status_code == 200
    assert r2.json().get("duplicate") is True
    # cleanup our cron_runs row
    DB.cron_runs.delete_one({"_id": f"messaging-sync:{rid}"})

def test_cron_daily_ok_webhookandcron():
    secret = os.environ.get("WEBHOOK_CRON_SECRET")
    if not secret:
        pytest.skip("WEBHOOK_CRON_SECRET not set")
    rid = f"TEST_{uuid.uuid4().hex[:8]}"
    headers = {"Authorization": f"Bearer {secret}", "X-Webhook-Id": rid, "Content-Type": "application/json"}
    r = requests.post(f"{API}/cron/messaging-daily", json={}, headers=headers)
    assert r.status_code == 200
    DB.cron_runs.delete_one({"_id": f"messaging-daily:{rid}"})


# ---------- Reply / send when disconnected ----------
def test_reply_409_replydisconnected(admin, seeded):
    cid = seeded["conv_a"]["id"]
    r = admin.post(f"{API}/messaging/conversations/{cid}/reply", json={"text": "TEST"})
    assert r.status_code == 409

def test_send_409_replydisconnected(admin, seeded):
    r = admin.post(f"{API}/messaging/send",
                   json={"to": "someone@example.com", "subject": "TEST", "text": "TEST"})
    assert r.status_code == 409


# ---------- Delete contact -> conv to trash ----------
def test_delete_contact_puts_conv_in_trash_contactdeletecascade(admin, seeded, demo_org):
    # Create a dedicated TEST_ contact + convo to delete
    ct_id = f"TEST_CT_{uuid.uuid4().hex[:8]}"
    ct_email = f"test_cascade_{uuid.uuid4().hex[:6]}@example.com"
    DB.contacts.insert_one({
        "id": ct_id, "org_id": demo_org["id"], "kind": "particulier", "status": "prospect",
        "first_name": "TEST", "last_name": "Cascade", "email": ct_email, "phone": "", "address": "",
        "city": "", "company": "", "source": "TEST", "tags": [], "notes": "",
        "types": ["client"], "interactions": [], "created_at": mc.now_iso(),
    })
    now = int(time.time() * 1000)

    def b64(s):
        return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")
    gmid = f"MID_{uuid.uuid4().hex[:10]}"
    thread = f"THREAD_{uuid.uuid4().hex[:10]}"
    m = {"id": gmid, "threadId": thread, "labelIds": ["INBOX"], "internalDate": str(now),
         "snippet": "cascade", "payload": {"mimeType": "text/plain",
         "headers": [{"name": "From", "value": ct_email}, {"name": "To", "value": seeded["account_email"]},
                     {"name": "Subject", "value": "TEST — cascade"},
                     {"name": "Message-ID", "value": f"<{uuid.uuid4().hex}@example.com>"}],
         "body": {"data": b64("cascade.")}}}
    acc = DB.channel_accounts.find_one({"id": seeded["acc_id"]}, {"_id": 0})

    async def _run():
        r = await mc.store_message(acc, m)
        await mc.refresh_conv(r[0])
        await mc.link_conv(r[0])
        return r[0]
    cid = arun(_run())
    try:
        # Sanity: conv is linked to ct_id
        assert DB.conversations.find_one({"id": cid})["contact_id"] == ct_id
        r = admin.delete(f"{API}/contacts/{ct_id}")
        assert r.status_code in (200, 204)
        conv = DB.conversations.find_one({"id": cid})
        assert conv["deleted_at"] is not None
        assert conv["deleted_reason"] == "contact"
    finally:
        DB.messages.delete_many({"gmail_id": gmid})
        DB.conversations.delete_one({"id": cid})
        DB.contacts.delete_one({"id": ct_id})


# ---------- Real AI (ANTHROPIC_API_KEY) ----------
def test_classify_ai(admin, seeded):
    if not mc.ai_ready():
        pytest.skip("ANTHROPIC_API_KEY not set")
    cid = seeded["conv_a"]["id"]
    # category_manual is True from TestPatch — drop it so classify can set a category
    DB.conversations.update_one({"id": cid}, {"$set": {"category_manual": False, "category": None}})
    r = admin.post(f"{API}/messaging/conversations/{cid}/classify")
    if r.status_code == 502:
        pytest.skip(f"AI upstream unavailable: {r.text[:120]}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["category"] in mc.CATEGORIES
    assert d["ai_summary"]
    assert isinstance(d["needs_reply"], bool)

def test_suggest_ai(admin, seeded):
    if not mc.ai_ready():
        pytest.skip("ANTHROPIC_API_KEY not set")
    cid = seeded["conv_a"]["id"]
    r = admin.post(f"{API}/messaging/conversations/{cid}/suggest")
    if r.status_code == 502:
        pytest.skip(f"AI upstream unavailable: {r.text[:120]}")
    assert r.status_code == 200, r.text
    assert r.json()["text"].strip()

def test_event_draft_and_create_ai(admin, seeded, demo_org):
    if not mc.ai_ready():
        pytest.skip("ANTHROPIC_API_KEY not set")
    cid = seeded["conv_a"]["id"]
    r = admin.post(f"{API}/messaging/conversations/{cid}/event-draft")
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("title", "type", "start", "end"):
        assert k in d
    # Build payload — fallback dates if AI left them empty
    start = d["start"] or (datetime.now(timezone.utc) + timedelta(days=60)).date().isoformat() + "T18:00"
    end = d["end"] or (datetime.now(timezone.utc) + timedelta(days=60, hours=4)).date().isoformat() + "T22:00"
    r = admin.post(f"{API}/messaging/conversations/{cid}/event",
                   json={"title": "TEST " + (d["title"][:40] or "event"),
                         "type": d["type"] or "Autre",
                         "start": start, "end": end, "guests": d.get("guests") or 0})
    assert r.status_code == 200, r.text
    ev_ref = r.json()
    ev = DB.events.find_one({"id": ev_ref["id"]}, {"_id": 0})
    assert ev["client_id"] == seeded["contact_id"]
    assert ev["status"] == "demande"
    assert "Demande reçue par e-mail" in (ev.get("notes") or "")
    # cleanup
    DB.events.delete_one({"id": ev["id"]})
    # Restore conv's original event_id link (was overwritten by this endpoint)
    DB.conversations.update_one({"id": cid}, {"$set": {"event_id": seeded["event_id"]}})
