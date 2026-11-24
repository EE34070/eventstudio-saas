"""Tests de non-régression multi-tenant : à faire passer AVANT chaque mise en production."""
import pathlib
import re


async def test_unauthenticated_is_rejected(client):
    r = await client.get("/api/contacts")
    assert r.status_code == 401


async def test_org_cannot_read_other_org_data(client, as_user):
    r = await client.post("/api/contacts", json={"display_name": "Client secret A"}, headers=as_user("alice"))
    assert r.status_code == 201
    cid = r.json()["id"]

    # Bob (org B) ne voit ni la liste, ni le détail, ni ne peut modifier/supprimer
    assert (await client.get("/api/contacts", headers=as_user("bob"))).json() == []
    assert (await client.get(f"/api/contacts/{cid}", headers=as_user("bob"))).status_code == 404
    assert (await client.patch(f"/api/contacts/{cid}", json={"display_name": "x"}, headers=as_user("bob"))).status_code == 404
    assert (await client.delete(f"/api/contacts/{cid}", headers=as_user("bob"))).status_code == 404

    # Alice le voit toujours, intact
    r = await client.get(f"/api/contacts/{cid}", headers=as_user("alice"))
    assert r.json()["display_name"] == "Client secret A"


async def test_org_header_cannot_be_forged(client, as_user):
    r = await client.get("/api/contacts", headers=as_user("bob", org="org_a"))
    assert r.status_code == 403


async def test_org_id_in_body_is_ignored(client, as_user, seeded):
    r = await client.post("/api/contacts", json={"display_name": "Intrus", "org_id": "org_a"}, headers=as_user("bob"))
    assert r.status_code == 201
    doc = await seeded.clients["default"]["t_org_b"].contacts.find_one({"_id": r.json()["id"]})
    assert doc["org_id"] == "org_b"
    assert await seeded.clients["default"]["t_org_a"].contacts.find_one({"_id": r.json()["id"]}) is None


async def test_cross_org_reference_rejected(client, as_user):
    cid = (await client.post("/api/contacts", json={"display_name": "Client A"}, headers=as_user("alice"))).json()["id"]
    r = await client.post("/api/events", json={"title": "Mariage", "starts_at": "2027-06-12T14:00:00Z", "client_id": cid},
                          headers=as_user("bob"))
    assert r.status_code == 422


async def test_module_not_in_plan_is_blocked(client, as_user):
    # Org B est en Essentiel : pas de module Stock
    assert (await client.get("/api/inventory/warehouses", headers=as_user("bob"))).status_code == 403
    assert (await client.get("/api/inventory/warehouses", headers=as_user("alice"))).status_code == 200


async def test_role_permissions(client, as_user):
    # Le technicien lit les événements mais ne peut pas créer de contacts
    assert (await client.get("/api/events", headers=as_user("tech"))).status_code == 200
    r = await client.post("/api/contacts", json={"display_name": "x"}, headers=as_user("tech"))
    assert r.status_code == 403


async def test_unpaid_subscription_is_read_only(client, as_user):
    assert (await client.get("/api/contacts", headers=as_user("carl"))).status_code == 200
    r = await client.post("/api/contacts", json={"display_name": "x"}, headers=as_user("carl"))
    assert r.status_code == 402


async def test_partner_sees_portal_not_internal(client, as_user):
    assert (await client.get("/api/contacts", headers=as_user("dj", org="org_b"))).status_code == 403
    assert (await client.get("/api/portal/events", headers=as_user("dj", org="org_b"))).status_code == 200


async def test_me_lists_orgs_and_modules(client, as_user):
    r = await client.get("/api/me", headers=as_user("dj"))
    assert {o["id"] for o in r.json()["orgs"]} == {"org_a", "org_b"}
    r = await client.get("/api/me", headers=as_user("alice"))
    keys = {m["key"] for m in r.json()["modules"]}
    assert {"contacts", "events", "inventory", "quotes"} <= keys
    assert "finance" not in keys  # pas dans le plan Pro


async def test_soft_delete_then_hidden(client, as_user):
    cid = (await client.post("/api/contacts", json={"display_name": "Temp"}, headers=as_user("alice"))).json()["id"]
    assert (await client.delete(f"/api/contacts/{cid}", headers=as_user("alice"))).status_code == 204
    assert (await client.get(f"/api/contacts/{cid}", headers=as_user("alice"))).status_code == 404


def test_modules_never_touch_db_directly():
    """Garde-fou statique : aucun module n'accède à db.<collection> ou db[...] sans TenantRepository."""
    root = pathlib.Path(__file__).parents[1] / "app" / "modules"
    pattern = re.compile(r"\bdb\s*(\[|\.(?!find|get)[a-z_]+\.)")
    offenders = [str(p) for p in root.rglob("*.py") if pattern.search(p.read_text())]
    assert offenders == [], f"Accès base direct interdit dans : {offenders}"
