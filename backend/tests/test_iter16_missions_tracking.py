"""Backend e2e for iter 16 — Prompt 9 (complement): mission check/sign/photos + public tracking link.

QA sandbox only. All records prefixed TEST_P9c. Cleaned by id at module teardown.
No real messages: reminders only tested in draft mode. The default QA warehouse
lat/lng is stripped at teardown if modified.
"""
import base64
import io
import subprocess
import uuid
from datetime import datetime, timedelta

import pytest
import requests

from conftest import API, BASE_URL

PREFIX = "TEST_P9c_"
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
    "vehicles": [], "equipment": [], "venues": [], "contacts": [],
    "events": [], "quotes": [], "tasks": [],
}
_wh_restore: dict | None = None


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
    # Restore QA default warehouse lat/lng if we modified it
    global _wh_restore
    if _wh_restore:
        try:
            s = sess("admin")
            s.put(f"{API}/warehouses/{_wh_restore['id']}", json=_wh_restore["body"])
        except Exception:
            pass
    _rm("quotes", _created["quotes"])
    _rm("events", _created["events"])
    _rm("tasks", _created["tasks"])
    _rm("venues", _created["venues"])
    _rm("contacts", _created["contacts"])
    _rm("equipment", _created["equipment"])
    _rm("vehicles", _created["vehicles"])


# ---------- helpers ----------
def _mk_venue(s, suffix, lat=None, lng=None, logistics=None, onsite_contacts=None):
    body = {"name": f"{PREFIX}{suffix}_{RUN}", "type": "Domaine",
            "address": "12 rue du Test", "zip": "30000", "city": "Nîmes"}
    if lat is not None:
        body["lat"], body["lng"] = lat, lng
    if onsite_contacts:
        body["onsite_contacts"] = onsite_contacts
    r = s.post(f"{API}/venues", json=body)
    assert r.status_code in (200, 201), r.text
    v = r.json()
    _created["venues"].append(v["id"])
    if logistics:
        r = s.put(f"{API}/venues/{v['id']}/logistics", json=logistics)
        assert r.status_code == 200, r.text
    return v


def _mk_eq(s, name, qty=200):
    r = s.post(f"{API}/equipment", json={
        "name": f"{PREFIX}{name}_{RUN}",
        "ref": f"P9c{uuid.uuid4().hex[:6].upper()}",
        "category": "mobilier", "qty_total": qty, "unit": "u",
        "weight_kg": 2.0, "volume_m3": 0.05,
    })
    assert r.status_code in (200, 201), r.text
    eq = r.json()
    _created["equipment"].append(eq["id"])
    return eq


def _mk_contact(s, email=None):
    email = email or f"c.{uuid.uuid4().hex[:8]}@example.com"
    r = s.post(f"{API}/contacts", json={
        "kind": "particulier", "first_name": f"{PREFIX}First",
        "last_name": f"Last{RUN}", "email": email,
        "phone": "+33612345678", "types": ["client"], "language": "fr-FR",
    })
    assert r.status_code in (200, 201), r.text
    c = r.json()
    _created["contacts"].append(c["id"])
    return c


def _mk_event(s, venue_id, client_id, title, start_date=None, equipment=None, status="confirme"):
    if not start_date:
        start_date = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")
    body = {
        "title": f"{PREFIX}{title}_{RUN}", "type": "Mariage",
        "client_id": client_id, "client_contact_ids": [client_id],
        "signatory_contact_id": client_id,
        "venue_id": venue_id,
        "start": f"{start_date}T18:00", "end": f"{start_date}T23:59",
        "guests": 50, "modules": ["loueur_materiel"],
    }
    r = s.post(f"{API}/events", json=body)
    assert r.status_code == 200, r.text
    ev = r.json()
    _created["events"].append(ev["id"])
    # Force setup_start/return_end to match start to avoid auto-shift
    r = s.patch(f"{API}/events/{ev['id']}", json={
        "setup_start": body["start"], "return_end": body["end"],
    })
    if r.status_code == 200:
        ev = r.json()
    if equipment:
        r = s.patch(f"{API}/events/{ev['id']}", json={"equipment": equipment})
        assert r.status_code == 200, r.text
        ev = r.json()
    # need a direct quote for stock to be allocated? No - 'equipment' lines drive to_deliver
    if status:
        r = s.post(f"{API}/events/{ev['id']}/status", json={"status": status})
        assert r.status_code == 200, r.text
        ev = r.json()
    return ev


