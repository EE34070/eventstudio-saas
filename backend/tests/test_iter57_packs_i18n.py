"""Iter 57 — Packs multilingues, versions de pack, révisions 1/2/3 des devis acceptés, propagation (QA)."""
import os
import uuid

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

from tests.test_iter54_dj_tab_roadmap import BASE, sess

load_dotenv("/app/backend/.env")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
TAG = "TEST_M57_" + uuid.uuid4().hex[:5]


def test_packs():
    a = sess("admin")
    ok = lambda r: (r.status_code < 300 or pytest.fail(f"{r.status_code} {r.text}"), r.json())[1]  # noqa: E731
    eq = lambda n, **k: ok(a.post(f"{BASE}/api/equipment", json={"name": f"{TAG} {n}", "ref": f"{TAG}-{n}", "category": "Son", "qty_total": 20, "price_day": 10, **k}))["id"]  # noqa: E731
    A, B_, mic, proj, tube = eq("enceinteA"), eq("enceinteB"), eq("micro"), eq("projecteur"), eq("tube")
    pack = eq("Formule", product_type="Pack", price_day=1000)
    C = lambda i, n, lab="", vis=True: {"equipment_id": i, "qty": n, "visible_client": vis, "client_label": lab}  # noqa: E731
    base = [C(A, 2, "", False), C(mic, 2, "micros sans fil"), C(tube, 5, "tubes lumineux")]
    setp = lambda comps: ok(a.put(f"{BASE}/api/equipment/{pack}/pack", json={"components": comps}))  # noqa: E731
    setp(base)
    ev = ok(a.post(f"{BASE}/api/events", json={"title": f"{TAG} ev", "start": "2028-06-10T16:00", "end": "2028-06-11T01:00", "language": "en-US"}))
    try:
        # traductions + « à revoir »
        t = ok(a.put(f"{BASE}/api/equipment/{pack}/translations", json={"lang": "en-US", "name": "Signature Package", "client_description": "Sound for 200 guests", "labels": {mic: "wireless microphones", tube: "light tubes"}}))
        en = next(x for x in t["languages"] if x["code"] == "en-US")
        assert en["state"] == "complete" and not en["stale"] and next(x for x in t["languages"] if x["code"] == "es-ES")["state"] == "absent"
        t = ok(a.put(f"{BASE}/api/equipment/{pack}/translations", json={"lang": "fr-FR", "client_description": "Sonorisation pour 200 personnes"}))
        assert next(x for x in t["languages"] if x["code"] == "en-US")["stale"]
        ok(a.put(f"{BASE}/api/equipment/{pack}/translations", json={"lang": "en-US", "name": "Signature Package", "client_description": "Sound for 200 guests", "labels": {mic: "wireless microphones", tube: "light tubes"}}))
        # devis en-US : pack et sous-lignes en anglais sur la page publique
        q = ok(a.post(f"{BASE}/api/events/{ev['id']}/quotes"))
        st = ok(a.get(f"{BASE}/api/quotes/{q['id']}/structure"))
        sec = st["blocks"][0]
        comps = [{"equipment_id": c["equipment_id"], "qty": 7 if c["equipment_id"] == tube else c["qty"], "base_qty": c["qty"], "visible_client": c["visible_client"], "client_label": c["client_label"], "name": "x", "service": False} for c in base]
        line = {"id": "p1", "parent_id": sec["id"], "type": "line", "label": f"{TAG} Formule", "qty": 1, "unit_price": 1000, "vat": 20, "equipment_id": pack, "kind": "catalog", "pack_components": comps, "pack_version": 1, "show_components": True}
        ok(a.put(f"{BASE}/api/quotes/{q['id']}/structure", json={"blocks": [sec, line], "dates": st["dates"]}))
        DB.quotes.update_one({"id": q["id"]}, {"$set": {"language": "en-US"}})
        assert ok(a.get(f"{BASE}/api/quotes/{q['id']}/translation-check"))["missing"] == []
        tk = ok(a.post(f"{BASE}/api/quotes/{q['id']}/share"))["token"]
        pub = requests.get(f"{BASE}/api/public/quotes/{tk}").text
        assert "Signature Package" in pub and "wireless microphones" in pub and "Equipment included" in pub and "enceinteA" not in pub
        DB.quotes.update_one({"id": q["id"]}, {"$set": {"language": "es-ES"}})
        chk = ok(a.get(f"{BASE}/api/quotes/{q['id']}/translation-check"))
        assert chk["missing"][0]["state"] == "absent" and "English" in chk["missing"][0]["fallback"]
        DB.quotes.update_one({"id": q["id"]}, {"$set": {"language": "en-US"}})
        ok(a.post(f"{BASE}/api/quotes/{q['id']}/status", json={"status": "accepte"}))
        snap = DB.quotes.find_one({"id": q["id"]})["signed_snapshot"]
        assert snap["total_ttc"] == 1200
        # niveau 1 : référence interne A -> B
        assert setp([C(B_, 2, "", False), base[1], base[2]])["version"] == 2
        lst = ok(a.get(f"{BASE}/api/equipment/{pack}/pack/quotes"))["quotes"]
        row = next(x for x in lst if x["id"] == q["id"])
        assert row["level"] == 1 and row["kept_adjustments"] == 1
        r = ok(a.post(f"{BASE}/api/equipment/{pack}/pack/apply", json={"quote_ids": [q["id"]]}))
        assert r[0]["level"] == 1
        d = DB.quotes.find_one({"id": q["id"]})
        cs = {c["equipment_id"]: c["qty"] for c in d["blocks"][1]["pack_components"]}
        assert B_ in cs and A not in cs and cs[tube] == 7 and d["signed_snapshot"] == snap and d["total_ttc"] == 1200
        assert not DB.quote_revisions.find_one({"quote_id": q["id"], "level": 2})
        # niveau 2 : projecteur visible offert -> révision V1.1, pas de signature
        setp([C(B_, 2, "", False), base[1], base[2], C(proj, 1, "projecteur")])
        r = ok(a.post(f"{BASE}/api/equipment/{pack}/pack/apply", json={"quote_ids": [q["id"]]}))
        assert r[0]["level"] == 2 and r[0]["revision"] == "V1.1"
        rev = DB.quote_revisions.find_one({"quote_id": q["id"], "level": 2})
        assert rev["pdf_file_ref"] and rev["language"] == "en-US" and rev["notification"]["sent"] is False and DB.quotes.find_one({"id": q["id"]})["status"] == "accepte"
        # niveau 3 : micro retiré -> non applicable en masse ; pas de reclassement vers moins strict
        setp([C(B_, 2, "", False), base[2], C(proj, 1, "projecteur")])
        r = ok(a.post(f"{BASE}/api/equipment/{pack}/pack/apply", json={"quote_ids": [q["id"]]}))
        assert r[0]["result"] == "level3"
        cur = DB.quotes.find_one({"id": q["id"]})["blocks"]
        new = [cur[0], {**cur[1], "unit_price": 900}]
        pv = ok(a.post(f"{BASE}/api/quotes/{q['id']}/revision", json={"blocks": new, "preview": True}))
        assert pv["level"] == 3
        blocked = ok(a.post(f"{BASE}/api/quotes/{q['id']}/revision", json={"blocks": new, "level": 2}))
        assert blocked["status"] == "blocked" and DB.quotes.find_one({"id": q["id"]})["total_ttc"] == 1200
        # avenant par code : la V1 reste la référence tant que le client n'a pas confirmé
        av = ok(a.post(f"{BASE}/api/quotes/{q['id']}/revision", json={"blocks": new, "mode": "avenant"}))
        assert av["status"] == "pending" and DB.quotes.find_one({"id": q["id"]})["total_ttc"] == 1200
        tok = ok(a.post(f"{BASE}/api/quotes/{q['id']}/share"))["token"]
        pa = requests.get(f"{BASE}/api/public/quotes/{tok}/amendment").json()
        assert pa["total_ttc_after"] == 1080 and "interne" not in str(pa)
        assert requests.post(f"{BASE}/api/public/quotes/{tok}/amendment/request").status_code == 200
        assert requests.post(f"{BASE}/api/public/quotes/{tok}/amendment/confirm", json={"code": "000000"}).status_code == 400
        import hashlib
        rv = DB.quote_revisions.find_one({"id": av["id"]})
        code = next(f"{n:06d}" for n in range(10 ** 6) if hashlib.sha256(f"{rv['otp_salt']}:{n:06d}".encode()).hexdigest() == rv["otp_hash"])
        assert requests.post(f"{BASE}/api/public/quotes/{tok}/amendment/confirm", json={"code": code}).status_code == 200
        assert DB.quotes.find_one({"id": q["id"]})["total_ttc"] == 1080 and DB.quote_revisions.find_one({"id": av["id"]})["status"] == "accepted"
        # droits
        c = sess("commercial")
        assert c.post(f"{BASE}/api/equipment/{pack}/pack/apply", json={"quote_ids": [q["id"]]}).status_code == 403
        assert sess("technicien").get(f"{BASE}/api/quotes/{q['id']}/revisions").status_code in (401, 403)
    finally:
        a.delete(f"{BASE}/api/events/{ev['id']}")
        DB.quotes.update_many({"event_id": ev["id"]}, {"$set": {"active": False, "status": "remplace"}})
        DB.equipment.delete_many({"ref": {"$regex": f"^{TAG}"}})
