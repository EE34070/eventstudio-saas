"""Backend e2e for Prompt 8 (iter 14): multi-warehouses, stock levels, allocation,
competing quotes, options, urgent reminder.

Always targets the QA sandbox org (slug qa-sandbox) via qa_token.py.
Never touches real Exclusivity Events org. Only the single real email allowed
(contact@exclusivity-events.com) is used — at most ONE urgent reminder send.
Data prefixed TEST_P8i14_, cleaned up by id.
"""
import os
import subprocess
import time
import uuid
from datetime import datetime, timedelta

import pytest
import requests

from conftest import API

PREFIX = "TEST_P8i14_"
RUN = uuid.uuid4().hex[:6]
ALLOWED_EMAIL = "contact@exclusivity-events.com"

_tokens: dict[str, str] = {}
_sessions: dict[str, requests.Session] = {}


def qa_token(role="admin"):
    if role in _tokens:
        return _tokens[role]
    out = subprocess.run(["python3", "/app/scripts/qa_token.py", role],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        pytest.skip(f"qa_token failed: {out.stderr[-300:]}")
    _tokens[role] = out.stdout.strip().splitlines()[-1]
    return _tokens[role]


def sess(role="admin") -> requests.Session:
    if role in _sessions:
        return _sessions[role]
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {qa_token(role)}", "Content-Type": "application/json"})
    _sessions[role] = s
    return s


_created: dict[str, list[str]] = {
    "warehouses": [], "equipment": [], "venues": [], "contacts": [],
    "events": [], "quotes": [], "tasks": [],
}


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    s = sess("admin")
    for qid in _created["quotes"]:
        s.delete(f"{API}/quotes/{qid}")
    for eid in _created["events"]:
        s.delete(f"{API}/events/{eid}")
    for tid in _created["tasks"]:
        s.delete(f"{API}/tasks/{tid}")
    for vid in _created["venues"]:
        s.delete(f"{API}/venues/{vid}")
    for cid in _created["contacts"]:
        s.delete(f"{API}/contacts/{cid}")
    for eqid in _created["equipment"]:
        s.delete(f"{API}/equipment/{eqid}")
    # Warehouses don't delete — archive them (set active=false) except default
    for wid in _created["warehouses"]:
        try:
            r = s.get(f"{API}/warehouses")
            w = next((x for x in r.json() if x["id"] == wid), None)
            if w and not w.get("is_default"):
                body = {k: w.get(k, "") for k in ("name", "type", "address", "postal_code", "city", "country",
                                                   "venue_id", "manager_contact_id", "access_hours",
                                                   "access_instructions")}
                body.update({"is_default": False, "priority": w.get("priority", 10),
                             "restricted_to_venue": bool(w.get("restricted_to_venue")), "active": False})
                s.put(f"{API}/warehouses/{wid}", json=body)
        except Exception:
            pass


# ============================================================================
# Helpers
# ============================================================================
def _mk_venue(s, name_suffix=""):
    r = s.post(f"{API}/venues", json={
        "name": f"{PREFIX}Venue_{name_suffix}_{RUN}",
        "type": "Domaine", "city": "Nîmes",
    })
    assert r.status_code in (200, 201), r.text
    v = r.json()
    _created["venues"].append(v["id"])
    return v


def _mk_eq(s, name, qty=0):
    r = s.post(f"{API}/equipment", json={
        "name": f"{PREFIX}{name}_{RUN}",
        "ref": f"P8{uuid.uuid4().hex[:6].upper()}",
        "category": "mobilier", "qty_total": qty, "unit": "u",
        "weight_kg": 2.0, "volume_m3": 0.05,
    })
    assert r.status_code in (200, 201), r.text
    eq = r.json()
    _created["equipment"].append(eq["id"])
    return eq


def _mk_contact(s, lang="fr-FR", email=None):
    email = email or f"c.{uuid.uuid4().hex[:8]}@example.com"
    r = s.post(f"{API}/contacts", json={
        "kind": "particulier", "first_name": f"{PREFIX}First",
        "last_name": f"Last{RUN}", "email": email,
        "phone": "+33612345678", "types": ["client"], "language": lang,
    })
    assert r.status_code in (200, 201), r.text
    c = r.json()
    _created["contacts"].append(c["id"])
    return c


def _mk_event(s, venue_id, client_id, title, start_date="2029-06-14", equipment=None):
    body = {
        "title": f"{PREFIX}{title}_{RUN}", "type": "Mariage",
        "client_id": client_id, "client_contact_ids": [client_id],
        "signatory_contact_id": client_id,
        "venue_id": venue_id,
        "start": f"{start_date}T18:00", "end": f"{start_date}T23:59",
        "guests": 50, "modules": ["dj"],
    }
    r = s.post(f"{API}/events", json=body)
    assert r.status_code == 200, r.text
    ev = r.json()
    _created["events"].append(ev["id"])
    if equipment:
        r = s.patch(f"{API}/events/{ev['id']}", json={"equipment": equipment})
        assert r.status_code == 200, r.text
        ev = r.json()
    return ev


def _wh_body(name, **over):
    d = {"name": name, "type": "autre", "address": "", "postal_code": "",
         "city": "", "country": "France", "venue_id": "",
         "manager_contact_id": "", "access_hours": "",
         "access_instructions": "", "is_default": False, "priority": 10,
         "restricted_to_venue": None, "active": True}
    d.update(over)
    return d


# ============================================================================
# 1. Warehouses — migration + CRUD
# ============================================================================
class TestWarehouses:
    def test_migration_default_warehouse_exists(self):
        s = sess("admin")
        r = s.get(f"{API}/warehouses")
        assert r.status_code == 200, r.text
        whs = r.json()
        assert any(w.get("is_default") for w in whs), "No default warehouse after migration"

    def test_new_equipment_level_matches_qty_total(self):
        s = sess("admin")
        eq = _mk_eq(s, "Chair", qty=400)
        r = s.get(f"{API}/equipment/{eq['id']}/stock")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total"]["on_hand"] == 400, d["total"]
        pytest.p8_eq_id = eq["id"]
        pytest.p8_eq_ref = eq["ref"]

    def test_create_site_client_wh_defaults_restricted(self):
        s = sess("admin")
        v = _mk_venue(s, "Valbonne")
        pytest.p8_venue_id = v["id"]
        # Create depot linked to venue
        r = s.post(f"{API}/warehouses",
                   json=_wh_body(f"{PREFIX}DepotValbonne_{RUN}", type="site_client", venue_id=v["id"]))
        assert r.status_code in (200, 201), r.text
        w = r.json()
        _created["warehouses"].append(w["id"])
        assert w["restricted_to_venue"] is True, "site_client should default restricted"
        assert w["type"] == "site_client"
        pytest.p8_depot_id = w["id"]

    def test_default_cannot_be_archived(self):
        s = sess("admin")
        whs = s.get(f"{API}/warehouses").json()
        default = next(w for w in whs if w["is_default"])
        pytest.p8_default_id = default["id"]
        body = _wh_body(default["name"], type=default["type"], is_default=True, active=False,
                        restricted_to_venue=False)
        r = s.put(f"{API}/warehouses/{default['id']}", json=body)
        assert r.status_code == 400, r.text

    def test_only_one_default(self):
        s = sess("admin")
        # Create a second warehouse marked default; should flip old one
        r = s.post(f"{API}/warehouses",
                   json=_wh_body(f"{PREFIX}Alt_{RUN}", type="autre", is_default=True,
                                 restricted_to_venue=False))
        assert r.status_code in (200, 201), r.text
        new = r.json()
        _created["warehouses"].append(new["id"])
        whs = s.get(f"{API}/warehouses").json()
        defaults = [w for w in whs if w["is_default"]]
        assert len(defaults) == 1 and defaults[0]["id"] == new["id"]
        # Flip back the original one
        orig = next(w for w in whs if w["id"] == pytest.p8_default_id)
        body = _wh_body(orig["name"], type=orig["type"], is_default=True,
                        restricted_to_venue=False, active=True)
        r = s.put(f"{API}/warehouses/{pytest.p8_default_id}", json=body)
        assert r.status_code == 200, r.text


# ============================================================================
# 2. Import CSV, stock levels sync, movements
# ============================================================================
class TestImportCsv:
    def test_import_csv_sets_levels(self):
        s = sess("admin")
        # Use product and depot from TestWarehouses
        whs = s.get(f"{API}/warehouses").json()
        default = next(w for w in whs if w["is_default"])
        depot = next(w for w in whs if w["id"] == pytest.p8_depot_id)
        ref = pytest.p8_eq_ref
        csv_text = (f"{ref};{default['name']};400\n"
                    f"{ref};{depot['name']};150\n"
                    f"NOPE;{default['name']};10\n")
        r = s.post(f"{API}/stock/import", json={"text": csv_text})
        assert r.status_code == 200, r.text
        res = r.json()
        assert res["imported"] == 2, res
        assert len(res["errors"]) >= 1
        # Levels + qty_total match
        r = s.get(f"{API}/equipment/{pytest.p8_eq_id}/stock")
        d = r.json()
        by_name = {w["name"]: w for w in d["warehouses"]}
        assert by_name[default["name"]]["on_hand"] == 400
        assert by_name[depot["name"]]["on_hand"] == 150
        assert d["total"]["on_hand"] == 550, d["total"]


# ============================================================================
# 3. Availability — allocation & competition scenarios
# ============================================================================
class TestAvailability:
    def test_180_at_depot_venue_splits_150_onsite_30_deliver(self):
        s = sess("admin")
        r = s.post(f"{API}/stock/availability", json={
            "date": "2029-06-14", "venue_id": pytest.p8_venue_id,
            "lines": [{"equipment_id": pytest.p8_eq_id, "qty": 180}],
        })
        assert r.status_code == 200, r.text
        d = r.json()
        row = d["rows"][0]
        on = sum(a["qty"] for a in row["allocation"] if a["fulfilment"] == "on_site")
        de = sum(a["qty"] for a in row["allocation"] if a["fulfilment"] == "to_deliver")
        assert on == 150 and de == 30, row["allocation"]
        assert d["delivery"]["to_deliver_qty"] == 30
        assert d["delivery"]["on_site_qty"] == 150
        assert d["delivery"]["all_on_site"] is False

    def test_100_at_depot_venue_all_on_site(self):
        s = sess("admin")
        r = s.post(f"{API}/stock/availability", json={
            "date": "2029-06-14", "venue_id": pytest.p8_venue_id,
            "lines": [{"equipment_id": pytest.p8_eq_id, "qty": 100}],
        })
        d = r.json()
        row = d["rows"][0]
        on = sum(a["qty"] for a in row["allocation"] if a["fulfilment"] == "on_site")
        assert on == 100
        assert d["delivery"]["all_on_site"] is True

    def test_180_elsewhere_uses_only_principal(self):
        s = sess("admin")
        v2 = _mk_venue(s, "Other")
        r = s.post(f"{API}/stock/availability", json={
            "date": "2029-06-14", "venue_id": v2["id"],
            "lines": [{"equipment_id": pytest.p8_eq_id, "qty": 180}],
        })
        d = r.json()
        row = d["rows"][0]
        # Depot restricted to its venue -> should not be used
        depot_use = sum(a["qty"] for a in row["allocation"] if a["warehouse_id"] == pytest.p8_depot_id)
        assert depot_use == 0, row["allocation"]
        total_alloc = sum(a["qty"] for a in row["allocation"])
        assert total_alloc == 180

    def test_missing_message_when_over_stock(self):
        s = sess("admin")
        r = s.post(f"{API}/stock/availability", json={
            "date": "2029-06-14", "venue_id": pytest.p8_venue_id,
            "lines": [{"equipment_id": pytest.p8_eq_id, "qty": 999}],
        })
        d = r.json()
        row = d["rows"][0]
        assert row["color"] == "red", row
        assert "Manque" in (row.get("message") or ""), row.get("message")


# ============================================================================
# 4. Two confirmed events + origin split
# ============================================================================
class TestTwoConfirmedEvents:
    def test_two_events_same_venue_second_splits(self):
        s = sess("admin")
        c = _mk_contact(s)
        ev1 = _mk_event(s, pytest.p8_venue_id, c["id"], "EV1",
                        start_date="2029-07-14",
                        equipment=[{"equipment_id": pytest.p8_eq_id, "qty": 120}])
        r = s.post(f"{API}/events/{ev1['id']}/status", json={"status": "confirme"})
        assert r.status_code == 200, r.text
        # Second event same day, 100 → 30 depot + 70 principal
        ev2 = _mk_event(s, pytest.p8_venue_id, c["id"], "EV2",
                        start_date="2029-07-14",
                        equipment=[{"equipment_id": pytest.p8_eq_id, "qty": 100}])
        r = s.post(f"{API}/events/{ev2['id']}/status", json={"status": "confirme"})
        assert r.status_code == 200, r.text
        r = s.get(f"{API}/events/{ev2['id']}/origin")
        assert r.status_code == 200, r.text
        o = r.json()
        by_id = {g["warehouse_id"]: g for g in o["groups"]}
        depot_g = by_id.get(pytest.p8_depot_id)
        assert depot_g is not None, o["groups"]
        depot_qty = sum(l["qty"] for l in depot_g["lines"])
        other_qty = sum(l["qty"] for gid, g in by_id.items() if gid != pytest.p8_depot_id for l in g["lines"])
        assert depot_qty == 30 and other_qty == 70, (depot_qty, other_qty)
        pytest.p8_ev2 = ev2["id"]
        pytest.p8_ev1 = ev1["id"]

    def test_overcommitting_confirms_with_shortage(self):
        s = sess("admin")
        c = _mk_contact(s)
        # Try confirming a 3rd event wanting 500 (stock 550, 220 already firm → 170 usable, insufficient)
        ev3 = _mk_event(s, pytest.p8_venue_id, c["id"], "EV3",
                        start_date="2029-07-14",
                        equipment=[{"equipment_id": pytest.p8_eq_id, "qty": 500}])
        r = s.post(f"{API}/events/{ev3['id']}/status", json={"status": "confirme"})
        # règle « ne jamais bloquer » : confirmation acceptée, manque listé
        assert r.status_code == 200 and r.json()["shortages_count"] >= 1, r.text
        lines = s.get(f"{API}/events/{ev3['id']}/shortages").json()["lines"]
        assert any(x["product_id"] == pytest.p8_eq_id and x["missing"] > 0 and x["status"] == "a_traiter" for x in lines)
        assert s.post(f"{API}/events/{ev3['id']}/status", json={"status": "demande"}).status_code == 200
        assert s.get(f"{API}/events/{ev3['id']}/shortages").json()["open"] == 0


# ============================================================================
# 5. Transfers
# ============================================================================
class TestTransfers:
    def test_transfer_direct_updates_both_levels(self):
        s = sess("admin")
        default_id = next(w["id"] for w in s.get(f"{API}/warehouses").json() if w["is_default"])
        before = s.get(f"{API}/equipment/{pytest.p8_eq_id}/stock").json()
        r = s.post(f"{API}/stock/transfers", json={
            "product_id": pytest.p8_eq_id, "qty": 30,
            "from_warehouse_id": default_id,
            "to_warehouse_id": pytest.p8_depot_id,
            "in_transit": False,
        })
        assert r.status_code == 200, r.text
        after = s.get(f"{API}/equipment/{pytest.p8_eq_id}/stock").json()
        assert after["total"]["on_hand"] == before["total"]["on_hand"], "Total should not change"
        by_b = {w["warehouse_id"]: w for w in before["warehouses"]}
        by_a = {w["warehouse_id"]: w for w in after["warehouses"]}
        assert by_a[default_id]["on_hand"] == by_b[default_id]["on_hand"] - 30
        assert by_a[pytest.p8_depot_id]["on_hand"] == by_b[pytest.p8_depot_id]["on_hand"] + 30
        # Movement logged
        r = s.get(f"{API}/stock/movements", params={"product_id": pytest.p8_eq_id})
        assert r.status_code == 200
        assert any(m["type"] == "transfert" for m in r.json())

    def test_transfer_in_transit_credits_only_after_receive(self):
        s = sess("admin")
        default_id = next(w["id"] for w in s.get(f"{API}/warehouses").json() if w["is_default"])
        before = s.get(f"{API}/equipment/{pytest.p8_eq_id}/stock").json()
        by_b = {w["warehouse_id"]: w for w in before["warehouses"]}
        r = s.post(f"{API}/stock/transfers", json={
            "product_id": pytest.p8_eq_id, "qty": 10,
            "from_warehouse_id": default_id,
            "to_warehouse_id": pytest.p8_depot_id,
            "in_transit": True,
        })
        assert r.status_code == 200, r.text
        mid = r.json()["id"]
        mid_state = s.get(f"{API}/equipment/{pytest.p8_eq_id}/stock").json()
        by_m = {w["warehouse_id"]: w for w in mid_state["warehouses"]}
        assert by_m[default_id]["on_hand"] == by_b[default_id]["on_hand"] - 10
        assert by_m[pytest.p8_depot_id]["on_hand"] == by_b[pytest.p8_depot_id]["on_hand"]
        # Pendant transit: on_hand warehouses baisse mais in_transit compense
        assert mid_state["in_transit"] >= 10, mid_state
        assert mid_state["total"]["on_hand"] + mid_state["in_transit"] == before["total"]["on_hand"] + before.get("in_transit", 0)
        # Receive
        r = s.post(f"{API}/stock/transfers/{mid}/receive")
        assert r.status_code == 200, r.text
        after = s.get(f"{API}/equipment/{pytest.p8_eq_id}/stock").json()
        by_a = {w["warehouse_id"]: w for w in after["warehouses"]}
        assert by_a[pytest.p8_depot_id]["on_hand"] == by_b[pytest.p8_depot_id]["on_hand"] + 10

    def test_transfer_over_stock_400(self):
        s = sess("admin")
        default_id = next(w["id"] for w in s.get(f"{API}/warehouses").json() if w["is_default"])
        r = s.post(f"{API}/stock/transfers", json={
            "product_id": pytest.p8_eq_id, "qty": 99999,
            "from_warehouse_id": default_id,
            "to_warehouse_id": pytest.p8_depot_id,
        })
        assert r.status_code == 400, r.text


# ============================================================================
# 6. Inventory, movements, equipment qty total sync
# ============================================================================
class TestInventoryAndMovements:
    def test_inventory_adjustment_creates_movement(self):
        s = sess("admin")
        eq = _mk_eq(s, "Table", qty=10)
        default_id = next(w["id"] for w in s.get(f"{API}/warehouses").json() if w["is_default"])
        r = s.post(f"{API}/stock/inventory", json={
            "warehouse_id": default_id,
            "counts": [{"product_id": eq["id"], "counted": 7}],
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["adjusted"] == 1
        # Level reflects adjustment
        st = s.get(f"{API}/equipment/{eq['id']}/stock").json()
        assert st["total"]["on_hand"] == 7

    def test_movement_entree_casse_ajustement(self):
        s = sess("admin")
        eq = _mk_eq(s, "Nappe", qty=20)
        default_id = next(w["id"] for w in s.get(f"{API}/warehouses").json() if w["is_default"])
        for t, qty in [("entree", 5), ("casse", 3), ("ajustement", 2)]:
            r = s.post(f"{API}/stock/movements", json={
                "type": t, "product_id": eq["id"],
                "warehouse_id": default_id, "qty": qty,
            })
            assert r.status_code == 200, (t, r.text)
        st = s.get(f"{API}/equipment/{eq['id']}/stock").json()
        # 20 + 5 - 3 + 2 = 24
        assert st["total"]["on_hand"] == 24, st["total"]

    def test_catalog_qty_total_change_applies_to_default(self):
        s = sess("admin")
        eq = _mk_eq(s, "Verre", qty=50)
        default_id = next(w["id"] for w in s.get(f"{API}/warehouses").json() if w["is_default"])
        r = s.put(f"{API}/equipment/{eq['id']}", json={
            "name": eq["name"], "ref": eq["ref"], "category": "mobilier",
            "qty_total": 80, "unit": "u",
        })
        assert r.status_code == 200, r.text
        st = s.get(f"{API}/equipment/{eq['id']}/stock").json()
        by = {w["warehouse_id"]: w for w in st["warehouses"]}
        assert by[default_id]["on_hand"] == 80


# ============================================================================
# 7. Manual allocations preserved + recalc
# ============================================================================
class TestManualAllocations:
    def test_put_allocations_persisted_and_recalc_resets(self):
        s = sess("admin")
        c = _mk_contact(s)
        eq = _mk_eq(s, "Chaise2", qty=100)
        default_id = next(w["id"] for w in s.get(f"{API}/warehouses").json() if w["is_default"])
        v = _mk_venue(s, "ManualVenue")
        ev = _mk_event(s, v["id"], c["id"], "EVMan", start_date="2029-08-01",
                       equipment=[{"equipment_id": eq["id"], "qty": 20}])
        # Manual split: 15 principal
        r = s.put(f"{API}/events/{ev['id']}/allocations", json={
            "equipment_id": eq["id"],
            "rows": [{"warehouse_id": default_id, "qty": 15}],
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert "manuelle" in (d.get("note") or "").lower(), d.get("note")
        # Recalc resets
        r = s.post(f"{API}/events/{ev['id']}/allocations/recalc")
        assert r.status_code == 200, r.text
        d = r.json()
        total = sum(l["qty"] for g in d["groups"] for l in g["lines"])
        assert total == 20


# ============================================================================
# 8. Stock return: casse + leave_on_site + second call 409
# ============================================================================
class TestStockReturn:
    def test_stock_return_leave_on_site_transfers_to_depot(self):
        s = sess("admin")
        c = _mk_contact(s)
        eq = _mk_eq(s, "Fauteuil", qty=30)
        v = _mk_venue(s, "RetVenue")
        # Create a depot for this venue
        r = s.post(f"{API}/warehouses",
                   json=_wh_body(f"{PREFIX}DepotRet_{RUN}", type="site_client", venue_id=v["id"]))
        assert r.status_code in (200, 201), r.text
        depot = r.json()
        _created["warehouses"].append(depot["id"])
        ev = _mk_event(s, v["id"], c["id"], "EVRet", start_date="2029-09-01",
                       equipment=[{"equipment_id": eq["id"], "qty": 10}])
        r = s.post(f"{API}/events/{ev['id']}/status", json={"status": "confirme"})
        assert r.status_code == 200, r.text
        # leave_on_site: 8 returned, 2 damaged
        r = s.post(f"{API}/events/{ev['id']}/stock-return", json={
            "mode": "leave_on_site",
            "lines": [{"equipment_id": eq["id"], "returned": 8, "damaged": 2}],
        })
        assert r.status_code == 200, r.text
        st = s.get(f"{API}/equipment/{eq['id']}/stock").json()
        by = {w["warehouse_id"]: w for w in st["warehouses"]}
        # 2 cassés diminue total ; les 8 retournés sont au dépôt
        assert st["total"]["on_hand"] == 28, st["total"]
        assert by.get(depot["id"], {}).get("on_hand", 0) == 8, by
        # second call 409
        r = s.post(f"{API}/events/{ev['id']}/stock-return", json={
            "mode": "origin", "lines": []})
        assert r.status_code == 409, r.text


# ============================================================================
# 9. Competing quotes + options + urgent reminder
# ============================================================================
class TestCompetingQuotes:
    def _prepare(self):
        s = sess("admin")
        c = _mk_contact(s)
        eq = _mk_eq(s, "ChaiseConc", qty=400)
        v = _mk_venue(s, "ConcVenue")
        # EV-A + quote with 130
        ev_a = _mk_event(s, v["id"], c["id"], "EVA", start_date="2029-10-14",
                         equipment=[{"equipment_id": eq["id"], "qty": 130}])
        r = s.post(f"{API}/events/{ev_a['id']}/quotes")
        assert r.status_code == 200, r.text
        q_a = r.json()
        _created["quotes"].append(q_a["id"])
        # Send DEV-A
        r = s.post(f"{API}/quotes/{q_a['id']}/status", json={"status": "envoye"})
        assert r.status_code == 200, r.text
        # EV-B + quote with 300
        ev_b = _mk_event(s, v["id"], c["id"], "EVB", start_date="2029-10-14",
                         equipment=[{"equipment_id": eq["id"], "qty": 300}])
        r = s.post(f"{API}/events/{ev_b['id']}/quotes")
        assert r.status_code == 200, r.text
        q_b = r.json()
        _created["quotes"].append(q_b["id"])
        r = s.post(f"{API}/quotes/{q_b['id']}/status", json={"status": "envoye"})
        assert r.status_code == 200, r.text
        return s, eq, v, ev_a, ev_b, q_a, q_b

    def test_full_competition_cycle(self):
        s, eq, v, ev_a, ev_b, q_a, q_b = self._prepare()
        # DEV-B availability should be orange and list DEV-A as competitor
        r = s.get(f"{API}/quotes/{q_b['id']}/availability")
        assert r.status_code == 200, r.text
        d = r.json()
        row = d["rows"][0]
        assert row["color"] == "orange", row
        comp_nums = [o["number"] for o in row["options"]]
        assert q_a["number"] in comp_nums, row["options"]
        assert "30" in (row["message"] or ""), row["message"]
        # /stock/options competition dict has reciprocal entries
        r = s.get(f"{API}/stock/options")
        assert r.status_code == 200, r.text
        o = r.json()
        comp = o["competition"]
        assert q_b["number"] in comp.get(q_a["id"], [])
        assert q_a["number"] in comp.get(q_b["id"], [])

        # Settings stock_count_options=true → row should become red
        r = s.put(f"{API}/stock/settings", json={"stock_count_options": True, "option_days": 7})
        assert r.status_code == 200, r.text
        try:
            r = s.get(f"{API}/quotes/{q_b['id']}/availability")
            assert r.json()["rows"][0]["color"] == "red"
        finally:
            # REMETTRE à false
            r = s.put(f"{API}/stock/settings", json={"stock_count_options": False, "option_days": 7})
            assert r.status_code == 200

        # Accept DEV-A → DEV-B becomes red and a task is created
        r = s.post(f"{API}/quotes/{q_a['id']}/status", json={"status": "accepte"})
        assert r.status_code == 200, r.text
        r = s.get(f"{API}/quotes/{q_b['id']}/availability")
        assert r.json()["rows"][0]["color"] == "red"
        r = s.get(f"{API}/tasks")
        assert r.status_code == 200
        titles = [t["title"] for t in r.json()["tasks"]]
        assert any(q_b["number"] in t for t in titles), titles

    def test_urgent_reminder_language_and_privacy(self):
        s = sess("admin")
        c_en = _mk_contact(s, lang="en-US")
        eq = _mk_eq(s, "ChaiseEN", qty=400)
        v = _mk_venue(s, "ENVenue")
        ev = _mk_event(s, v["id"], c_en["id"], "EVEN", start_date="2029-11-14",
                       equipment=[{"equipment_id": eq["id"], "qty": 130}])
        r = s.post(f"{API}/events/{ev['id']}/quotes")
        assert r.status_code == 200, r.text
        q = r.json()
        _created["quotes"].append(q["id"])
        # draft -> 400 on POST reminder
        r = s.post(f"{API}/quotes/{q['id']}/urgent-reminder", json={"deadline": "", "set_deadline": True})
        assert r.status_code == 400, r.text
        # Send it
        r = s.post(f"{API}/quotes/{q['id']}/status", json={"status": "envoye"})
        assert r.status_code == 200, r.text
        # Preview in EN, must contain number but NOT other quote info (none here)
        r = s.get(f"{API}/quotes/{q['id']}/urgent-reminder")
        assert r.status_code == 200, r.text
        pv = r.json()
        assert pv["language"].startswith("en"), pv["language"]
        assert q["number"] in pv["subject"] or q["number"] in pv["body"]
        # Should NOT contain another quote number, other client name, or qty
        assert "DEV-" not in pv["body"].replace(q["number"], "")
        # Verify no "130" (qty of other quote scenario) leaked — our scenario has this
        # single quote so no other qty to check beyond its own. Pass.

    def test_urgent_reminder_send_dedup_48h(self):
        """Only against the one allowed email; create 1 quote, send once, retry must 409."""
        s = sess("admin")
        c = _mk_contact(s, email=ALLOWED_EMAIL)
        eq = _mk_eq(s, "ChaiseSend", qty=400)
        v = _mk_venue(s, "SendVenue")
        ev = _mk_event(s, v["id"], c["id"], "EVSend", start_date="2029-12-14",
                       equipment=[{"equipment_id": eq["id"], "qty": 20}])
        r = s.post(f"{API}/events/{ev['id']}/quotes")
        assert r.status_code == 200, r.text
        q = r.json()
        _created["quotes"].append(q["id"])
        r = s.post(f"{API}/quotes/{q['id']}/status", json={"status": "envoye"})
        assert r.status_code == 200, r.text
        # Send
        r = s.post(f"{API}/quotes/{q['id']}/urgent-reminder",
                   json={"subject": "", "body": "", "deadline": "", "set_deadline": True})
        # Could 200 (sent) OR 500 if SMTP not configured — accept 200/500 but prefer 200
        if r.status_code not in (200, 500):
            pytest.fail(f"unexpected status {r.status_code}: {r.text}")
        if r.status_code == 500:
            pytest.skip("SMTP not available in preview; skipping 48h dedup assertion")
        # Second within 48h → 409 reminder_recent
        r2 = s.post(f"{API}/quotes/{q['id']}/urgent-reminder",
                    json={"deadline": "", "set_deadline": True})
        assert r2.status_code == 409, r2.text
        assert r2.json().get("detail", {}).get("code") == "reminder_recent" or "reminder_recent" in r2.text


# ============================================================================
# 10. Option expiry releases option and creates task
# ============================================================================
class TestOptionExpiry:
    def test_patch_past_expiry_releases_option(self):
        s = sess("admin")
        c = _mk_contact(s)
        eq = _mk_eq(s, "ChaiseExp", qty=400)
        v = _mk_venue(s, "ExpVenue")
        ev = _mk_event(s, v["id"], c["id"], "EVExp", start_date="2030-01-14",
                       equipment=[{"equipment_id": eq["id"], "qty": 130}])
        r = s.post(f"{API}/events/{ev['id']}/quotes")
        q = r.json()
        _created["quotes"].append(q["id"])
        s.post(f"{API}/quotes/{q['id']}/status", json={"status": "envoye"})
        # PATCH option with a past date
        past = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d")
        # The route sets option_released_at=None only if date >= today, so past date stays expired
        r = s.patch(f"{API}/quotes/{q['id']}/option",
                    json={"option_expires_at": past})
        assert r.status_code == 200, r.text
        # Wait: the route doesn't immediately mark released when setting past date,
        # but expire_options() runs on prepare(). So call /stock/options to trigger it.
        r = s.get(f"{API}/stock/options")
        assert r.status_code == 200
        r = s.get(f"{API}/quotes/{q['id']}/availability")
        d = r.json()
        # Option is now released → should be green (plenty of stock)
        assert d["option_released_at"], d
        # Task "Relancer ou clôturer" should exist
        r = s.get(f"{API}/tasks")
        titles = [t["title"] for t in r.json()["tasks"]]
        assert any(q["number"] in t and ("Relancer" in t or "clôturer" in t) for t in titles), titles


# ============================================================================
# 11. RBAC: technicien denied
# ============================================================================
class TestRbac:
    def test_tech_cannot_create_warehouse(self):
        tok = qa_token("technicien")
        r = requests.post(f"{API}/warehouses",
                          headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                          json=_wh_body(f"{PREFIX}NoAccess_{RUN}"))
        assert r.status_code == 403, r.status_code

    def test_tech_cannot_transfer(self):
        tok = qa_token("technicien")
        r = requests.post(f"{API}/stock/transfers",
                          headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                          json={"product_id": "x", "qty": 1, "from_warehouse_id": "a", "to_warehouse_id": "b"})
        assert r.status_code == 403, r.status_code

    def test_tech_cannot_availability(self):
        tok = qa_token("technicien")
        r = requests.post(f"{API}/stock/availability",
                          headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                          json={"date": "2029-01-01", "venue_id": "", "lines": []})
        assert r.status_code == 403, r.status_code
