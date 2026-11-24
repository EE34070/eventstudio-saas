"""Fixtures : clusters Mongo en mémoire, sociétés créées par le vrai provisioning.

L'authentification Clerk est remplacée par l'en-tête X-Test-User (tests uniquement).
"""
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from fastapi import HTTPException, Request
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.core.auth import Principal, current_principal
from app.core.db import ClusterRouter
from app.core.provisioning import create_org
from app.main import create_app

NOW = datetime(2026, 1, 1, tzinfo=UTC)


async def fake_principal(request: Request) -> Principal:
    uid = request.headers.get("X-Test-User")
    if not uid:
        raise HTTPException(401, "Authentification requise")
    return Principal(user_id=uid)


@pytest_asyncio.fixture
async def router():
    # Un cluster partagé + un cluster dédié (offre Entreprise)
    return ClusterRouter({"default": AsyncMongoMockClient(), "dedie-acme": AsyncMongoMockClient()})


@pytest_asyncio.fixture
async def seeded(router):
    await create_org(router, org_id="org_a", name="Org A", slug="a", owner_user_id="alice", plan="pro", status="active")
    await create_org(router, org_id="org_b", name="Org B", slug="b", owner_user_id="bob", plan="essentiel", status="active")
    await create_org(router, org_id="org_c", name="Org C impayée", slug="c", owner_user_id="carl", plan="pro", status="past_due")
    await create_org(router, org_id="org_d", name="Acme (dédié)", slug="d", owner_user_id="dora",
                     plan="enterprise", status="active", dedicated_cluster="dedie-acme")
    await router.control.memberships.insert_many([
        {"user_id": "tech", "org_id": "org_a", "role": "technician", "status": "active", "created_at": NOW},
        # Prestataire multi-sociétés : un compte, deux memberships
        {"user_id": "dj", "org_id": "org_a", "role": "partner", "status": "active", "created_at": NOW},
        {"user_id": "dj", "org_id": "org_b", "role": "partner", "status": "active", "created_at": NOW},
    ])
    return router


@pytest_asyncio.fixture
async def client(seeded):
    app = create_app(router=seeded)
    app.dependency_overrides[current_principal] = fake_principal
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def as_user():
    def _h(uid: str, org: str | None = None) -> dict:
        h = {"X-Test-User": uid}
        if org:
            h["X-Org-Id"] = org
        return h
    return _h
