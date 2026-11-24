"""Tests du SaaS « une base par société », sans serveur, sans Clerk ni MongoDB réels.

Lancement : cd backend && python -m pytest tests_saas -q
"""
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update({"ENV": "development", "MONGO_URL": "mongodb://unused", "DB_NAME": "platform", "CONTROL_DB": "platform",
                   "CLERK_PUBLISHABLE_KEY": "pk_test_saas", "FILE_SIGNING_SECRET": "s" * 48, "LINK_SECRET": "l" * 48})

from mongomock_motor import AsyncMongoMockClient  # noqa: E402

import tenant_router as tenants  # noqa: E402

tenants.init(tenants.Clusters({"default": AsyncMongoMockClient(), "dedie-acme": AsyncMongoMockClient()}, "platform"))

import server  # noqa: E402
from clerk_auth import require_user  # noqa: E402
from fastapi import HTTPException, Request  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

ORG_A, ORG_B = "aaaaaaaa-0000-4000-8000-00000000000a", "bbbbbbbb-0000-4000-8000-00000000000b"


def fake_user(request: Request) -> dict:
    uid = request.headers.get("x-test-user")
    if not uid:
        raise HTTPException(401, "Not signed in")
    return {"user_id": uid, "session_id": "s", "claims": {"sub": uid, "iat": 9_999_999_999}}


@pytest_asyncio.fixture
async def platform():
    tenants.init(tenants.Clusters({"default": AsyncMongoMockClient(), "dedie-acme": AsyncMongoMockClient()}, "platform"))
    c = tenants.CLUSTERS.control
    for oid, name, cluster in ((ORG_A, "Société A", None), (ORG_B, "Société B", "dedie-acme")):
        await c.orgs.insert_one({"id": oid, "name": name, "slug": name.lower().replace(" ", "-"), "modules": ["dj"],
                                 "default_vat": 20, "quote_prefix": "DEV", "invoice_prefix": "FAC"})
        await tenants.provision(oid, server.INDEXES, cluster=cluster)
    for uid, oid in (("alice", ORG_A), ("bob", ORG_B)):
        await c.users.insert_one({"user_id": uid, "email": f"{uid}@test.fr", "name": uid, "org_id": oid, "role": "admin",
                                  "env": "preview", "status": "active", "last_login_at": "2999"})
    await c.users.insert_one({"user_id": "newbie", "email": "newbie@test.fr", "name": "Nouveau", "org_id": None,
                              "role": None, "env": "preview", "status": "active", "last_login_at": "2999"})
    return tenants.CLUSTERS


@pytest_asyncio.fixture
async def client(platform):
    import security
    security._hits.clear()  # limitation de débit en mémoire : remise à zéro entre tests
    server.app.dependency_overrides[require_user] = fake_user
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as c:
        yield c
    server.app.dependency_overrides.clear()


@pytest.fixture
def as_user():
    return lambda uid: {"x-test-user": uid}