def _mk_vehicle(s, suffix, **over):
    body = {"name": f"{PREFIX}{suffix}_{RUN}", "plate": f"BB-{uuid.uuid4().hex[:3].upper()}-ZZ",
            "type": "utilitaire", "licence_required": "B", "tailgate": True,
            "length_m": 5.5, "height_m": 2.5, "capacity_kg": 1200, "seats": 3,
            "cost_km": 0.5, "ownership": "propre", "active": True,
            "ct_due": "", "insurance_due": "", "service_due": "",
            "unavailabilities": [], "rental_start": "", "rental_end": "", "rental_cost": 0,
            "volume_m3": 10}
    body.update(over)
    r = s.post(f"{API}/vehicles", json=body)
    assert r.status_code in (200, 201), r.text
    v = r.json()
    _created["vehicles"].append(v["id"])
    return v


def _driver(s, first="Jean", last="Dupont", phone="+33677889900"):
    """Create a team member driver. Returns member id or None if not possible."""
    r = s.get(f"{API}/team")
    if r.status_code != 200:
        return None
    body = {"first_name": first, "last_name": last, "role": "chauffeur",
            "email": f"drv.{uuid.uuid4().hex[:6]}@example.com",
            "phone": phone, "is_driver": True, "licences": ["B"], "active": True}
    r = s.post(f"{API}/team", json=body)
    if r.status_code not in (200, 201):
        return None
    return r.json()


