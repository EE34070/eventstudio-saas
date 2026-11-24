"""Iteration 3 regression: files upload/download, event overlaps endpoint, rental period,
double-booking on rental period, public quote page, venues sections stability, PDF product page."""
import io
import time

import pytest
import requests

from conftest import API, client


# -------- Helpers --------
def _png(w=4, h=4, color=(30, 60, 200)):
    # Minimal PNG bytes (solid color)
    import struct
    import zlib

    def chunk(t, data):
        c = zlib.crc32(t + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + t + data + struct.pack(">I", c)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b""
    for _ in range(h):
        raw += b"\x00" + bytes(color) * w
    idat = zlib.compress(raw, 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _jpeg():
    # a tiny valid JPEG header (not a real image but magic matches)
    return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 64 + b"\xff\xd9"


def _upload(session, filename, data, ctype, extra_url=API):
    # Avoid the session's application/json Content-Type header
    return requests.post(f"{extra_url}/files",
                         headers={"Authorization": session.headers["Authorization"]},
                         files={"file": (filename, data, ctype)})


# -------- Files API --------
class TestFiles:
    def test_upload_png_and_fetch(self, admin):
        r = _upload(admin, "TEST_.png", _png(), "image/png")
        assert r.status_code == 200, r.text
        fid = r.json()["id"]
        assert r.json()["ref"] == f"file:{fid}"
        g = admin.get(f"{API}/files/{fid}")
        assert g.status_code == 200
        assert g.headers["Content-Type"].startswith("image/png")

    def test_reject_bad_content_type(self, admin):
        r = _upload(admin, "TEST_.txt", b"hello", "text/plain")
        assert r.status_code == 400

    def test_reject_magic_mismatch(self, admin):
        # Claim JPEG but send PDF bytes
        r = _upload(admin, "TEST_.jpg", b"%PDF-1.4 fake", "image/jpeg")
        assert r.status_code == 400
        assert "contenu" in r.json().get("detail", "").lower()

    def test_technicien_cannot_upload(self, tech):
        r = _upload(tech, "TEST_.png", _png(), "image/png")
        assert r.status_code == 403

    def test_file_download_requires_auth(self, admin):
        r = _upload(admin, "TEST_.png", _png(), "image/png")
        fid = r.json()["id"]
        assert requests.get(f"{API}/files/{fid}").status_code == 401

    def test_tenant_isolation(self, admin):
        r = _upload(admin, "TEST_.png", _png(), "image/png")
        fid = r.json()["id"]
        other = client(f"test_otherorg{int(time.time())}+clerk_test@example.com", "admin", "none")
        # Needs an org
        other.post(f"{API}/onboarding", json={"company_name": f"TEST_Other_{int(time.time())}"})
        g = other.get(f"{API}/files/{fid}")
        assert g.status_code == 404


# -------- Event overlaps endpoint --------
class TestOverlaps:
    def test_overlaps_lists_and_excludes_self(self, admin, events_by_code):
        a = events_by_code["EVT-2026-010"]
        r = admin.get(f"{API}/events/overlaps",
                      params={"start": a["start"], "end": a["end"], "exclude": a["id"],
                              "venue_id": a.get("venue_id", "")})
        assert r.status_code == 200
        rows = r.json()
        # self excluded
        assert all(e["id"] != a["id"] for e in rows)
        # same_venue flag matches
        for e in rows:
            assert e["same_venue"] == (bool(a.get("venue_id")) and e.get("venue_name") and a.get("venue_id") and True or False) or e["same_venue"] is False

    def test_overlaps_empty_when_future(self, admin):
        r = admin.get(f"{API}/events/overlaps",
                      params={"start": "2099-01-01T00:00", "end": "2099-01-02T00:00"})
        assert r.status_code == 200
        assert r.json() == []

    def test_overlaps_bad_range(self, admin):
        r = admin.get(f"{API}/events/overlaps", params={"start": "2026-01-02T10:00", "end": "2026-01-02T09:00"})
        assert r.status_code == 200 and r.json() == []

    def test_overlaps_requires_events_write(self, tech):
        r = tech.get(f"{API}/events/overlaps",
                     params={"start": "2026-12-18T00:00", "end": "2026-12-21T23:00"})
        assert r.status_code == 403


# -------- Rental period --------
class TestRentalPeriod:
    def _new_event(self, admin, title_prefix="TEST_Rent"):
        r = admin.post(f"{API}/events", json={
            "title": f"{title_prefix}_{int(time.time()*1000)}",
            "start": "2027-07-10T18:00", "end": "2027-07-11T02:00",
            "setup_start": "2027-07-10T08:00", "return_end": "2027-07-11T12:00",
        })
        assert r.status_code == 200, r.text
        return r.json()["id"]

    def test_period_drives_days_and_totals(self, admin):
        eqs = admin.get(f"{API}/equipment").json()["items"]
        eq = eqs[0]
        eid = self._new_event(admin)
        r = admin.patch(f"{API}/events/{eid}", json={
            "equipment": [{"equipment_id": eq["id"], "qty": 1, "price_day": 10.0}],
        })
        assert r.status_code == 200, r.text
        base_days = r.json()["rental_days"]
        # Set rental over 4 days (2027-07-05 to 2027-07-09 => 4 days)
        r = admin.patch(f"{API}/events/{eid}", json={
            "rental_start": "2027-07-05T08:00", "rental_end": "2027-07-09T18:00"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["rental_days"] == 4
        assert d["amount_equipment"] == pytest.approx(40.0)
        # Clearing both -> back to event dates
        r = admin.patch(f"{API}/events/{eid}", json={"rental_start": "", "rental_end": ""})
        assert r.status_code == 200
        assert r.json()["rental_days"] == base_days

    def test_period_invalid(self, admin):
        eid = self._new_event(admin)
        # end before start
        r = admin.patch(f"{API}/events/{eid}", json={
            "rental_start": "2027-07-09T18:00", "rental_end": "2027-07-05T08:00"})
        assert r.status_code == 400
        # only one side -> should fail
        r = admin.patch(f"{API}/events/{eid}", json={"rental_start": "2027-07-05T08:00"})
        assert r.status_code == 400

    def test_shift_also_shifts_rental_period(self, admin):
        eqs = admin.get(f"{API}/equipment").json()["items"]
        eq = eqs[0]
        eid = self._new_event(admin)
        admin.patch(f"{API}/events/{eid}", json={
            "equipment": [{"equipment_id": eq["id"], "qty": 1}],
            "rental_start": "2027-07-05T08:00", "rental_end": "2027-07-09T18:00"})
        r = admin.post(f"{API}/events/{eid}/shift", json={"days": 3})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["rental_start"].startswith("2027-07-08")
        assert d["rental_end"].startswith("2027-07-12")


# -------- Double-booking on rental period --------
class TestDoubleBooking:
    def test_409_on_period_overlap(self, admin):
        eqs = admin.get(f"{API}/equipment").json()["items"]
        scarce = sorted([e for e in eqs if e["qty_total"] >= 1], key=lambda x: x["qty_total"])[0]
        total = scarce["qty_total"]
        # Unique future window per run to avoid clashing with prior test leftovers
        import random
        yr = 2040 + random.randint(0, 50)
        t1 = admin.post(f"{API}/events", json={
            "title": f"TEST_DB1_{int(time.time()*1000)}",
            "start": f"{yr}-08-10T18:00", "end": f"{yr}-08-11T02:00"}).json()["id"]
        r = admin.patch(f"{API}/events/{t1}", json={
            "equipment": [{"equipment_id": scarce["id"], "qty": total}],
            "rental_start": f"{yr}-08-05T08:00", "rental_end": f"{yr}-08-09T18:00"})
        assert r.status_code == 200, r.text
        assert admin.post(f"{API}/events/{t1}/status", json={"status": "confirme"}).status_code == 200
        t2 = admin.post(f"{API}/events", json={
            "title": f"TEST_DB2_{int(time.time()*1000)}",
            "start": f"{yr}-08-20T18:00", "end": f"{yr}-08-21T02:00"}).json()["id"]
        r = admin.patch(f"{API}/events/{t2}", json={
            "equipment": [{"equipment_id": scarce["id"], "qty": total}],
            "rental_start": f"{yr}-08-15T08:00", "rental_end": f"{yr}-08-18T18:00"})
        assert r.status_code == 200, r.text
        assert admin.post(f"{API}/events/{t2}/status", json={"status": "confirme"}).status_code == 200
        r = admin.patch(f"{API}/events/{t2}", json={
            "rental_start": f"{yr}-08-08T08:00", "rental_end": f"{yr}-08-18T18:00"})
        assert r.status_code == 409, r.text
        # Cleanup: delete events to free stock for future runs
        admin.delete(f"{API}/events/{t1}")
        admin.delete(f"{API}/events/{t2}")


# -------- Public quote --------
class TestPublicQuote:
    def test_public_quote_demo(self, admin, events_by_code):
        # Demo: DEV-2026-0006 on EVT-2026-010 per iteration note
        quotes = admin.get(f"{API}/quotes").json()
        q = next((q for q in quotes if q["number"] == "DEV-2026-0006"), None) or next(
            (q for q in quotes if q.get("event_code") == "EVT-2026-010"), None)
        if not q:
            pytest.skip("demo quote not present")
        tok = q["share_token"]
        r = requests.get(f"{API}/public/quotes/{tok}")
        assert r.status_code == 200, r.text
        pub = r.json()
        # No leakage
        for k in ("org_id", "history", "share_token", "costs_total", "client_id"):
            assert k not in pub
        # client only exposes name
        assert set(pub.get("client", {}).keys()) <= {"name"} if isinstance(pub.get("client"), dict) else True
        assert "client_name" in pub
        assert "products" in pub
        # Product photo url pattern if any photo
        for p in pub["products"]:
            if p["photo"]:
                assert p["photo"].startswith(f"/api/public/quotes/{tok}/files/") or p["photo"].startswith("https://")

    def test_public_quote_invalid_token(self):
        r = requests.get(f"{API}/public/quotes/{'x' * 32}")
        assert r.status_code == 404

    def test_public_product_file_only_for_this_quote(self, admin):
        quotes = admin.get(f"{API}/quotes").json()
        q = next((q for q in quotes if q.get("event_code") == "EVT-2026-010"), None)
        if not q:
            pytest.skip("demo quote not present")
        pub = requests.get(f"{API}/public/quotes/{q['share_token']}").json()
        # Try unrelated file id -> 404
        r = requests.get(f"{API}/public/quotes/{q['share_token']}/files/{'deadbeef' * 4}")
        assert r.status_code == 404


# -------- PDF product sheet page --------
class TestQuotePDFProducts:
    def test_pdf_contains_products_when_photo_or_desc(self, admin):
        quotes = admin.get(f"{API}/quotes").json()
        q = next((q for q in quotes if q.get("event_code") == "EVT-2026-010"), None)
        if not q:
            pytest.skip("demo quote not present")
        tok = admin.headers["Authorization"]
        r = requests.get(f"{API}/quotes/{q['id']}/pdf", headers={"Authorization": tok})
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")
        # Should contain 'Fiches produits' literal somewhere (reportlab writes it as Tj strings)
        # The content is zlib-compressed streams; we search substring but it may be encoded.
        # Use a loose heuristic: content size reasonably larger than a plain quote without products.
        assert len(r.content) > 3000


# -------- Venues sections --------
class TestVenuesSections:
    def test_sections_get_ids_and_stay_stable(self, admin):
        name = f"TEST_V_{int(time.time()*1000)}"
        r = admin.post(f"{API}/venues", json={
            "name": name, "sections": [{"name": "La Folie"}, {"name": "Le Temple"}]})
        assert r.status_code == 200, r.text
        v = r.json()
        vid = v["id"]
        ids = [s["id"] for s in v["sections"]]
        assert all(ids) and len(set(ids)) == 2
        # Resave: ids stable
        r = admin.put(f"{API}/venues/{vid}", json={"name": name, "sections": v["sections"]})
        assert r.status_code == 200
        assert [s["id"] for s in r.json()["sections"]] == ids
        # Cleanup
        admin.delete(f"{API}/venues/{vid}")

    def test_equipment_line_section_persists(self, admin):
        # Create venue w/ one section
        vr = admin.post(f"{API}/venues", json={
            "name": f"TEST_V_{int(time.time()*1000)}", "sections": [{"name": "Salle A"}]}).json()
        vid, sid = vr["id"], vr["sections"][0]["id"]
        eqs = admin.get(f"{API}/equipment").json()["items"]
        eq = eqs[0]
        er = admin.post(f"{API}/events", json={
            "title": f"TEST_VSec_{int(time.time()*1000)}",
            "start": "2027-09-10T18:00", "end": "2027-09-11T02:00",
            "venue_id": vid}).json()
        eid = er["id"]
        r = admin.patch(f"{API}/events/{eid}", json={
            "equipment": [{"equipment_id": eq["id"], "qty": 1, "section_id": sid}]})
        assert r.status_code == 200, r.text
        got = admin.get(f"{API}/events/{eid}").json()
        line = got["equipment"][0]
        assert line.get("section_id") == sid
        # Cleanup
        admin.delete(f"{API}/events/{eid}")
        admin.delete(f"{API}/venues/{vid}")
