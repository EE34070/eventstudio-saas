"""ERP événementiel – backend regression: auth, RBAC, multi-tenant, conflicts, closing rule, CRUD."""
import time

import requests

from conftest import API, client


# --- Auth / me
class TestAuth:
    def test_no_token_401(self):
        assert requests.get(f"{API}/me").status_code == 401
        assert requests.get(f"{API}/events").status_code == 401

    def test_me_admin(self, admin):
        r = admin.get(f"{API}/me")
        assert r.status_code == 200
        d = r.json()
        assert d["org"]["slug"] == "exclusivity-events"
        assert d["user"]["role"] == "admin"
        assert "users:manage" in d["perms"]


# --- RBAC
class TestRBAC:
    def test_technicien_scope(self, tech, events_by_code):
        me = tech.get(f"{API}/me").json()
        assert me["user"]["role"] == "technicien"
        tid = me["user"]["team_id"]
        r = tech.get(f"{API}/events")
        assert r.status_code == 200
        rows = r.json()
        for e in rows:
            assert "amount_ht" not in e
            assert any(t["member_id"] == tid for t in e["team"])
        mine = {e["id"] for e in rows}
        other = next(e for e in events_by_code.values() if e["id"] not in mine)
        assert tech.get(f"{API}/events/{other['id']}").status_code == 404
        if rows:
            d = tech.get(f"{API}/events/{rows[0]['id']}").json()
            assert "amount_ht" not in d
            assert tech.patch(f"{API}/events/{rows[0]['id']}", json={"notes": "x"}).status_code == 403

    def test_comptable(self, compta, events_by_code):
        e = events_by_code["EVT-2026-005"]
        cur = compta.get(f"{API}/events/{e['id']}").json()
        r = compta.patch(f"{API}/events/{e['id']}", json={"deposit_paid": cur["deposit_paid"], "invoice_paid": cur["invoice_paid"]})
        assert r.status_code == 200, r.text
        assert compta.patch(f"{API}/events/{e['id']}", json={"title": "Hack"}).status_code == 403

    def test_commercial_cannot_delete(self, commercial, events_by_code):
        e = events_by_code["EVT-2026-005"]
        assert commercial.delete(f"{API}/events/{e['id']}").status_code == 403


# --- Multi-tenant
class TestTenant:
    def test_new_org_isolation(self, events_by_code):
        c = client(f"test_tenant{int(time.time())}+clerk_test@example.com", "admin", "none")
        me = c.get(f"{API}/me").json()
        assert me["org"] is None
        assert c.get(f"{API}/events").status_code == 403
        r = c.post(f"{API}/onboarding", json={"company_name": "TEST_Org", "city": "Nice"})
        assert r.status_code == 200, r.text
        me = c.get(f"{API}/me").json()
        assert me["org"]["name"] == "TEST_Org" and me["user"]["role"] == "admin"
        assert c.get(f"{API}/events").json() == []
        assert c.get(f"{API}/events/{events_by_code['EVT-2026-001']['id']}").status_code == 404
        assert c.get(f"{API}/contacts").json() == []
        assert c.get(f"{API}/equipment").json()["items"] == []


# --- Business rules
class TestRules:
    def test_double_booking(self, admin, events_by_code):
        e = events_by_code["EVT-2026-008"]
        assert e["status"] == "demande"
        r = admin.post(f"{API}/events/{e['id']}/status", json={"status": "confirme"})
        assert r.status_code == 409, r.text
        det = r.json()["detail"]
        assert det["conflicts"]
        codes = [x["code"] for c in det["conflicts"] for x in c["events"]]
        assert "EVT-2026-007" in codes
        assert admin.get(f"{API}/events/{e['id']}").json()["status"] == "demande"

    def test_close_rule(self, admin, events_by_code):
        e4 = events_by_code["EVT-2026-004"]
        r = admin.post(f"{API}/events/{e4['id']}/status", json={"status": "cloture"})
        assert r.status_code == 400 and "matériel" in r.text
        e3 = events_by_code["EVT-2026-003"]
        r = admin.post(f"{API}/events/{e3['id']}/status", json={"status": "cloture"})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "cloture"
        # revert
        assert admin.post(f"{API}/events/{e3['id']}/status", json={"status": e3["status"]}).status_code == 200


