"""Iter 61 — IS estimé, acomptes, solde, modulation, TVA prévisionnelle, CFE, calendrier, provision (QA)."""
import os
from datetime import date

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv("/app/backend/.env")
from routes_tax import acompte_dates, compute_is, fiscal_year  # noqa: E402
from tests.test_iter54_dj_tab_roadmap import BASE, sess  # noqa: E402

DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
P = {"taux_reduit_pct": 15, "plafond_taux_reduit": 42500, "taux_normal_pct": 25}


def test_rules():
    r = compute_is(60000, True, P)
    assert r["is_reduit"] == 6375 and r["is_normal"] == 4375 and r["is_total"] == 10750 and r["effective_rate"] == 17.9
    assert compute_is(60000, False, P)["is_total"] == 15000 and compute_is(-5000, True, P)["is_total"] == 0 and compute_is(60000, True, P, 750)["is_total"] == 10000
    assert acompte_dates(date(2026, 12, 31)) == ["2026-03-15", "2026-06-15", "2026-09-15", "2026-12-15"]
    assert acompte_dates(date(2026, 6, 30)) == ["2025-09-15", "2025-12-15", "2026-03-15", "2026-06-15"]
    assert acompte_dates(date(2026, 9, 30)) == ["2025-12-15", "2026-03-15", "2026-06-15", "2026-09-15"]
    assert fiscal_year("06-30", "2026-11-24") == ("2026-07-01", "2027-06-30") and fiscal_year("12-31", "2026-11-24") == ("2026-01-01", "2026-12-31")


def test_api():
    a = sess("admin")
    ok = lambda r: (r.status_code < 300 or pytest.fail(f"{r.status_code} {r.text}"), r.json())[1]  # noqa: E731
    org = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
    keep = {c: list(DB[c].find({"org_id": org})) for c in ("tax_inputs", "tax_settings", "tax_dues")}
    sub = DB.subscriptions.find_one({"org_id": org, "deleted_at": None})
    put = lambda **k: ok(a.put(f"{BASE}/api/finance/tax/inputs", json={"is_n1": 12000, **k}))  # noqa: E731
    ev = None
    try:
        s = ok(a.get(f"{BASE}/api/finance/tax-settings"))["settings"]
        ok(a.put(f"{BASE}/api/finance/tax-settings", json={**s, "regime": "is", "closing": "12-31", "tva_regime": "reel_mensuel", "tva_exigibilite": "encaissements", "capital_libere": True, "detention_75": True, "ca_sous_seuil": True}))
        d = put(use_deficits=False)
        y = d["fiscal_year"]["end"][:4]
        assert [x["due_date"] for x in d["acomptes"]] == [f"{y}-03-15", f"{y}-06-15", f"{y}-09-15", f"{y}-12-15"] and all(x["amount"] == 3000 for x in d["acomptes"]) and d["acomptes_total"] == 12000
        assert any(x["key"].startswith("is-solde") for x in d["calendar"]) and d["eligible"]
        # résultat fiscal piloté à 60 000 € -> 10 750 €, 17,9 %
        base = d["estimate"]["accounting_result"]
        L = [{"label": "Ajustement test", "amount": abs(60000 - base), "kind": "produit" if base < 60000 else "charge"}]
        d = put(use_deficits=False, lines=L)
        assert d["estimate"]["taxable_result"] == 60000 and d["estimate"]["is_total"] == 10750 and d["estimate"]["effective_rate"] == 17.9 and d["solde"] == -1250
        assert d["modulation"]["possible"] and d["modulation"]["saving"] > 0 and "majoration" in d["modulation"]["warning"]
        # abonnement personnel réintégré
        if sub:
            DB.subscriptions.update_one({"id": sub["id"]}, {"$set": {"personal_non_deductible": True, "active": True}})
            d2 = ok(a.get(f"{BASE}/api/finance/tax"))
            assert d2["estimate"]["reintegrations"] and d2["estimate"]["taxable_result"] == r2(60000 + d2["estimate"]["reintegrations"][0]["amount"])
            DB.subscriptions.update_one({"id": sub["id"]}, {"$set": {"personal_non_deductible": False, "active": sub.get("active", True)}})
        # dispense sous le seuil, CFE, pointage
        d = put(use_deficits=False, lines=L, is_n1=2000, cfe_amount=4000)
        assert d["reference"]["exempt"] and d["acomptes_total"] == 0 and d["solde"] == 10750
        cfe = [x for x in d["calendar"] if x["tax"] == "CFE"]
        assert cfe and all(x["amount"] == 2000 for x in cfe) and d["provision"]["by_tax"]["CFE"] >= 2000 and d["provision"]["monthly"] > 0
        k = cfe[0]["key"]
        d = ok(a.put(f"{BASE}/api/finance/tax/dues/{k}", json={"paid": True, "final_amount": 2100}))
        row = next(x for x in d["calendar"] if x["key"] == k)
        assert row["status"] == "paid" and row["amount"] == 2100 and row["final"]
        # devis signé de 10 000 € HT : IS et TVA suivent
        before = ok(a.get(f"{BASE}/api/finance/tax"))
        ev = ok(a.post(f"{BASE}/api/events", json={"title": "TEST_M61 ev", "start": f"{y}-12-28T15:00", "end": f"{y}-12-28T23:00"}))
        q = ok(a.post(f"{BASE}/api/events/{ev['id']}/quotes"))
        DB.quotes.update_one({"id": q["id"]}, {"$set": {"lines": [{"label": "Prestation", "qty": 1, "unit_price": 10000, "vat": 20}], "blocks": [], "total_ht": 10000, "total_vat": 2000, "total_ttc": 12000, "vat_breakdown": [{"rate": 20, "ht": 10000, "vat": 2000}]}})
        ok(a.post(f"{BASE}/api/quotes/{q['id']}/status", json={"status": "accepte"}))
        after = ok(a.get(f"{BASE}/api/finance/tax"))
        assert after["estimate"]["products"][0]["amount"] == before["estimate"]["products"][0]["amount"] + 10000 and after["estimate"]["is_total"] == before["estimate"]["is_total"] + 2500
        col = lambda v: sum(t["collected"] for t in v["tva"])  # noqa: E731
        assert abs(col(after) - col(before) - 2000) < 1 and after["provision"]["total_12_months"] > before["provision"]["total_12_months"]
        t = sess("technicien")
        assert t.get(f"{BASE}/api/finance/tax").status_code in (401, 403) and sess("commercial").put(f"{BASE}/api/finance/tax/inputs", json={}).status_code in (401, 403)
    finally:
        if ev:
            a.delete(f"{BASE}/api/events/{ev['id']}")
            DB.quotes.update_many({"event_id": ev["id"]}, {"$set": {"active": False, "status": "remplace"}})
            DB.invoices.delete_many({"event_id": ev["id"]})
        for c, docs in keep.items():
            DB[c].delete_many({"org_id": org})
            if docs:
                DB[c].insert_many(docs)
        DB.tax_estimates.delete_many({"org_id": org})


r2 = lambda x: round(x + 1e-9, 2)  # noqa: E731
