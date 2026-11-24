import os

from dotenv import dotenv_values

if (os.environ.get("ENV") or dotenv_values("/app/backend/.env").get("ENV") or "").strip().lower() != "development":
    raise SystemExit("Tests refusés : ENV doit valoir development (jamais sur la base de production).")
import subprocess

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in open("/app/frontend/.env"):
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = BASE_URL + "/api"

_cache = {}


def token_for(email, role, mode="demo"):
    if mode == "demo" and os.environ.get("ALLOW_REAL_ORG_TESTS") != "1":
        pytest.skip("Suite ciblant la société réelle : désactivée (tests en société QA uniquement)")
    key = (email, role, mode)
    if key not in _cache:
        out = subprocess.run(["python3", "/app/scripts/clerk_token.py", email, role, mode],
                             capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            pytest.skip(f"token failure: {out.stderr[-300:]}")
        _cache[key] = out.stdout.strip().splitlines()[-1]
    return _cache[key]


def client(email, role, mode="demo"):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token_for(email, role, mode)}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def admin():
    return client("test_admin+clerk_test@example.com", "admin")


@pytest.fixture(scope="session")
def tech():
    return client("test_tech+clerk_test@example.com", "technicien")


@pytest.fixture(scope="session")
def compta():
    return client("test_compta+clerk_test@example.com", "comptable")


@pytest.fixture(scope="session")
def commercial():
    return client("test_commercial+clerk_test@example.com", "commercial")


@pytest.fixture(scope="session")
def events_by_code(admin):
    r = admin.get(f"{API}/events")
    assert r.status_code == 200
    return {e["code"]: e for e in r.json()}


# Suites whose classes share state in order: keep the whole file on one xdist worker.
SEQUENTIAL_FILES = ("test_iter25_access_profiles_extra.py", "test_iter22_access_profiles.py", "test_iter21_member_invite.py", "test_iter20_quote_duplicate.py", "test_iter19_event_quotes.py", "test_iter18_quote_docs.py", "test_iter11_staff.py", "test_iter14_stock.py", "test_iter15_logistics.py", "test_iter16_missions_tracking.py")


def pytest_xdist_make_scheduler(config, log):
    from xdist.scheduler.loadscope import LoadScopeScheduling

    class Sched(LoadScopeScheduling):
        def _split_scope(self, nodeid):
            path = nodeid.split("::", 1)[0]
            return path if path.endswith(SEQUENTIAL_FILES) else super()._split_scope(nodeid)

    return Sched(config, log)


# CI / poste sans clés Clerk de test : les suites qui exigent Clerk, la société QA, Gmail, Spotify ou d'autres secrets sont ignorées (skip), pas en échec.
from pathlib import Path

from dotenv import dotenv_values

_REPO = Path(__file__).resolve().parents[2]
HAS_CLERK = bool(os.environ.get("CLERK_SECRET_KEY") or dotenv_values(_REPO / "backend" / ".env").get("CLERK_SECRET_KEY"))
_EXTERNAL = ("qa_token", "clerk_token", "clerk_ticket", "/app/backend/.env", "test_iter54_dj_tab_roadmap", "import API, client")


class _SkippedModule(pytest.Module):
    def collect(self):
        pytest.skip("Exige Clerk de test, la société QA ou des secrets absents de cet environnement")


def pytest_pycollect_makemodule(module_path, parent):
    if not HAS_CLERK and module_path.name.startswith("test_") and any(k in module_path.read_text() for k in _EXTERNAL):
        return _SkippedModule.from_parent(parent, path=module_path)
