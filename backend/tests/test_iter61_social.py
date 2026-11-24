"""Iter 61 — Pôle Social (QA uniquement, données fictives, aucun e-mail)."""
import io
import os
import uuid
from datetime import date, timedelta

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

from tests.test_iter54_dj_tab_roadmap import BASE, sess

load_dotenv("/app/backend/.env")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
TAG = "TEST_M61_" + uuid.uuid4().hex[:5]
COLLS = ["employee_files", "employment_contracts", "pay_revisions", "pay_variables", "payroll_lines", "time_entries", "absences", "pay_periods", "social_managers", "social_scenarios", "social_dues", "social_changes", "social_notifications", "headcount_budgets", "social_settings"]


def test_social():
    a = sess("admin")
    ok = lambda r: (r.status_code < 300 or pytest.fail(f"{r.status_code} {r.text[:600]}"), r.json())[1]  # noqa: E731
    org = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
    O = {"org_id": org}
    for c in COLLS:
        DB[c].delete_many(O)
    DB.team.delete_many({**O, "name": {"$regex": "^(TEST_M61|Scénario)"}})
    Y, today = date.today().year + 1, date.today()
    U = f"{BASE}/api/social"
    made = {"ev": []}
    try:
        # 1. CDI 2 000 € au 1er janvier, avenant 2 200 € au 1er juin
        e1 = ok(a.post(f"{U}/employees", json={"name": f"{TAG} CDI"}))["team_id"]
        c1 = ok(a.post(f"{U}/contracts", json={"team_id": e1, "type": "cdi", "start": f"{Y}-01-01", "base_pay": 2000, "dpae_done_at": f"{Y - 1}-12-20"}))
        ok(a.post(f"{U}/contracts/{c1['id']}/amend", json={"effective_from": f"{Y}-06-01", "base_pay": 2200, "reason": "hausse"}))
        assert a.post(f"{U}/contracts", json={"team_id": e1, "type": "cdd", "start": f"{Y}-01-01", "end": f"{Y}-03-01", "base_pay": 1}).status_code == 400
        f = ok(a.get(f"{U}/forecast?start={Y}-01"))
        p = next(x for x in f["people"] if x["team_id"] == e1)
        assert p["gross"][f"{Y}-01"] == 2000 and p["gross"][f"{Y}-06"] == 2200 and p["cost"][f"{Y}-01"] == 2900 and p["cost"][f"{Y}-06"] == 3190
        assert any(x["date"] == f"{Y}-01-31" and x["kind"] == "nets" for x in f["flows"]) and any(x["date"] == f"{Y}-02-15" and x["kind"] == "cotisations" for x in f["flows"])
        assert ok(a.get(f"{U}/register"))["rows"] and a.get(f"{U}/register?format=pdf").content[:4] == b"%PDF" and a.get(f"{U}/contracts/{c1['id']}/pdf").content[:4] == b"%PDF"
        # 2. CDD finissant dans 12 jours
        e2 = ok(a.post(f"{U}/employees", json={"name": f"{TAG} CDD"}))["team_id"]
        end = (today + timedelta(days=12)).isoformat()
        ok(a.post(f"{U}/contracts", json={"team_id": e2, "type": "cdd", "cdd_reason": "Surcroît", "start": (today - timedelta(days=60)).isoformat(), "end": end, "base_pay": 1900, "signed_at": "2020-01-01", "dpae_done_at": "2020-01-01"}))
        assert any(x["kind"] == "cdd_end" and "renouveler" in x["label"] for x in ok(a.get(f"{U}/employees/{e2}"))["alerts"])
        f2 = ok(a.get(f"{U}/forecast"))
        p2 = next(x for x in f2["people"] if x["team_id"] == e2)
        after = f"{(today + timedelta(days=75)).isoformat()[:7]}"
        assert after not in p2["gross"] or p2["gross"][after] == 0
        assert ok(a.get(f"{BASE}/api/menu"))["badges"]["social"] >= 1
        # 3. intermittent : 11 h validées dans Staff
        ev = ok(a.post(f"{BASE}/api/events", json={"title": f"{TAG} ev", "start": f"{Y}-03-10T15:00", "end": f"{Y}-03-11T02:00"}))
        made["ev"].append(ev["id"])
        pid, mid = "p" + TAG, "m" + TAG
        DB.provider_profiles.insert_one({**O, "id": pid, "name": f"{TAG} Tech", "employment_status": "intermittent", "contact_id": "c" + TAG})
        DB.missions.insert_one({**O, "id": mid, "provider_id": pid, "provider_name": f"{TAG} Tech", "event_id": ev["id"], "date": f"{Y}-03-10", "category_key": "technicien", "rate_type": "hourly", "agreed_rate": 20, "total_ht": 220, "status": "confirmed", "employment_status": "intermittent"})
        DB.timesheets.insert_one({**O, "id": "t" + TAG, "mission_id": mid, "provider_id": pid, "provider_name": f"{TAG} Tech", "event_id": ev["id"], "date": f"{Y}-03-10", "hours": 11, "night_hours": 0, "amount_base": 220, "amount_overtime": 0, "status": "validated", "employment_status": "intermittent"})
        r = ok(a.post(f"{U}/contracts/from-missions", json={"mission_ids": [mid]}))
        e3 = r["team_id"]
        assert r["contracts"][0]["type"] == "cddu" and a.post(f"{U}/contracts/from-missions", json={"mission_ids": [mid]}).status_code == 409
        t = next(x for x in ok(a.get(f"{U}/time?period={Y}-03"))["rows"] if x["team_id"] == e3)
        assert t["total"] == 11 and t["rows"][0]["source"] == "timesheet"
        fin = ok(a.get(f"{BASE}/api/events/{ev['id']}/finance"))
        soc = [c for c in fin["commitments"] if c.get("source") == "social"]
        assert soc and soc[0]["amount_ht"] == 143.0 and any(c["key"] == "staff" for c in fin["charges"]["categories"])
        ok(a.post(f"{U}/variables", json={"team_id": e1, "period": f"{Y}-03", "kind": "prime_evenement", "amount": 100, "event_id": ev["id"]}))
        assert any(c["amount_ht"] == 145.0 for c in ok(a.get(f"{BASE}/api/events/{ev['id']}/finance"))["commitments"] if c.get("source") == "social")
        assert a.post(f"{U}/absences", json={"team_id": e3, "type": "cp", "start": f"{Y}-03-02", "end": f"{Y}-03-03"}).status_code == 400
        # 4. congés depuis l'espace salarié
        e4 = ok(a.post(f"{U}/employees", json={"name": f"{TAG} Leave"}))["team_id"]
        c4 = ok(a.post(f"{U}/contracts", json={"team_id": e4, "type": "cdi", "start": f"{Y - 3}-01-01", "base_pay": 2000, "signed_at": "2020-01-01", "dpae_done_at": "2020-01-01"}))
        tech = sess("technicien")
        DB.users.update_one({"email": "qa_technicien+clerk_test@example.com"}, {"$set": {"team_id": e4}})
        d1 = today + timedelta(days=(7 - today.weekday()) + 14)
        ev2 = ok(a.post(f"{BASE}/api/events", json={"title": f"{TAG} ev2", "start": f"{(d1 + timedelta(days=2)).isoformat()}T15:00", "end": f"{(d1 + timedelta(days=2)).isoformat()}T23:00"}))
        made["ev"].append(ev2["id"])
        DB.events.update_one({"id": ev2["id"]}, {"$set": {"team": [{"member_id": e4, "role": "tech"}]}})
        mine = ok(tech.get(f"{BASE}/api/my-social"))
        assert mine["leave"]["remaining"] > 20 and "coef" not in mine and "employer_cost_total" not in str(mine)
        rq = ok(tech.post(f"{BASE}/api/my-social/absences", json={"type": "cp", "start": d1.isoformat(), "end": (d1 + timedelta(days=4)).isoformat()}))
        assert rq["absence"]["days"] == 5 and rq["balance_after"] == round(mine["leave"]["remaining"] - 5, 2)
        ap = ok(a.post(f"{U}/absences/{rq['absence']['id']}/approve", json={}))
        assert ap["status"] == "approved" and ap["overlaps"] and ap["overlaps"][0]["id"] == ev2["id"]
        assert "validée" in ok(tech.get(f"{BASE}/api/my-social"))["notifications"][0]["text"]
        assert ok(a.get(f"{U}/absences"))["provision_total"] > 0
        # 10. accès croisés
        assert tech.get(f"{U}/employees").status_code == 403 and tech.get(f"{U}/pay").status_code == 403 and tech.get(f"{U}/employees/{e1}").status_code == 403
        assert tech.get(f"{BASE}/api/my-social/contracts/{c1['id']}/pdf").status_code == 404 and tech.get(f"{BASE}/api/my-social/contracts/{c4['id']}/pdf").status_code == 200
        ab1 = ok(a.post(f"{U}/absences", json={"team_id": e1, "type": "maladie", "start": f"{Y}-02-02", "end": f"{Y}-02-04"}))
        assert tech.delete(f"{BASE}/api/my-social/absences/{ab1['id']}").status_code == 404
        fid = ok(a.post(f"{U}/files", files={"file": ("b.pdf", b"%PDF-1.4 test", "application/pdf")}, headers={"Content-Type": None}))["file_id"]
        assert tech.get(f"{BASE}/api/files/{fid}").status_code == 404 and tech.get(f"{BASE}/api/my-social/files/{fid}").status_code == 404 and a.get(f"{BASE}/api/files/{fid}").status_code == 200
        ok(a.put(f"{U}/employees/{e1}", json={"ssn": "1 85 05 30 189 001 22", "iban": "FR76 3000 1000 0000 0000 0000 123"}))
        raw = DB.employee_files.find_one({"team_id": e1})
        assert "185053018900122" not in str(raw) and ok(a.get(f"{U}/employees/{e1}/secrets"))["ssn"] == "185053018900122" and "ssn_encrypted" not in str(ok(a.get(f"{U}/employees/{e1}")))
        cpt = sess("comptable")
        assert cpt.get(f"{U}/employees").status_code == 200 and cpt.post(f"{U}/employees", json={"name": "x"}).status_code == 403
        DB.users.update_one({"email": "qa_technicien+clerk_test@example.com"}, {"$set": {"team_id": None}})
        assert tech.get(f"{BASE}/api/my-social").status_code == 404
        # 5. clôture des variables → pré-paie + brouillon, sans envoi
        per = f"{Y}-03"
        pr = ok(a.post(f"{U}/periods/{per}/close"))
        assert pr["status"] == "closed" and pr["draft"]["status"] == "draft" and {e1, e3} <= {r["team_id"] for r in pr["prepay"]}
        assert a.get(f"{U}/periods/{per}/prepay?format=csv").status_code == 200 and a.get(f"{U}/periods/{per}/prepay?format=pdf").content[:4] == b"%PDF"
        assert a.post(f"{U}/variables", json={"team_id": e1, "period": per, "kind": "acompte", "amount": 10}).status_code == 409
        assert a.post(f"{U}/periods/{per}/send-draft").status_code == 400
        # 6. import des bulletins : e1 seulement, coût réel très supérieur au prévu
        csvb = f"Nom;Brut;Cotisations salariales;Cotisations patronales;Net à payer;Net imposable;PAS;Heures;Coût employeur\n{TAG} CDI;2100;460;1260;1640;1700;50;151,67;3360\n".encode()
        im = ok(a.post(f"{U}/payroll/import", data={"period": per}, files={"file": ("j.csv", csvb, "text/csv")}, headers={"Content-Type": None}))
        line = next(l for l in im["lines"] if l["team_id"] == e1)
        assert line["status"] == "draft" and any("bulletin manquant" in c["text"] and "Tech" in c["text"] for c in im["controls"]) and any("coût réel" in c["text"] for c in im["controls"])
        v = ok(a.post(f"{U}/payroll/lines/{line['id']}/validate"))
        assert v["coef"] == {"value": 1.6, "source": "réel"}
        fr = ok(a.get(f"{U}/forecast?start={Y}-01"))
        pp = next(x for x in fr["people"] if x["team_id"] == e1)
        assert pp["cost"][per] == 3360 and pp["source"][per] == "réel" and pp["cost"][f"{Y}-04"] == 3200
        assert any(x["date"] == f"{Y}-04-15" and x["kind"] == "pas" and x["amount"] == 50 for x in fr["flows"])
        dues = ok(a.get(f"{U}/dues"))["rows"]
        k = next(x for x in dues if x["key"] == f"urssaf-{per}")
        assert any(x["key"] == f"urssaf-{per}" and x["paid_at"] for x in ok(a.put(f"{U}/dues/{k['key']}", json={"paid_at": f"{Y}-04-15", "paid_amount": k["amount"]}))["rows"])
        # 7. gérants
        for n in ("Florian TEST", "Damien TEST"):
            ok(a.post(f"{U}/managers", json={"name": f"{TAG} {n}", "pay": [{"amount": 3000, "start": f"{Y}-01-01"}], "calls": [{"year": Y, "due_date": f"{Y}-05-05", "amount": 4000}]}))
        mg = ok(a.get(f"{U}/managers"))["rows"]
        fm = ok(a.get(f"{U}/forecast?start={Y}-01&months=36"))
        row = next(r for r in fm["rows"] if r["month"] == f"{Y}-05")
        assert len(mg) == 2 and row["mgr_pay"] == 6000 and row["mgr_charge"] == 2700 and row["mgr_cash"] == 8000 and len(fm["rows"]) == 36
        reg = next(r for r in fm["rows"] if r["month"] == f"{Y + 1}-10")
        assert reg["mgr_cash"] == 2 * (36000 * 0.45 - 4000)
        assert ok(a.get(f"{U}/managers/simulate?budget=50000"))["dividends"]["net"] > 0
        # 9. prévisionnel 3 ans et dossier banquier
        fv = ok(a.post(f"{BASE}/api/finance/forecasts", json={"name": TAG, "start_year": Y, "mode": "blank"}))
        made["fv"] = fv["id"]
        full = ok(a.get(f"{BASE}/api/finance/forecasts/{fv['id']}"))
        pnl = {r[0]: r for r in next(t for t in full["results"]["tables"] if t["key"] == "pnl")["rows"]}
        assert full["results"]["personnel_source"] == "Pôle Social" and pnl["Personnel"][1] > 30000 and pnl["Gérants (rémunération et cotisations)"][1] == 104400
        assert a.get(f"{BASE}/api/finance/forecasts/{fv['id']}/export?format=pdf").content[:4] == b"%PDF"
        tax = ok(a.get(f"{BASE}/api/finance/tax"))
        assert any("Pôle Social" in c["label"] for c in tax["estimate"]["charges"])
        # 8. scénario : rien n'est modifié
        n0 = DB.employment_contracts.count_documents(O)
        s = ok(a.post(f"{U}/scenarios", json={"name": "CDI technicien", "kind": "hire", "date": f"{Y}-03-01", "gross": 2300, "job": "Technicien"}))["rows"][0]
        res = s["results"]
        assert res["delta_cost"] > 0 and res["is_with"] <= res["is_without"] and res["cash_low_with"] < res["cash_low_without"] and DB.employment_contracts.count_documents(O) == n0
        ok(a.post(f"{U}/scenarios", json={"name": "+5 %", "kind": "raise_pct", "date": f"{Y}-07-01", "pct": 5}))
        ok(a.post(f"{U}/scenarios", json={"name": "gérants", "kind": "manager_raise", "date": f"{Y}-07-01", "pct": 10}))
        # divers
        assert ok(a.get(f"{U}/dashboard"))["headcount"]["total"] >= 2 and ok(a.get(f"{U}/pay"))["rows"] and ok(a.get(f"{U}/budget/{Y}"))["rows"][2]["real"]
        assert ok(a.get(f"{U}/simulate?amount=2000"))["cost"] == 2900
        st = ok(a.get(f"{U}/settings"))
        ok(a.put(f"{U}/settings", json={"valid_from": f"{Y}-01-01", "params": {**st["current"], "coef": {**st["current"]["coef"], "cdi": 1.5}}}))
        assert a.put(f"{U}/settings", json={"valid_from": f"{Y}-01-01", "params": {"coef": {"cdi": "x"}}}).status_code == 400
        # 11. aucune écriture comptable
        assert not [c for c in DB.list_collection_names() if "journal" in c or "ledger" in c or "accounting_entr" in c]
    finally:
        DB.users.update_one({"email": "qa_technicien+clerk_test@example.com"}, {"$set": {"team_id": None}})
        for c in COLLS:
            DB[c].delete_many(O)
        for c, k in (("provider_profiles", "p"), ("missions", "m"), ("timesheets", "t")):
            DB[c].delete_many({**O, "id": k + TAG})
        DB.team.delete_many({**O, "name": {"$regex": "^(TEST_M61|Scénario)"}})
        DB.events.delete_many({**O, "id": {"$in": made["ev"]}})
        DB.forecast_versions.delete_many({**O, "name": {"$regex": "^TEST_M61"}})
