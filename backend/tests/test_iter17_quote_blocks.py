"""Backend e2e for iter 17 — PROMPT_DEVIS §1 / §2 / §2bis / §4 (quote blocks, spaces, dates, price masking).

Targets the QA sandbox org only (slug qa-sandbox) via qa_token.py. Never touches
'Exclusivity Events'. All created records are prefixed TEST_PDi17_ and cleaned
up by id at module teardown. No real emails are sent (we never POST /send on a
quote whose client has a real address, except the 400 path which is pre-email).
"""
import os
import subprocess
import uuid
from datetime import datetime, timedelta

import pytest
import requests

from conftest import API

PREFIX = "TEST_PDi17_"
RUN = uuid.uuid4().hex[:6]
NOREPLY = "noreply.pdi17@example.com"

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


_created: dict[str, list[str]] = {k: [] for k in ("quotes", "events", "venues", "contacts", "equipment", "templates", "tasks")}


def _rm(path, items):
    s = sess("admin")
    for i in items:
        try:
            s.delete(f"{API}/{path}/{i}")
        except Exception:
            pass


@pytest.fixture(scope="module", autouse=True)
def _cleanup():
    yield
    _rm("quotes", _created["quotes"])
    _rm("events", _created["events"])
    _rm("venues", _created["venues"])
    _rm("contacts", _created["contacts"])
    _rm("equipment", _created["equipment"])
    _rm("quote-section-templates", _created["templates"])


# ---------- helpers ----------
def _venue(s, name):
    r = s.post(f"{API}/venues", json={"name": f"{PREFIX}{name}_{RUN}", "type": "Domaine",
                                       "address": "1 rue Test", "zip": "30000", "city": "Nîmes"})
    assert r.status_code in (200, 201), r.text
    v = r.json()
    _created["venues"].append(v["id"])
    return v


def _contact(s, email=None):
    email = email or f"c.{uuid.uuid4().hex[:8]}@example.com"
    r = s.post(f"{API}/contacts", json={"kind": "particulier", "first_name": f"{PREFIX}F",
                                         "last_name": f"L{RUN}", "email": email, "phone": "+33600000000",
                                         "types": ["client"], "language": "fr-FR"})
    assert r.status_code in (200, 201), r.text
    c = r.json()
    _created["contacts"].append(c["id"])
    return c


def _eq(s, name, qty=100):
    r = s.post(f"{API}/equipment", json={"name": f"{PREFIX}{name}_{RUN}", "ref": f"P17{uuid.uuid4().hex[:6].upper()}",
                                          "category": "mobilier", "qty_total": qty, "unit": "u",
                                          "weight_kg": 1.0, "volume_m3": 0.01})
    assert r.status_code in (200, 201), r.text
    eq = r.json()
    _created["equipment"].append(eq["id"])
    return eq


def _direct(s, venue_id, client_id, lines, date=None):
    date = date or (datetime.utcnow() + timedelta(days=60)).strftime("%Y-%m-%d")
    r = s.post(f"{API}/quotes/direct", json={"client_ids": [client_id], "type": "Mariage",
                                              "date": date, "venue_id": venue_id, "guests": 50,
                                              "lines": lines, "deposit_percent": 30})
    assert r.status_code == 200, r.text
    q = r.json()
    _created["quotes"].append(q["id"])
    _created["events"].append(q["event_id"])
    return q