# --- Event CRUD + equipment + shift
class TestEventFlow:
    def test_create_patch_shift_delete(self, admin, events_by_code):
        eqs = admin.get(f"{API}/equipment").json()["items"]
        lyre = next(x for x in eqs if x["ref"] == "LUM-001")
        r = admin.post(f"{API}/events", json={"title": "TEST_Event", "start": "2027-09-10T18:00", "end": "2027-09-11T02:00"})
        assert r.status_code == 200, r.text
        eid = r.json()["id"]
        try:
            r = admin.patch(f"{API}/events/{eid}", json={"equipment": [{"equipment_id": lyre["id"], "qty": 2}],
                                                        "prestations": [{"module": "dj", "title": "TEST DJ", "price": 500}]})
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["amount_equipment"] == 2 * lyre["price_day"] * d["rental_days"]
            assert d["amount_ht"] == d["amount_equipment"] + 500
            assert len(d["history"]) >= 2 and d["history"][0]["action"] == "Modification"
            r = admin.post(f"{API}/events/{eid}/shift", json={"days": 3})
            assert r.status_code == 200 and r.json()["start"] == "2027-09-13T18:00"
            # conflict guard on shift: confirm with all lyres, then shift onto EVT-2026-007 gala
            g = events_by_code["EVT-2026-007"]
            admin.patch(f"{API}/events/{eid}", json={"equipment": [{"equipment_id": lyre["id"], "qty": lyre["qty_total"]}]})
            assert admin.post(f"{API}/events/{eid}/status", json={"status": "confirme"}).status_code == 200
            from datetime import date
            days = (date.fromisoformat(g["start"][:10]) - date(2027, 9, 13)).days
            r = admin.post(f"{API}/events/{eid}/shift", json={"days": days})
            assert r.status_code == 409, r.text
        finally:
            assert admin.delete(f"{API}/events/{eid}").status_code == 200
        assert admin.get(f"{API}/events/{eid}").status_code == 404


# --- Catalogue
class TestCatalogue:
    def test_availability_and_maintenance(self, admin):
        r = admin.get(f"{API}/equipment", params={"start": "2026-12-04T07:00", "end": "2026-12-05T10:00"})
        assert r.status_code == 200
        lyre = next(x for x in r.json()["items"] if x["ref"] == "LUM-001")
        assert lyre["reserved"] >= 10 and lyre["available"] == lyre["qty_total"] - lyre["qty_maintenance"] - lyre["reserved"]
        assert admin.get(f"{API}/equipment", params={"start": "2026-12-05T10:00", "end": "2026-12-04T07:00"}).status_code == 400
        r = admin.post(f"{API}/equipment", json={"ref": f"TEST-{int(time.time())}", "name": "TEST_Eq", "qty_total": 4, "price_day": 10})
        assert r.status_code == 200, r.text
        eid = r.json()["id"]
        try:
            r = admin.post(f"{API}/equipment/{eid}/maintenance", json={"action": "start", "qty": 2, "note": "t"})
            assert r.json()["qty_maintenance"] == 2
            r = admin.post(f"{API}/equipment/{eid}/maintenance", json={"action": "end", "qty": 1})
            assert r.json()["qty_maintenance"] == 1
            assert admin.post(f"{API}/equipment/{eid}/maintenance", json={"action": "end", "qty": 5}).status_code == 400
            assert admin.get(f"{API}/equipment/{eid}/bookings").status_code == 200
        finally:
            assert admin.delete(f"{API}/equipment/{eid}").status_code == 200

    def test_packs_crud(self, admin):
        r = admin.post(f"{API}/packs", json={"name": "TEST_Pack", "price": 100})
        assert r.status_code == 200
        pid = r.json()["id"]
        r = admin.put(f"{API}/packs/{pid}", json={"name": "TEST_Pack2", "price": 120})
        assert r.json()["name"] == "TEST_Pack2"
        assert any(p["id"] == pid for p in admin.get(f"{API}/packs").json())
        assert admin.delete(f"{API}/packs/{pid}").status_code == 200
        assert admin.delete(f"{API}/packs/{pid}").status_code == 404