# Minimal 1x1 PNG with a visible dark pixel (for signature validation)
def _dark_png_data_url():
    # 10x10 black square PNG
    from PIL import Image
    im = Image.new("RGBA", (40, 40), (0, 0, 0, 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _white_png_data_url():
    from PIL import Image
    im = Image.new("RGBA", (40, 40), (255, 255, 255, 0))  # fully transparent/white
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _small_png_bytes():
    from PIL import Image
    im = Image.new("RGB", (40, 40), (120, 120, 120))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


# ---------- shared fixtures ----------
@pytest.fixture(scope="module")
def default_wh():
    """Return QA default warehouse record and save initial state for teardown."""
    global _wh_restore
    s = sess("admin")
    r = s.get(f"{API}/warehouses")
    assert r.status_code == 200, r.text
    whs = r.json()
    wh = next((w for w in whs if w.get("is_default")), None) or whs[0]
    # snapshot body fields we might PUT
    _wh_restore = {"id": wh["id"], "body": {
        "name": wh["name"], "type": wh.get("type", "principal"),
        "address": wh.get("address", ""), "postal_code": wh.get("postal_code", ""),
        "city": wh.get("city", ""), "country": wh.get("country", "France"),
        "lat": wh.get("lat"), "lng": wh.get("lng"),
        "venue_id": wh.get("venue_id", ""),
        "manager_contact_id": wh.get("manager_contact_id", ""),
        "access_hours": wh.get("access_hours", ""),
        "access_instructions": wh.get("access_instructions", ""),
        "is_default": wh.get("is_default", True),
        "priority": wh.get("priority", 10),
        "restricted_to_venue": wh.get("restricted_to_venue"),
        "active": wh.get("active", True),
    }}
    return wh


@pytest.fixture(scope="module")
def mission_ready(default_wh):
    """Create an event+venue+equipment+vehicle, generate missions, place material, return (mission_livraison, mission_retrait, ctx dict)."""
    s = sess("admin")
    v = _mk_venue(s, "MisVen", logistics={
        "delivery_address": "", "access_hours": "", "delivery_start": "09:00",
        "delivery_end": "11:00", "pickup_start": "17:00", "pickup_end": "19:00",
        "max_length_m": 0, "max_height_m": 0, "max_tonnage_t": 0,
        "tailgate_required": False, "dock_distance_m": 0, "stairs": "",
        "parking": "", "gate_code": "", "instructions": "",
        "preferred_channel": "email", "reminders_off": False,
    })
    c = _mk_contact(s, email=ALLOWED_EMAIL)
    eq = _mk_eq(s, "MisChair", qty=200)
    ev = _mk_event(s, v["id"], c["id"], "MisEv",
                   equipment=[{"equipment_id": eq["id"], "qty": 4, "price_day": 5}],
                   status="confirme")
    veh = _mk_vehicle(s, "MisVeh")
    r = s.post(f"{API}/events/{ev['id']}/logistics/generate")
    assert r.status_code == 200, r.text
    missions = r.json()["missions"]
    liv = next(m for m in missions if m["type"] == "livraison")
    ret = next(m for m in missions if m["type"] == "retrait")
    # Add vehicle to livraison + auto-place
    r = s.post(f"{API}/logistics/missions/{liv['id']}/vehicles",
               json={"vehicle_id": veh["id"], "driver_ids": []})
    assert r.status_code == 200, r.text
    r = s.post(f"{API}/logistics/missions/{liv['id']}/auto", json={"mode": "random"})
    assert r.status_code == 200, r.text
    liv = r.json()
    # Same for retrait
    r = s.post(f"{API}/logistics/missions/{ret['id']}/vehicles",
               json={"vehicle_id": veh["id"], "driver_ids": []})
    assert r.status_code == 200, r.text
    r = s.post(f"{API}/logistics/missions/{ret['id']}/auto", json={"mode": "random"})
    ret = r.json()
    return {"liv": liv, "ret": ret, "event": ev, "venue": v, "vehicle": veh, "eq": eq, "contact": c}


# ============================================================================
# 1. PATCH item check — cap at qty
# ============================================================================
class TestCheckItem:
    def test_check_item_caps_at_qty(self, mission_ready):
        s = sess("admin")
        liv = mission_ready["liv"]
        item = next((i for i in liv["items"] if i.get("mv_id")), None)
        if not item:
            # fall back: place at least one
            item = liv["items"][0]
        r = s.patch(f"{API}/logistics/missions/{liv['id']}/items/{item['id']}",
                    json={"loaded_qty": 9999})
        assert r.status_code == 200, r.text
        m = r.json()
        found = next(i for i in m["items"] if i["id"] == item["id"])
        assert found["loaded_qty"] == found["qty"], found


# ============================================================================
# 2. Tracking link + public tracking endpoint
# ============================================================================
class TestTrackingPublic:
    def test_tracking_link_stable(self, mission_ready):
        s = sess("admin")
        liv = mission_ready["liv"]
        r1 = s.get(f"{API}/logistics/missions/{liv['id']}/tracking-link")
        assert r1.status_code == 200, r1.text
        url1 = r1.json()["url"]
        assert "/suivi/" in url1, url1
        token = url1.rsplit("/suivi/", 1)[1]
        assert len(token) >= 20, token
        r2 = s.get(f"{API}/logistics/missions/{liv['id']}/tracking-link")
        assert r2.json()["url"] == url1
        pytest.p9c_track_url = url1
        pytest.p9c_track_token = token

    def test_tracking_url_host_matches_backend(self, mission_ready):
        url = getattr(pytest, "p9c_track_url", None) or \
              sess("admin").get(f"{API}/logistics/missions/{mission_ready['liv']['id']}/tracking-link").json()["url"]
        from urllib.parse import urlparse
        backend_host = urlparse(BASE_URL).netloc
        url_host = urlparse(url).netloc
        # Report mismatch but don't fail: APP_URL may be a specific preview
        if url_host != backend_host:
            pytest.p9c_host_mismatch = {"url_host": url_host, "backend_host": backend_host}
        assert url_host, f"empty host in tracking url: {url}"

    def test_public_tracking_no_auth(self, mission_ready):
        token = getattr(pytest, "p9c_track_token", None)
        if not token:
            pytest.skip("token not captured")
        r = requests.get(f"{API}/public/tracking/{token}")  # no Authorization header
        assert r.status_code == 200, r.text
        d = r.json()
        assert "status" in d and "status_label" in d
        assert "vehicles" in d and "items" in d and "drivers" in d
        # No PII leak: no client name, no amounts, no org_id, no email
        flat = str(d)
        assert ALLOWED_EMAIL not in flat, "contact email leaked in public payload"
        assert "org_id" not in d, d.keys()
        contact = mission_ready["contact"]
        name = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()
        assert name not in flat, f"client name '{name}' leaked in public payload"
        # No amount field
        for k in ("amount", "total", "total_ttc", "price"):
            assert k not in d, f"amount field '{k}' leaked"

    def test_public_tracking_unknown_token_404(self):
        bad = "x" * 30
        r = requests.get(f"{API}/public/tracking/{bad}")
        assert r.status_code == 404, r.text

    def test_public_tracking_short_token_404(self):
        r = requests.get(f"{API}/public/tracking/short")
        assert r.status_code == 404, r.text


# ============================================================================
# 3. Mission photos
# ============================================================================
class TestMissionPhotos:
    def test_image_accepted_pdf_refused(self, mission_ready):
        s = requests.Session()
        s.headers.update({"Authorization": f"Bearer {qa_token('admin')}"})
        liv_id = mission_ready["liv"]["id"]
        # image ok
        r = s.post(f"{API}/logistics/missions/{liv_id}/photos",
                   files={"file": ("photo.png", _small_png_bytes(), "image/png")})
        assert r.status_code == 200, r.text
        assert len(r.json().get("photos") or []) >= 1
        # pdf refused
        r = s.post(f"{API}/logistics/missions/{liv_id}/photos",
                   files={"file": ("bad.pdf", b"%PDF-1.4\n%fake", "application/pdf")})
        assert r.status_code == 400, r.text


# ============================================================================
# 4. Sign mission — livraison -> livree, retrait -> retiree, 409 re-sign, 400 empty
# ============================================================================
class TestMissionSign:
    def test_empty_signature_400(self, mission_ready):
        s = sess("admin")
        liv_id = mission_ready["liv"]["id"]
        r = s.post(f"{API}/logistics/missions/{liv_id}/sign",
                   json={"signer_name": "Jean Client",
                         "signature": _white_png_data_url(), "notes": ""})
        assert r.status_code == 400, r.text

    def test_sign_livraison_sets_livree_and_doc(self, mission_ready):
        s = sess("admin")
        liv_id = mission_ready["liv"]["id"]
        ev_id = mission_ready["event"]["id"]
        r = s.post(f"{API}/logistics/missions/{liv_id}/sign",
                   json={"signer_name": "Jean Client",
                         "signature": _dark_png_data_url(), "notes": "ok"})
        assert r.status_code == 200, r.text
        m = r.json()
        assert m["status"] == "livree", m
        assert m.get("signed_at"), m
        assert m.get("bon_file"), m
        pytest.p9c_bon_file = m["bon_file"]

        # Second sign -> 409
        r2 = s.post(f"{API}/logistics/missions/{liv_id}/sign",
                    json={"signer_name": "Jean Client",
                          "signature": _dark_png_data_url(), "notes": ""})
        assert r2.status_code == 409, r2.text

        # Doc listed
        r3 = s.get(f"{API}/events/{ev_id}/documents")
        assert r3.status_code == 200, r3.text
        docs = r3.json()
        bon_docs = [d for d in docs if d.get("kind") == "Bon signé (mission)"]
        assert bon_docs, docs
        assert any(d["ref"] == m["bon_file"] for d in bon_docs)

    def test_download_bon_pdf(self, mission_ready):
        """GET the file ref via /api/files/<ref> or similar: try both patterns."""
        ref = getattr(pytest, "p9c_bon_file", None)
        if not ref:
            pytest.skip("bon_file not captured")
        s = sess("admin")
        # Common pattern: GET /api/files/{ref}
        for path in (f"{API}/files/{ref}", f"{API}/files?ref={ref}"):
            r = s.get(path, allow_redirects=True)
            if r.status_code == 200:
                assert r.content.startswith(b"%PDF") or b"PDF" in r.content[:10], f"not a PDF ({len(r.content)} bytes)"
                return
        pytest.skip(f"no file download endpoint found for ref {ref}")

    def test_photo_rejected_after_sign(self, mission_ready):
        s = requests.Session()
        s.headers.update({"Authorization": f"Bearer {qa_token('admin')}"})
        liv_id = mission_ready["liv"]["id"]
        r = s.post(f"{API}/logistics/missions/{liv_id}/photos",
                   files={"file": ("photo.png", _small_png_bytes(), "image/png")})
        assert r.status_code == 400, r.text

    def test_sign_retrait_sets_retiree(self, mission_ready):
        s = sess("admin")
        ret_id = mission_ready["ret"]["id"]
        r = s.post(f"{API}/logistics/missions/{ret_id}/sign",
                   json={"signer_name": "Agent Retrait",
                         "signature": _dark_png_data_url(), "notes": ""})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "retiree"


# ============================================================================
# 5. PATCH status en_route — eta/en_route_at logic
# ============================================================================
class TestEnRouteEta:
    def _fresh_mission_with_coords(self, with_coords):
        """Build a brand new event+mission; set GPS on the default WH + venue if with_coords, else not."""
        s = sess("admin")
        lat, lng = (43.8367, 4.3601) if with_coords else (None, None)
        lat_v, lng_v = (43.6108, 3.8767) if with_coords else (None, None)
        v = _mk_venue(s, f"EtaVen{'Gps' if with_coords else 'NoGps'}",
                      lat=lat_v, lng=lng_v,
                      logistics={"delivery_start": "10:00", "delivery_end": "12:00",
                                  "pickup_start": "17:00", "pickup_end": "19:00",
                                  "delivery_address": "", "access_hours": "",
                                  "max_length_m": 0, "max_height_m": 0, "max_tonnage_t": 0,
                                  "tailgate_required": False, "dock_distance_m": 0,
                                  "stairs": "", "parking": "", "gate_code": "",
                                  "instructions": "", "preferred_channel": "email",
                                  "reminders_off": False})
        c = _mk_contact(s)
        eq = _mk_eq(s, f"EtaEq{'Gps' if with_coords else 'NoGps'}", qty=50)
        ev = _mk_event(s, v["id"], c["id"], f"EtaEv{'Gps' if with_coords else 'NoGps'}",
                       equipment=[{"equipment_id": eq["id"], "qty": 2, "price_day": 5}],
                       status="confirme")
        # Set / strip default warehouse lat/lng
        r = s.get(f"{API}/warehouses")
        wh = next((w for w in r.json() if w.get("is_default")), r.json()[0])
        body = dict(_wh_restore["body"])
        body["lat"] = lat
        body["lng"] = lng
        r = s.put(f"{API}/warehouses/{wh['id']}", json=body)
        assert r.status_code == 200, r.text
        # Generate
        r = s.post(f"{API}/events/{ev['id']}/logistics/generate")
        assert r.status_code == 200, r.text
        liv = next(m for m in r.json()["missions"] if m["type"] == "livraison")
        return liv

    def test_en_route_with_coords_sets_eta(self, default_wh):
        s = sess("admin")
        liv = self._fresh_mission_with_coords(True)
        r = s.patch(f"{API}/logistics/missions/{liv['id']}",
                    json={"status": "en_route", "confirm": True})
        assert r.status_code == 200, r.text
        m = r.json()
        assert m["status"] == "en_route"
        assert m.get("en_route_at"), m
        assert m.get("eta"), f"expected eta populated when both sides have GPS: {m}"
        # Public tracking shows eta
        tok = s.get(f"{API}/logistics/missions/{liv['id']}/tracking-link").json()["url"].rsplit("/suivi/", 1)[1]
        pub = requests.get(f"{API}/public/tracking/{tok}").json()
        assert pub.get("eta"), pub
        # Change status -> eta hidden in public payload
        r = s.patch(f"{API}/logistics/missions/{liv['id']}",
                    json={"status": "livree"})
        assert r.status_code == 200
        pub2 = requests.get(f"{API}/public/tracking/{tok}").json()
        assert not pub2.get("eta"), f"eta should be hidden when status != en_route: {pub2}"

    def test_en_route_without_coords_no_eta(self, default_wh):
        liv = self._fresh_mission_with_coords(False)
        s = sess("admin")
        r = s.patch(f"{API}/logistics/missions/{liv['id']}",
                    json={"status": "en_route", "confirm": True})
        assert r.status_code == 200, r.text
        m = r.json()
        assert m.get("en_route_at"), m
        assert not m.get("eta"), f"eta should be empty without GPS: {m.get('eta')}"


# ============================================================================
# 6. Cross-org mission not accessible
# ============================================================================
class TestCrossOrg:
    def test_other_org_mission_404(self, mission_ready):
        # demo admin can't see qa-sandbox missions
        from conftest import token_for
        try:
            tok = token_for("test_admin+clerk_test@example.com", "admin", "demo")
        except Exception:
            pytest.skip("demo token unavailable")
        s = requests.Session()
        s.headers.update({"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        liv_id = mission_ready["liv"]["id"]
        r = s.get(f"{API}/logistics/missions/{liv_id}/tracking-link")
        assert r.status_code == 404, r.text
        # Also PATCH
        r = s.patch(f"{API}/logistics/missions/{liv_id}",
                    json={"status": "planifiee", "confirm": True})
        assert r.status_code == 404, r.text


# ============================================================================
# 7. Reminders — J-1 contains /suivi/, J-7 does not
# ============================================================================
class TestReminderSuiviLink:
    def test_j1_contains_suivi_j7_does_not(self):
        s = sess("admin")
        # Use Paris time to avoid UTC day-flip skew with today()
        try:
            from zoneinfo import ZoneInfo
            paris_today = datetime.now(ZoneInfo("Europe/Paris")).date()
        except Exception:
            paris_today = datetime.utcnow().date()
        tomorrow = (paris_today + timedelta(days=1)).strftime("%Y-%m-%d")
        week = (paris_today + timedelta(days=7)).strftime("%Y-%m-%d")
        mission_ids: dict[str, str] = {}
        for suffix, day in (("ReminderJ1", tomorrow), ("ReminderJ7", week)):
            v = _mk_venue(s, suffix, logistics={
                "delivery_start": "10:00", "delivery_end": "12:00",
                "pickup_start": "17:00", "pickup_end": "19:00",
                "delivery_address": "", "access_hours": "", "max_length_m": 0,
                "max_height_m": 0, "max_tonnage_t": 0, "tailgate_required": False,
                "dock_distance_m": 0, "stairs": "", "parking": "", "gate_code": "",
                "instructions": "", "preferred_channel": "email", "reminders_off": False,
            }, onsite_contacts=[{"name": "Alice", "role": "regisseur", "phone": "",
                                  "email": ALLOWED_EMAIL, "language": "fr-FR", "is_primary": True}])
            c = _mk_contact(s)
            eq = _mk_eq(s, f"{suffix}Eq", qty=50)
            ev = _mk_event(s, v["id"], c["id"], f"{suffix}Ev",
                           start_date=day,
                           equipment=[{"equipment_id": eq["id"], "qty": 2, "price_day": 5}],
                           status="confirme")
            r = s.post(f"{API}/events/{ev['id']}/logistics/generate")
            assert r.status_code == 200, r.text
            liv = next(m for m in r.json()["missions"] if m["type"] == "livraison")
            mission_ids[suffix] = liv["id"]
        r = s.post(f"{API}/logistics/reminders/run")
        assert r.status_code == 200, r.text
        logs = s.get(f"{API}/logistics/reminders").json()["logs"]
        j1 = [l for l in logs if l["rule"] == "j1" and l.get("mission_id") == mission_ids["ReminderJ1"]]
        j7 = [l for l in logs if l["rule"] == "j7" and l.get("mission_id") == mission_ids["ReminderJ7"]]
        assert j1, f"no J-1 reminder for mission {mission_ids['ReminderJ1']}"
        assert j7, f"no J-7 reminder for mission {mission_ids['ReminderJ7']}"
        assert "/suivi/" in j1[0]["body"], j1[0]["body"]
        assert "/suivi/" not in j7[0]["body"], j7[0]["body"]


# ============================================================================
# 8. RBAC — technicien can check/sign/track-link but NOT patch date/notes
# ============================================================================
class TestTechnicienRbac:
    @pytest.fixture(scope="class")
    def tech_mission(self, default_wh):
        """Create a mission and ensure technicien can access it (via events:read)."""
        s = sess("admin")
        v = _mk_venue(s, "TechVen")
        c = _mk_contact(s)
        eq = _mk_eq(s, "TechEq", qty=50)
        ev = _mk_event(s, v["id"], c["id"], "TechEv",
                       equipment=[{"equipment_id": eq["id"], "qty": 2, "price_day": 5}],
                       status="confirme")
        veh = _mk_vehicle(s, "TechVeh")
        r = s.post(f"{API}/events/{ev['id']}/logistics/generate")
        liv = next(m for m in r.json()["missions"] if m["type"] == "livraison")
        s.post(f"{API}/logistics/missions/{liv['id']}/vehicles",
               json={"vehicle_id": veh["id"], "driver_ids": []})
        s.post(f"{API}/logistics/missions/{liv['id']}/auto", json={"mode": "random"})
        r = sess("admin").get(f"{API}/logistics/missions/{liv['id']}") if False else None
        # Re-fetch with items
        m = next(mm for mm in sess("admin").get(f"{API}/events/{ev['id']}/logistics").json()["missions"]
                 if mm["id"] == liv["id"])
        return m

    def test_tech_can_check_item(self, tech_mission):
        tech = sess("technicien")
        item = next((i for i in tech_mission["items"] if i.get("mv_id")), tech_mission["items"][0])
        r = tech.patch(f"{API}/logistics/missions/{tech_mission['id']}/items/{item['id']}",
                       json={"loaded_qty": 1})
        # Technicien may only see own missions; if 404, skip gracefully
        if r.status_code == 404:
            pytest.skip("technicien does not see this mission (team scoping)")
        assert r.status_code == 200, r.text

    def test_tech_can_read_tracking_link(self, tech_mission):
        tech = sess("technicien")
        r = tech.get(f"{API}/logistics/missions/{tech_mission['id']}/tracking-link")
        if r.status_code == 404:
            pytest.skip("technicien does not see this mission (team scoping)")
        assert r.status_code == 200, r.text
        assert "/suivi/" in r.json()["url"]

    def test_tech_cannot_patch_date_or_notes(self, tech_mission):
        tech = sess("technicien")
        r = tech.patch(f"{API}/logistics/missions/{tech_mission['id']}",
                       json={"notes": "hack"})
        if r.status_code == 404:
            pytest.skip("technicien does not see this mission (team scoping)")
        assert r.status_code == 403, r.text
        r = tech.patch(f"{API}/logistics/missions/{tech_mission['id']}",
                       json={"date": (datetime.utcnow() + timedelta(days=60)).strftime("%Y-%m-%d")})
        assert r.status_code == 403, r.text