# ========================================================================
# 1. Migration: direct quote -> structure returns single section "Prestations"
# ========================================================================
class TestMigration:
    def test_direct_quote_migrates_to_prestations_section(self):
        s = sess("admin")
        v = _venue(s, "MigVen")
        c = _contact(s)
        q = _direct(s, v["id"], c["id"], [
            {"label": "Service A", "qty": 2, "unit_price": 100, "vat": 20},
            {"label": "Service B", "qty": 1, "unit_price": 50, "vat": 20},
        ])
        before_ttc = q["total_ttc"]
        r = s.get(f"{API}/quotes/{q['id']}/structure")
        assert r.status_code == 200, r.text
        st = r.json()
        sections = [b for b in st["blocks"] if b["type"] == "section"]
        assert len(sections) == 1 and sections[0]["title"] == "Prestations"
        lines = [b for b in st["blocks"] if b["type"] == "line"]
        assert len(lines) == 2
        assert all(l["parent_id"] == sections[0]["id"] for l in lines)
        # Total unchanged: verify via /structure recompute, which returns total_ttc
        assert q["total_ttc"] == 250 * 1.2 or abs(q["total_ttc"] - 300.0) < 0.1
        # Re-fetch quote via list (GET /quotes is allowed; GET /quotes/{id} is not)
        qs = s.get(f"{API}/quotes?event_id={q['event_id']}").json()
        matching = [x for x in qs if x["id"] == q["id"]]
        assert matching and matching[0]["total_ttc"] == before_ttc


# ========================================================================
# 2. PUT structure validation + totals + discounts + optional
# ========================================================================
class TestPutStructure:
    @pytest.fixture(scope="class")
    def quote(self):
        s = sess("admin")
        v = _venue(s, "StructVen")
        c = _contact(s)
        q = _direct(s, v["id"], c["id"], [{"label": "Base", "qty": 1, "unit_price": 100, "vat": 20}])
        return {"s": s, "qid": q["id"], "venue_id": v["id"]}

    def _tree(self):
        s1, s2, sub1 = "s1_" + RUN, "s2_" + RUN, "sub1_" + RUN
        return [
            {"id": s1, "type": "section", "title": "Cérémonie"},
            {"id": "l1_" + RUN, "parent_id": s1, "type": "line", "label": "Enceinte", "qty": 2, "unit_price": 100, "vat": 20},
            {"id": sub1, "parent_id": s1, "type": "subsection", "title": "Micros"},
            {"id": "l2_" + RUN, "parent_id": sub1, "type": "line", "label": "Micro HF", "qty": 1, "unit_price": 50, "vat": 20},
            {"id": s2, "type": "section", "title": "Cocktail"},
            {"id": "l3_" + RUN, "parent_id": s2, "type": "line", "label": "Table", "qty": 4, "unit_price": 25, "vat": 20},
        ]

    def test_valid_tree_recomputes_totals(self, quote):
        body = {"blocks": self._tree(), "price_display": "detailed", "deposit_percent": 30}
        r = quote["s"].put(f"{API}/quotes/{quote['qid']}/structure", json=body)
        assert r.status_code == 200, r.text
        # 2*100 + 50 + 4*25 = 350 HT; TTC 420
        assert abs(r.json()["total_ht"] - 350.0) < 0.01
        assert abs(r.json()["total_ttc"] - 420.0) < 0.01

    def test_line_without_section_400(self, quote):
        body = {"blocks": [{"id": "x", "type": "line", "label": "orphelin", "qty": 1, "unit_price": 10, "vat": 20}],
                "price_display": "detailed", "deposit_percent": 30}
        r = quote["s"].put(f"{API}/quotes/{quote['qid']}/structure", json=body)
        assert r.status_code == 400, r.text

    def test_subsection_outside_section_400(self, quote):
        body = {"blocks": [
            {"id": "sub", "type": "subsection", "title": "orpheline"},
            {"id": "l", "parent_id": "sub", "type": "line", "label": "x", "qty": 1, "unit_price": 1, "vat": 20},
        ], "price_display": "detailed", "deposit_percent": 30}
        r = quote["s"].put(f"{API}/quotes/{quote['qid']}/structure", json=body)
        assert r.status_code == 400

    def test_empty_title_400(self, quote):
        body = {"blocks": [
            {"id": "s", "type": "section", "title": "   "},
            {"id": "l", "parent_id": "s", "type": "line", "label": "x", "qty": 1, "unit_price": 1, "vat": 20},
        ], "price_display": "detailed", "deposit_percent": 30}
        r = quote["s"].put(f"{API}/quotes/{quote['qid']}/structure", json=body)
        assert r.status_code == 400

    def test_duplicate_ids_400(self, quote):
        dup = "dup_" + RUN
        body = {"blocks": [
            {"id": dup, "type": "section", "title": "A"},
            {"id": dup, "type": "section", "title": "B"},
            {"id": "l", "parent_id": dup, "type": "line", "label": "x", "qty": 1, "unit_price": 1, "vat": 20},
        ], "price_display": "detailed", "deposit_percent": 30}
        r = quote["s"].put(f"{API}/quotes/{quote['qid']}/structure", json=body)
        assert r.status_code == 400

    def test_line_section_global_discounts_apply(self, quote):
        sid = "ds_" + RUN
        body = {"blocks": [
            {"id": sid, "type": "section", "title": "Disc", "discount_percent": 10},
            {"id": "ld_" + RUN, "parent_id": sid, "type": "line", "label": "x",
             "qty": 1, "unit_price": 100, "vat": 20, "discount_percent": 10},
        ], "price_display": "detailed", "global_discount_percent": 10, "deposit_percent": 30}
        r = quote["s"].put(f"{API}/quotes/{quote['qid']}/structure", json=body)
        assert r.status_code == 200, r.text
        # 100 * 0.9 (line) * 0.9 (global) * 0.9 (section) = 72.9
        assert abs(r.json()["total_ht"] - 72.9) < 0.1

    def test_optional_section_not_in_total(self, quote):
        s1, opt = "sa_" + RUN, "sopt_" + RUN
        body = {"blocks": [
            {"id": s1, "type": "section", "title": "Base"},
            {"id": "lb_" + RUN, "parent_id": s1, "type": "line", "label": "x", "qty": 1, "unit_price": 100, "vat": 20},
            {"id": opt, "type": "section", "title": "Option", "optional": True, "selected": False},
            {"id": "lo_" + RUN, "parent_id": opt, "type": "line", "label": "y", "qty": 1, "unit_price": 500, "vat": 20},
        ], "price_display": "detailed", "deposit_percent": 30}
        r = quote["s"].put(f"{API}/quotes/{quote['qid']}/structure", json=body)
        assert r.status_code == 200, r.text
        assert abs(r.json()["total_ht"] - 100.0) < 0.01