# --- Contacts, venues, team, users
class TestCRM:
    def test_contacts(self, admin):
        r = admin.post(f"{API}/contacts", json={"first_name": "TEST_Jean", "last_name": "Dupont", "city": "Nice"})
        cid = r.json()["id"]
        try:
            r = admin.post(f"{API}/contacts/{cid}/interactions", json={"type": "appel", "note": "TEST call"})
            assert r.status_code == 200
            d = admin.get(f"{API}/contacts/{cid}").json()
            assert d["display_name"] == "TEST_Jean Dupont" and len(d["interactions"]) == 1
            r = admin.put(f"{API}/contacts/{cid}", json={"first_name": "TEST_Jean", "last_name": "Martin"})
            assert r.status_code == 200 and admin.get(f"{API}/contacts/{cid}").json()["last_name"] == "Martin"
            assert any(c["id"] == cid for c in admin.get(f"{API}/contacts", params={"q": "TEST_Jean"}).json())
        finally:
            assert admin.delete(f"{API}/contacts/{cid}").status_code == 200

    def test_venues(self, admin):
        r = admin.post(f"{API}/venues", json={"name": "TEST_Venue", "city": "Cannes", "lat": 43.55, "lng": 7.01})
        vid = r.json()["id"]
        r = admin.put(f"{API}/venues/{vid}", json={"name": "TEST_Venue2", "city": "Cannes"})
        assert r.json()["name"] == "TEST_Venue2"
        assert admin.get(f"{API}/venues/{vid}").json()["events"] == []
        assert admin.delete(f"{API}/venues/{vid}").status_code == 200

    def test_team_grant(self, admin, commercial):
        r = admin.post(f"{API}/team", json={"name": "TEST_Member", "access_role": "technicien"})
        assert r.status_code == 200
        tid = r.json()["id"]
        r = admin.put(f"{API}/team/{tid}", json={"name": "TEST_Member2", "access_role": "technicien"})
        assert r.json()["name"] == "TEST_Member2"
        assert admin.delete(f"{API}/team/{tid}").status_code == 200
        assert commercial.post(f"{API}/team", json={"name": "TEST_x"}).status_code == 403

    def test_cannot_grant_above_own(self):
        g = client("test_gerant+clerk_test@example.com", "gerant")
        assert g.post(f"{API}/team", json={"name": "TEST_x", "access_role": "admin"}).status_code == 403

    def test_users_and_last_admin(self, admin):
        r = admin.get(f"{API}/users")
        assert r.status_code == 200
        users = r.json()["users"]
        admins = [u for u in users if u["role"] == "admin"]
        assert admins
        me = next(u for u in users if u["email"] == "test_admin+clerk_test@example.com")
        if len(admins) == 1:
            r = admin.patch(f"{API}/users/{me['user_id']}/role", json={"role": "gerant"})
            assert r.status_code == 409
        tgt = next((u for u in users if u["email"] == "test_commercial+clerk_test@example.com"), None)
        if tgt:
            r = admin.patch(f"{API}/users/{tgt['user_id']}/role", json={"role": "commercial"})
            assert r.status_code == 200


class TestMisc:
    def test_dashboard_search_notifications(self, admin, tech):
        d = admin.get(f"{API}/dashboard").json()
        assert "kpis" in d and "alerts" in d and len(d["months"]) == 12
        assert any(a["type"] == "conflit" for a in d["alerts"])
        assert "kpis" not in tech.get(f"{API}/dashboard").json()
        s = admin.get(f"{API}/search", params={"q": "Mariage"}).json()
        assert s["events"]
        n = admin.get(f"{API}/notifications").json()
        assert "alerts" in n and "activity" in n
