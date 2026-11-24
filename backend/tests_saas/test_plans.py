"""Offres : rubriques incluses, lecture seule si impayé, modules métier et utilisateurs limités."""
import tenant_router as tenants
from conftest import ORG_A


async def _set(platform, **sub):
    await platform.control.orgs.update_one({"id": ORG_A}, {"$set": {"subscription": sub}})


async def test_historical_company_keeps_everything(client, as_user):
    me = (await client.get("/api/me", headers=as_user("alice"))).json()
    assert me["plan"]["plan"] == "enterprise" and "finance" in me["plan"]["sections"]


async def test_section_outside_plan_is_refused(client, as_user, platform):
    await _set(platform, plan="essentiel", status="active")
    assert (await client.get("/api/contacts", headers=as_user("alice"))).status_code == 200
    r = await client.get("/api/warehouses", headers=as_user("alice"))
    assert r.status_code == 403 and "offre" in r.json()["detail"]


async def test_unpaid_is_read_only(client, as_user, platform):
    await _set(platform, plan="pro", status="past_due")
    assert (await client.get("/api/contacts", headers=as_user("alice"))).status_code == 200
    assert (await client.post("/api/contacts", json={"first_name": "x"}, headers=as_user("alice"))).status_code == 402


async def test_expired_trial_is_read_only(client, as_user, platform):
    await _set(platform, plan="pro", status="trialing", trial_ends_at="2000-01-01T00:00:00+00:00")
    assert (await client.post("/api/contacts", json={"first_name": "x"}, headers=as_user("alice"))).status_code == 402


async def test_business_modules_limited(client, as_user, platform):
    await _set(platform, plan="essentiel", status="active")
    r = await client.put("/api/org/modules", json={"modules": ["dj", "photobooth"]}, headers=as_user("alice"))
    assert r.status_code == 403
    assert (await client.put("/api/org/modules", json={"modules": ["dj"]}, headers=as_user("alice"))).status_code == 200


async def test_onboarding_starts_trial(client, as_user, platform):
    await client.post("/api/onboarding", json={"company_name": "Essai SARL"}, headers=as_user("newbie"))
    org = await platform.control.orgs.find_one({"name": "Essai SARL"})
    assert org["subscription"]["status"] == "trialing" and org["subscription"]["plan"] == "pro"
    assert tenants.tenant_db_name(org["id"]) == org["db"]["name"]