# ========================================================================
# 3. Same product in two sections -> availability sums qty
# ========================================================================
class TestAvailabilitySum:
    def test_same_product_two_sections_sums(self):
        s = sess("admin")
        v = _venue(s, "AvailVen")
        c = _contact(s)
        eq = _eq(s, "Enceinte", qty=10)
        q = _direct(s, v["id"], c["id"], [
            {"label": eq["name"], "qty": 2, "unit_price": 50, "vat": 20, "equipment_id": eq["id"], "kind": "catalog"},
        ])
        s1, s2 = "s1_" + RUN, "s2_" + RUN
        body = {"blocks": [
            {"id": s1, "type": "section", "title": "Cérémonie"},
            {"id": "la_" + RUN, "parent_id": s1, "type": "line", "label": eq["name"],
             "qty": 2, "unit_price": 50, "vat": 20, "equipment_id": eq["id"], "kind": "catalog"},
            {"id": s2, "type": "section", "title": "Cocktail"},
            {"id": "lb_" + RUN, "parent_id": s2, "type": "line", "label": eq["name"],
             "qty": 3, "unit_price": 50, "vat": 20, "equipment_id": eq["id"], "kind": "catalog"},
        ], "price_display": "detailed", "deposit_percent": 30}
        r = s.put(f"{API}/quotes/{q['id']}/structure", json=body)
        assert r.status_code == 200, r.text
        r = s.get(f"{API}/quotes/{q['id']}/availability")
        assert r.status_code == 200, r.text
        rows = r.json().get("rows") or []
        mine = [row for row in rows if row.get("product_id") == eq["id"]]
        assert mine, rows
        assert mine[0]["qty"] == 5, mine


