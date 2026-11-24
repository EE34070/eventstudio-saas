"""Iter 13 — verify minor fixes:
1) PATCH /api/crm/tasks/{id} is restricted to CRM tasks (opportunity_id non-null/non-empty).
   - manual task (POST /api/tasks) -> PATCH /api/crm/tasks/{id} returns 404 and does not modify the task.
   - CRM task (POST /api/crm/opportunities/{oid}/tasks) -> PATCH done=true still works.
Tests run against qa-sandbox. Cleanup by id.
"""
import os
import subprocess
import uuid
from datetime import datetime, timedelta

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in open("/app/frontend/.env"):
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = BASE_URL + "/api"

_mongo = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

CREATED = {"tasks": [], "contacts": [], "opportunities": []}


def _tok(role: str) -> str:
    out = subprocess.run(["python3", "/app/scripts/qa_token.py", role],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        pytest.skip(f"qa_token.py {role} failed: {out.stderr[-300:]}")
    return out.stdout.strip().splitlines()[-1]


@pytest.fixture(scope="module")
def admin():
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {_tok('admin')}",
                      "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    org = _mongo.orgs.find_one({"slug": "qa-sandbox"})
    if not org:
        return
    org_id = org["id"]
    _mongo.tasks.delete_many({"org_id": org_id, "id": {"$in": CREATED["tasks"]}})
    _mongo.opportunities.delete_many({"org_id": org_id, "id": {"$in": CREATED["opportunities"]}})
    _mongo.contacts.delete_many({"org_id": org_id, "id": {"$in": CREATED["contacts"]}})


class TestCrmPatchTaskRestriction:
    def test_manual_task_patch_crm_returns_404(self, admin):
        # Create a manual task via /api/tasks (no opportunity_id)
        r = admin.post(f"{API}/tasks", json={"title": "TEST_P7_i13 manual task"})
        assert r.status_code == 200, r.text
        tid = r.json()["id"]
        CREATED["tasks"].append(tid)
        original_title = r.json()["title"]
        original_status = r.json().get("status", "todo")

        due = (datetime.utcnow() + timedelta(days=2)).strftime("%Y-%m-%d")
        # Attempt PATCH via CRM endpoint - should 404 since this task has no opportunity_id
        rp = admin.patch(f"{API}/crm/tasks/{tid}",
                         json={"title": "HACKED", "due_date": due, "done": True})
        assert rp.status_code == 404, f"Expected 404, got {rp.status_code}: {rp.text}"

        # Verify the manual task was NOT modified in DB
        doc = _mongo.tasks.find_one({"id": tid})
        assert doc is not None
        assert doc["title"] == original_title, "manual task title should be unchanged"
        assert doc.get("status", "todo") == original_status, "status should be unchanged"
        assert doc.get("done_at") in (None, ""), "done_at should remain unset"

    def test_crm_task_patch_still_works(self, admin):
        # Create contact + opportunity + CRM task
        contact = admin.post(f"{API}/contacts", json={
            "first_name": "TEST_P7_i13", "last_name": "CrmPatch",
            "email": f"test_p7_i13_{uuid.uuid4().hex[:6]}@example.com"})
        assert contact.status_code == 200, contact.text
        cid = contact.json()["id"]
        CREATED["contacts"].append(cid)

        future = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")
        opp = admin.post(f"{API}/crm/opportunities", json={
            "title": "TEST_P7_i13 opp", "client_contact_id": cid, "amount": 100,
            "event_date": future})
        assert opp.status_code == 200, opp.text
        oid = opp.json()["id"]
        CREATED["opportunities"].append(oid)

        due = (datetime.utcnow() + timedelta(days=3)).strftime("%Y-%m-%d")
        rt = admin.post(f"{API}/crm/opportunities/{oid}/tasks", json={
            "title": "TEST_P7_i13 crm task", "due_date": due, "done": False})
        assert rt.status_code == 200, rt.text
        tid = rt.json()["id"]
        CREATED["tasks"].append(tid)

        # PATCH done=true via CRM endpoint - should succeed
        rp = admin.patch(f"{API}/crm/tasks/{tid}", json={
            "title": "TEST_P7_i13 crm task", "due_date": due, "done": True})
        assert rp.status_code == 200, rp.text
        body = rp.json()
        assert body.get("status") == "done"
        assert body.get("done") is True
        assert body.get("done_at")

        # Verify persisted in DB
        doc = _mongo.tasks.find_one({"id": tid})
        assert doc["status"] == "done"
        assert doc.get("done_at")
