"""Iter 59 — États financiers : FEC, balance, brouillon liasse, contrôles, verrouillage, barèmes (QA)."""
import io
import os

import pytest
import requests
from dotenv import load_dotenv
from pymongo import MongoClient

from tests.test_iter54_dj_tab_roadmap import BASE, sess

load_dotenv("/app/backend/.env")
DB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
HEAD = "JournalCode\tJournalLib\tEcritureNum\tEcritureDate\tCompteNum\tCompteLib\tCompAuxNum\tCompAuxLib\tPieceRef\tPieceDate\tEcritureLib\tDebit\tCredit\tEcritureLet\tDateLet\tValidDate\tMontantdevise\tIdevise"


def fec(rows, year):
    L = lambda i, acc, lib, d, c, dt: f"OD\tOD\t{i}\t{dt}\t{acc}\t{lib}\t\t\tP{i}\t{dt}\tx\t{d:.2f}\t{c:.2f}\t\t\t{dt}\t\t".replace(".", ",")  # noqa: E731
    return (HEAD + "\n" + "\n".join(L(i, a, l, d, c, f"{year}0101" if a[0] in "12345" and i < 5 else f"{year}0630") for i, (a, l, d, c) in enumerate(rows))).encode("utf-8")


ROWS = lambda k: [("512000", "Banque", 1000, 0), ("101000", "Capital", 0, 1000), ("512000", "Banque", 20000, 0), ("164000", "Emprunt", 0, 20000), ("218300", "Matériel", 20000, 0), ("512000", "Banque", 0, 20000),  # noqa: E731
                  ("411000", "Clients", 120000 * k, 0), ("706000", "Prestations", 0, 100000 * k), ("445710", "TVA collectée", 0, 20000 * k), ("604000", "Achats prestations", 30000 * k, 0), ("622600", "Honoraires", 10000 * k, 0),
                  ("401000", "Fournisseurs", 0, 40000 * k), ("641000", "Salaires", 20000 * k, 0), ("421000", "Personnel", 0, 20000 * k), ("695000", "IS", 5000 * k, 0), ("444000", "Etat IS", 0, 5000 * k),
                  ("512000", "Banque", 70000 * k, 0), ("411000", "Clients", 0, 70000 * k), ("401000", "Fournisseurs", 30000 * k, 0), ("512000", "Banque", 0, 30000 * k), ("421000", "Personnel", 20000 * k, 0), ("512000", "Banque", 0, 20000 * k)]