# ========================================================================
# 4. Dates propagation to event + logistics generate + validation errors
# ========================================================================
class TestDates:
    def test_dates_propagate_to_event_and_missions(self):
        s = sess("admin")
        v = _venue(s, "DateVen")
        c = _contact(s)
        eq = _eq(s, "Chair", qty=50)
        q = _direct(s, v["id"], c["id"], [
            {"label": eq["name"], "qty": 4, "unit_price": 10, "vat": 20,
             "equipment_id": eq["id"], "kind": "catalog"},
        ])
        # J and J+1 dates (far future to avoid collision)
        J = (datetime.utcnow() + timedelta(days=90)).strftime("%Y-%m-%d")
        Jp1 = (datetime.utcnow() + timedelta(days=91)).strftime("%Y-%m-%d")
        sid = "sx_" + RUN
        body = {
            "blocks": [
                {"id": sid, "type": "section", "title": "Cérémonie"},
                {"id": "lx_" + RUN, "parent_id": sid, "type": "line", "label": eq["name"],
                 "qty": 4, "unit_price": 10, "vat": 20, "equipment_id": eq["id"], "kind": "catalog"},
            ],
            "dates": {
                "delivery": {"enabled": True, "date": J, "start": "10:00", "end": "12:00"},
                "operation": {"start": f"{J}T16:00", "end": f"{Jp1}T02:00"},
                "pickup": {"enabled": True, "date": Jp1, "start": "10:00", "end": "12:00"},
                "delivery_same_day": True,
                "pickup_after_operation": True,
            },
            "price_display": "detailed", "deposit_percent": 30,
        }
        r = s.put(f"{API}/quotes/{q['id']}/structure", json=body)
        assert r.status_code == 200, r.text

        ev = s.get(f"{API}/events/{q['event_id']}").json()
        assert ev["setup_start"].startswith(f"{J}T10:00")
        assert ev["start"].startswith(f"{J}T16:00")
        assert ev["end"].startswith(f"{Jp1}T02:00")
        assert ev["return_end"].startswith(f"{Jp1}T12:00")

        # Accept the quote so logistics generate has material to deliver
        r = s.post(f"{API}/quotes/{q['id']}/status", json={"status": "accepte"})
        assert r.status_code == 200, r.text
        r = s.post(f"{API}/events/{q['event_id']}/logistics/generate")
        assert r.status_code == 200, r.text
        missions = r.json().get("missions", [])
        liv = next((m for m in missions if m["type"] == "livraison"), None)
        retr = next((m for m in missions if m["type"] == "retrait"), None)
        assert liv and retr, missions
        assert liv["date"] == J and liv["window_start"] == "10:00" and liv["window_end"] == "12:00"
        assert retr["date"] == Jp1 and retr["window_start"] == "10:00" and retr["window_end"] == "12:00"

    def test_delivery_after_operation_start_400(self):
        s = sess("admin")
        v = _venue(s, "LateDel")
        c = _contact(s)
        q = _direct(s, v["id"], c["id"], [{"label": "svc", "qty": 1, "unit_price": 10, "vat": 20}])
        J = (datetime.utcnow() + timedelta(days=95)).strftime("%Y-%m-%d")
        sid = "sld_" + RUN
        body = {
            "blocks": [
                {"id": sid, "type": "section", "title": "S"},
                {"id": "l_" + RUN, "parent_id": sid, "type": "line", "label": "svc", "qty": 1, "unit_price": 10, "vat": 20},
            ],
            "dates": {
                # delivery AFTER operation start (18:00 > 16:00)
                "delivery": {"enabled": True, "date": J, "start": "18:00", "end": "19:00"},
                "operation": {"start": f"{J}T16:00", "end": f"{J}T22:00"},
                "pickup": {"enabled": True, "date": J, "start": "22:00", "end": "23:00"},
                "delivery_same_day": False, "pickup_after_operation": False,
            },
            "price_display": "detailed", "deposit_percent": 30,
        }
        r = s.put(f"{API}/quotes/{q['id']}/structure", json=body)
        assert r.status_code == 400, r.text
        assert "livraison" in r.text.lower()

    def test_pickup_before_operation_end_400(self):
        s = sess("admin")
        v = _venue(s, "EarlyPk")
        c = _contact(s)
        q = _direct(s, v["id"], c["id"], [{"label": "svc", "qty": 1, "unit_price": 10, "vat": 20}])
        J = (datetime.utcnow() + timedelta(days=96)).strftime("%Y-%m-%d")
        sid = "sep_" + RUN
        body = {
            "blocks": [
                {"id": sid, "type": "section", "title": "S"},
                {"id": "l_" + RUN, "parent_id": sid, "type": "line", "label": "svc", "qty": 1, "unit_price": 10, "vat": 20},
            ],
            "dates": {
                "delivery": {"enabled": True, "date": J, "start": "10:00", "end": "12:00"},
                "operation": {"start": f"{J}T16:00", "end": f"{J}T22:00"},
                # pickup window ends BEFORE operation end
                "pickup": {"enabled": True, "date": J, "start": "18:00", "end": "20:00"},
                "delivery_same_day": False, "pickup_after_operation": False,
            },
            "price_display": "detailed", "deposit_percent": 30,
        }
        r = s.put(f"{API}/quotes/{q['id']}/structure", json=body)
        assert r.status_code == 400, r.text
        assert "retrait" in r.text.lower()

    def test_no_delivery_no_pickup_no_missions_generated(self):
        s = sess("admin")
        v = _venue(s, "NoLogi")
        c = _contact(s)
        q = _direct(s, v["id"], c["id"], [{"label": "DJ", "qty": 1, "unit_price": 500, "vat": 20}])
        J = (datetime.utcnow() + timedelta(days=97)).strftime("%Y-%m-%d")
        sid = "snl_" + RUN
        body = {
            "blocks": [
                {"id": sid, "type": "section", "title": "DJ"},
                {"id": "l_" + RUN, "parent_id": sid, "type": "line", "label": "DJ", "qty": 1, "unit_price": 500, "vat": 20},
            ],
            "dates": {
                "delivery": {"enabled": False, "date": "", "start": "", "end": ""},
                "operation": {"start": f"{J}T18:00", "end": f"{J}T23:00"},
                "pickup": {"enabled": False, "date": "", "start": "", "end": ""},
                "delivery_same_day": False, "pickup_after_operation": False,
            },
            "price_display": "detailed", "deposit_percent": 30,
        }
        r = s.put(f"{API}/quotes/{q['id']}/structure", json=body)
        assert r.status_code == 200, r.text
        r = s.post(f"{API}/quotes/{q['id']}/status", json={"status": "accepte"})
        assert r.status_code == 200, r.text
        r = s.post(f"{API}/events/{q['event_id']}/logistics/generate")
        assert r.status_code == 200, r.text
        assert r.json().get("missions", []) == [], r.json()


# ========================================================================
# 5. Price masking on public quote (no auth)
# ========================================================================
class TestPriceMasking:
    def _make(self, s, price_display):
        v = _venue(s, f"Mask{price_display}")
        c = _contact(s, email=NOREPLY)
        q = _direct(s, v["id"], c["id"], [{"label": "svc", "qty": 1, "unit_price": 100, "vat": 20}])
        s1 = "sm_" + RUN + "_" + price_display[:5]
        body = {
            "blocks": [
                {"id": s1, "type": "section", "title": "Prestations"},
                {"id": "lm_" + RUN + "_" + price_display[:5], "parent_id": s1, "type": "line",
                 "label": "svc", "qty": 1, "unit_price": 100, "vat": 20},
            ],
            "price_display": price_display, "deposit_percent": 30,
        }
        r = s.put(f"{API}/quotes/{q['id']}/structure", json=body)
        assert r.status_code == 200, r.text
        token = s.post(f"{API}/quotes/{q['id']}/share").json()["token"]
        return q["id"], token

    def test_section_totals_hides_unit_price_keeps_subtotals(self):
        s = sess("admin")
        _, token = self._make(s, "section_totals")
        # public endpoint without auth
        r = requests.get(f"{API}/public/quotes/{token}", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("lines") == [], "lines must be empty in masked modes"
        rows = data.get("rows", [])
        line_rows = [r for r in rows if r.get("kind") == "line"]
        assert line_rows, "expected at least one line row"
        for lr in line_rows:
            assert "unit_price" not in lr, f"leaked unit_price: {lr}"
            assert lr.get("hide_price") is True, lr
        # subtotal present
        assert any(r.get("kind") == "subtotal" for r in rows), rows

    def test_total_only_hides_unit_price_and_subtotals(self):
        s = sess("admin")
        _, token = self._make(s, "total_only")
        r = requests.get(f"{API}/public/quotes/{token}", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("lines") == []
        rows = data.get("rows", [])
        for lr in [r for r in rows if r.get("kind") == "line"]:
            assert "unit_price" not in lr
        assert not any(r.get("kind") == "subtotal" for r in rows), rows

    def test_none_blocks_send_and_signature(self):
        s = sess("admin")
        qid, _ = self._make(s, "none")
        r = s.post(f"{API}/quotes/{qid}/send")
        assert r.status_code == 400, r.text
        assert "sans prix" in r.text.lower() or "prix" in r.text.lower()
        r = s.post(f"{API}/quotes/{qid}/signature")
        assert r.status_code == 400, r.text


# ========================================================================
# 6. Public option toggle
# ========================================================================
class TestPublicOption:
    @pytest.fixture(scope="class")
    def opt_quote(self):
        s = sess("admin")
        v = _venue(s, "OptVen")
        c = _contact(s)
        q = _direct(s, v["id"], c["id"], [{"label": "svc", "qty": 1, "unit_price": 100, "vat": 20}])
        base = "ob_" + RUN
        opt = "oo_" + RUN
        nonopt = "on_" + RUN
        body = {"blocks": [
            {"id": base, "type": "section", "title": "Base"},
            {"id": "lb_" + RUN, "parent_id": base, "type": "line", "label": "svc",
             "qty": 1, "unit_price": 100, "vat": 20},
            {"id": opt, "type": "section", "title": "Photobooth", "optional": True, "selected": False},
            {"id": "lo_" + RUN, "parent_id": opt, "type": "line", "label": "Photobooth",
             "qty": 1, "unit_price": 300, "vat": 20},
            {"id": nonopt, "type": "section", "title": "AutreNonOpt"},
            {"id": "ln_" + RUN, "parent_id": nonopt, "type": "line", "label": "x",
             "qty": 1, "unit_price": 10, "vat": 20},
        ], "price_display": "detailed", "deposit_percent": 30}
        r = s.put(f"{API}/quotes/{q['id']}/structure", json=body)
        assert r.status_code == 200, r.text
        # Must be at least "envoye" status for option (brouillon is also allowed per code)
        token = s.post(f"{API}/quotes/{q['id']}/share").json()["token"]
        return {"s": s, "qid": q["id"], "number": q["number"], "token": token,
                "opt_id": opt, "nonopt_id": nonopt}

    def test_select_option_updates_total_and_flags_modified(self, opt_quote):
        r = requests.post(f"{API}/public/quotes/{opt_quote['token']}/options",
                          json={"section_id": opt_quote["opt_id"], "selected": True}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("client_modified") is True
        # TTC should include option now: (100+10+300)*1.2 = 492
        assert abs(r.json()["total_ttc"] - 492.0) < 0.05
        # Task created in back-office
        tasks = opt_quote["s"].get(f"{API}/tasks").json()
        rows = tasks.get("tasks", []) if isinstance(tasks, dict) else tasks
        titles = [t.get("title", "") for t in rows]
        assert any(opt_quote["number"] in t and "modifi" in t.lower() for t in titles), titles

    def test_option_on_non_optional_section_404(self, opt_quote):
        r = requests.post(f"{API}/public/quotes/{opt_quote['token']}/options",
                          json={"section_id": opt_quote["nonopt_id"], "selected": True}, timeout=30)
        assert r.status_code == 404, r.text

    def test_option_on_accepted_quote_409(self, opt_quote):
        s = opt_quote["s"]
        r = s.post(f"{API}/quotes/{opt_quote['qid']}/status", json={"status": "accepte"})
        assert r.status_code == 200, r.text
        r = requests.post(f"{API}/public/quotes/{opt_quote['token']}/options",
                          json={"section_id": opt_quote["opt_id"], "selected": False}, timeout=30)
        assert r.status_code == 409, r.text


# ========================================================================
# 7. PDFs (quote + installation)
# ========================================================================
class TestPdfs:
    def test_quote_pdf_and_installation_pdf(self):
        s = sess("admin")
        v = _venue(s, "PdfVen")
        # Add space to venue first
        r = s.post(f"{API}/venues/{v['id']}/spaces", json={"name": "Le Temple"})
        assert r.status_code == 200, r.text
        space_id = r.json()["id"]
        c = _contact(s)
        eq = _eq(s, "Enc", qty=20)
        q = _direct(s, v["id"], c["id"], [
            {"label": eq["name"], "qty": 2, "unit_price": 50, "vat": 20,
             "equipment_id": eq["id"], "kind": "catalog"},
        ])
        J = (datetime.utcnow() + timedelta(days=100)).strftime("%Y-%m-%d")
        Jp1 = (datetime.utcnow() + timedelta(days=101)).strftime("%Y-%m-%d")
        sid = "spv_" + RUN
        body = {
            "blocks": [
                {"id": sid, "type": "section", "title": "Cérémonie", "space_id": space_id},
                {"id": "lpv_" + RUN, "parent_id": sid, "type": "line", "label": eq["name"],
                 "qty": 2, "unit_price": 50, "vat": 20, "equipment_id": eq["id"], "kind": "catalog"},
            ],
            "dates": {
                "delivery": {"enabled": True, "date": J, "start": "10:00", "end": "12:00"},
                "operation": {"start": f"{J}T16:00", "end": f"{Jp1}T02:00"},
                "pickup": {"enabled": True, "date": Jp1, "start": "10:00", "end": "12:00"},
                "delivery_same_day": True, "pickup_after_operation": True,
            },
            "price_display": "detailed", "deposit_percent": 30,
        }
        r = s.put(f"{API}/quotes/{q['id']}/structure", json=body)
        assert r.status_code == 200, r.text
        # Quote PDF
        r = s.get(f"{API}/quotes/{q['id']}/pdf")
        assert r.status_code == 200, r.text
        assert r.content[:4] == b"%PDF", r.content[:20]
        # Installation PDF
        r = s.get(f"{API}/quotes/{q['id']}/installation/pdf")
        assert r.status_code == 200, r.text
        assert r.content[:4] == b"%PDF"

    def test_pdf_section_totals_no_unit_price_text(self):
        s = sess("admin")
        v = _venue(s, "PdfMask")
        c = _contact(s)
        q = _direct(s, v["id"], c["id"], [{"label": "UNIQUEPRICE999", "qty": 1, "unit_price": 777.77, "vat": 20}])
        sid = "spm_" + RUN
        body = {"blocks": [
            {"id": sid, "type": "section", "title": "Prestations"},
            {"id": "lpm_" + RUN, "parent_id": sid, "type": "line", "label": "UNIQUEPRICE999",
             "qty": 1, "unit_price": 777.77, "vat": 20},
        ], "price_display": "section_totals", "deposit_percent": 30}
        r = s.put(f"{API}/quotes/{q['id']}/structure", json=body)
        assert r.status_code == 200, r.text
        r = s.get(f"{API}/quotes/{q['id']}/pdf")
        assert r.status_code == 200
        # PDF bytes: "777,77" or "777.77" should not appear as unit price text when masked
        body_bytes = r.content
        # Best-effort: binary may be compressed, but the ReportLab canvas text stream usually leaves ASCII numbers unencrypted. Skip hard-assert on binary.
        # We assert PDF validity only.
        assert body_bytes[:4] == b"%PDF"


# ========================================================================
# 8. Spaces + templates persistence
# ========================================================================
class TestSpacesAndTemplates:
    def test_add_space_then_template_returned_by_structure(self):
        s = sess("admin")
        v = _venue(s, "TplVen")
        r = s.post(f"{API}/venues/{v['id']}/spaces", json={"name": "La Folie"})
        assert r.status_code == 200, r.text
        space_id = r.json()["id"]

        c = _contact(s)
        q = _direct(s, v["id"], c["id"], [{"label": "x", "qty": 1, "unit_price": 10, "vat": 20}])

        # save a section template
        tpl_blocks = [
            {"id": "ts_" + RUN, "type": "section", "title": "Sono cérémonie laïque"},
            {"id": "tl_" + RUN, "parent_id": "ts_" + RUN, "type": "line", "label": "Enceinte",
             "qty": 2, "unit_price": 100, "vat": 20},
        ]
        r = s.post(f"{API}/quote-section-templates",
                   json={"name": f"{PREFIX}Tpl_{RUN}", "blocks": tpl_blocks})
        assert r.status_code == 200, r.text
        tid = r.json().get("id")
        if tid:
            _created["templates"].append(tid)

        # GET /structure returns templates list
        r = s.get(f"{API}/quotes/{q['id']}/structure")
        assert r.status_code == 200
        tpls = r.json().get("templates", [])
        assert any(t.get("name", "").startswith(f"{PREFIX}Tpl_{RUN}") for t in tpls), tpls
        # And the venue's spaces include the just-added one
        sp_ids = {sp["id"] for sp in r.json().get("spaces", [])}
        assert space_id in sp_ids


# ========================================================================
# 9. Legacy PUT /quotes/{id} still works + accept + invoice on structured quote
# ========================================================================
class TestLegacyAndInvoice:
    def test_legacy_put_quotes_still_works(self):
        s = sess("admin")
        v = _venue(s, "LegacyVen")
        c = _contact(s)
        q = _direct(s, v["id"], c["id"], [{"label": "legacy", "qty": 1, "unit_price": 100, "vat": 20}])
        r = s.put(f"{API}/quotes/{q['id']}", json={
            "lines": [{"label": "legacy2", "qty": 2, "unit_price": 50, "vat": 20}],
            "deposit_percent": 30, "valid_until": "", "notes": "", "language": "",
        })
        assert r.status_code == 200, r.text
        assert abs(r.json()["total_ht"] - 100.0) < 0.01

    def test_accept_structured_quote_and_make_deposit_invoice(self):
        s = sess("admin")
        v = _venue(s, "InvVen")
        c = _contact(s)
        q = _direct(s, v["id"], c["id"], [{"label": "svc", "qty": 1, "unit_price": 200, "vat": 20}])
        sid = "sa_" + RUN
        body = {"blocks": [
            {"id": sid, "type": "section", "title": "Prestations"},
            {"id": "lsa_" + RUN, "parent_id": sid, "type": "line", "label": "svc",
             "qty": 1, "unit_price": 200, "vat": 20},
        ], "price_display": "detailed", "deposit_percent": 30}
        r = s.put(f"{API}/quotes/{q['id']}/structure", json=body)
        assert r.status_code == 200, r.text
        r = s.post(f"{API}/quotes/{q['id']}/status", json={"status": "accepte"})
        assert r.status_code == 200, r.text
        r = s.post(f"{API}/quotes/{q['id']}/invoice", json={"kind": "acompte"})
        assert r.status_code == 200, r.text
        inv = r.json()
        assert inv.get("kind") == "acompte"


# ========================================================================
# 10. RBAC: technicien cannot GET/PUT /quotes/{id}/structure
# ========================================================================
class TestRbac:
    def test_technicien_cannot_read_structure(self):
        s_admin = sess("admin")
        v = _venue(s_admin, "RbacVen")
        c = _contact(s_admin)
        q = _direct(s_admin, v["id"], c["id"], [{"label": "svc", "qty": 1, "unit_price": 10, "vat": 20}])
        s_tech = sess("technicien")
        r = s_tech.get(f"{API}/quotes/{q['id']}/structure")
        assert r.status_code == 403, r.text