def test_statements():
    a = sess("admin")
    ok = lambda r: (r.status_code < 300 or pytest.fail(f"{r.status_code} {r.text}"), r.json())[1]  # noqa: E731
    org = DB.orgs.find_one({"slug": "qa-sandbox"})["id"]
    DB.fiscal_years.delete_many({"org_id": org, "end": {"$in": ["2019-12-31", "2020-12-31", "2021-12-31"]}})
    post = lambda kind, name, data, **form: a.post(f"{BASE}/api/finance/statements/import/{kind}", files={"file": (name, io.BytesIO(data), "text/plain")}, data=form, headers={"Content-Type": None})  # noqa: E731
    try:
        # barèmes et paramètres
        t = ok(a.get(f"{BASE}/api/finance/tax-settings"))
        is_ = next(r for r in t["rates"] if r["tax"] == "is")
        assert is_["params"]["plafond_taux_reduit"] == 42500 and t["reduced_rate_eligible"] is False
        t = ok(a.put(f"{BASE}/api/finance/tax-settings", json={**t["settings"], "capital_libere": True, "detention_75": True, "ca_sous_seuil": True}))
        assert t["reduced_rate_eligible"] is True
        ok(a.put(f"{BASE}/api/finance/tax-settings", json={**t["settings"], "capital_libere": False}))
        # FEC déséquilibré refusé
        bad = ROWS(1) + [("606000", "Fournitures", 500, 0)]
        r = post("fec", "123456789FEC20191231.txt", fec(bad, 2019))
        assert r.status_code == 400 and "déséquilibré" in r.json()["detail"]
        # FEC équilibré : 2019 puis 2020
        for y, k in ((2019, 1), (2020, 2)):
            d = ok(post("fec", f"123456789FEC{y}1231.txt", fec(ROWS(k), y)))
            assert d["status"] == "draft" and d["end"] == f"{y}-12-31" and d["values"]["total_actif"] == d["values"]["total_passif"] and not [c for c in d["controls"] if c["level"] == "block"]
            v = d["values"]
            assert v["ca"] == 100000 * k and v["charges_externes"] == 10000 * k and v["va"] == 60000 * k and v["ebe"] == 40000 * k and v["net"] == 35000 * k and v["taux_marge"] == 70.0
            ok(a.post(f"{BASE}/api/finance/statements/{d['id']}/validate", json={}))
        s = ok(a.get(f"{BASE}/api/finance/statements"))
        ys = {y["end"]: y for y in s["years"]}
        assert ys["2019-12-31"]["status"] == "locked" and ys["2020-12-31"]["values"]["capitaux_propres"] == 71000
        assert any("N-1" in c["text"] for c in ys["2020-12-31"]["controls"]) and len(ys["2020-12-31"]["reading"]) >= 3  # résultat 2019 non reporté dans ce FEC d'essai
        assert a.put(f"{BASE}/api/finance/statements/{ys['2019-12-31']['id']}", json={"start": "2019-01-01", "end": "2019-12-31", "headings": {}}).status_code == 404  # verrouillé
        # table de correspondance : 6226 -> autres charges, sur un brouillon
        d = ok(post("fec", "123456789FEC20191231.txt", fec(ROWS(1), 2019)))
        assert d["version"] == 2
        ok(a.put(f"{BASE}/api/finance/heading-map", json={"prefix": "6226", "heading": "autres_charges"}))
        d2 = next(x for x in ok(a.get(f"{BASE}/api/finance/statements"))["drafts"] if x["id"] == d["id"])
        assert d2["values"]["charges_externes"] == 0 and d2["values"]["autres_charges"] == 10000 and d2["values"]["net"] == 35000
        ok(a.put(f"{BASE}/api/finance/heading-map", json={"prefix": "6226", "heading": ""}))
        ok(a.delete(f"{BASE}/api/finance/statements/{d['id']}"))
        # balance CSV
        csvb = "Compte;Libellé;Débit;Crédit\n" + "\n".join(f"{x};{l};{d_};{c}" for x, l, d_, c in ROWS(3))
        b = ok(post("balance", "balance.csv", csvb.encode(), start="2021-01-01", end="2021-12-31"))
        assert b["source"] == "balance" and b["values"]["ca"] == 300000
        ok(a.delete(f"{BASE}/api/finance/statements/{b['id']}"))
        # brouillon « liasse » : déséquilibre et marge > 100 % bloquent la validation
        DB.fiscal_years.insert_one({"id": "t59-liasse", "org_id": org, "start": "2021-01-01", "end": "2021-12-31", "status": "draft", "source": "liasse", "version": 1, "created_at": "2026-01-01", "confidence": {"clients": 0.5},
                                    "headings": {"clients": 50000, "capital": 1000, "production_vendue": 10000, "achats_mp": -5000, "resultat_bilan": 15000}})
        r = a.post(f"{BASE}/api/finance/statements/t59-liasse/validate", json={})
        assert r.status_code == 400 and len(r.json()["detail"]["blocks"]) >= 3  # déséquilibre, marge 150 %, champ douteux
        d = ok(a.put(f"{BASE}/api/finance/statements/t59-liasse", json={"start": "2021-01-01", "end": "2021-12-31", "headings": {"achats_mp": 4000, "resultat_bilan": 6000, "clients": 7000}}))
        assert not [c for c in d["controls"] if c["level"] == "block"] and d["confidence"]["clients"] == 1.0
        assert ok(a.post(f"{BASE}/api/finance/statements/t59-liasse/validate", json={}))["status"] == "locked"
        # exports et droits
        x = a.get(f"{BASE}/api/finance/statements/export.xlsx"); p = a.get(f"{BASE}/api/finance/statements/export.pdf")
        assert x.status_code == 200 and x.content[:2] == b"PK" and p.content[:4] == b"%PDF"
        open("/tmp/etats.pdf", "wb").write(p.content)
        assert sess("technicien").get(f"{BASE}/api/finance/statements").status_code in (401, 403) and sess("commercial").post(f"{BASE}/api/finance/statements/x/validate", json={}).status_code in (401, 403)
        assert DB.quotes.count_documents({"org_id": org, "created_at": {"$gt": "2999"}}) == 0
    finally:
        if os.environ.get("KEEP") != "1":
            DB.fiscal_years.delete_many({"org_id": org, "end": {"$in": ["2019-12-31", "2020-12-31", "2021-12-31"]}})
        DB.heading_maps.delete_many({"org_id": org, "prefix": "6226"})
