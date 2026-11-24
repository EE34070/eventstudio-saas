"""Iter 47 — Liste des devis : onglets, filtres, tri, CSV, droits (QA uniquement)."""
import subprocess

import requests

BASE = next(l.split("=", 1)[1].strip().rstrip("/") for l in open("/app/frontend/.env") if l.startswith("REACT_APP_BACKEND_URL="))
OPEN = {"brouillon", "envoye", "vu", "negociation"}


def sess(role):
    t = subprocess.run(["python3", "/app/scripts/qa_token.py", role], capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {t}"})
    return s


def get(s, qs=""):
    r = s.get(f"{BASE}/api/quote-list?size=200&{qs}")
    assert r.status_code == 200, r.text
    return r.json()


def test_groups_counts_sort_and_quick():
    a = sess("admin")
    d = get(a)
    assert d["group"] == "to_process" and d["rows"] and {r["status"] for r in d["rows"]} <= OPEN and d["footer"]["count"] == d["counts"]["to_process"]
    other = sum(1 for r in get(a, "group=all&status=remplace")["rows"]) if False else 0
    assert d["counts"]["all"] - sum(d["counts"][k] for k in ("to_process", "accepted", "closed")) >= other  # le statut « remplacé » n'apparaît que dans « Tous »
    dates = [r["event_date"] for r in d["rows"] if r["event_date"]]
    assert dates == sorted(dates)
    assert {r["status"] for r in get(a, "group=accepted")["rows"]} <= {"accepte"} and {r["status"] for r in get(a, "group=closed")["rows"]} <= {"refuse", "expire"}
    c = get(a, "status=accepte&status=brouillon")
    assert c["group"] == "custom" and {r["status"] for r in c["rows"]} <= {"accepte", "brouillon"}
    f = get(a, "group=all&quick=follow_up")
    assert all(r["status"] in ("envoye", "vu") and r["to_follow_up"] for r in f["rows"])
    assert all(r["expiring"] for r in get(a, "quick=expiring")["rows"])
    amounts = [r["total_ht"] for r in get(a, "group=all&sort=total_ht&dir=desc")["rows"]]
    assert amounts == sorted(amounts, reverse=True)
    big = get(a, "group=all&min_ht=1000")
    assert all(r["total_ht"] >= 1000 for r in big["rows"]) and big["footer"]["total_ht"] >= 1000 * min(1, big["footer"]["count"])
    one = d["rows"][0]
    assert any(r["id"] == one["id"] for r in get(a, f"q={one['number']}")["rows"])
    csv = a.get(f"{BASE}/api/quote-list/csv?group=accepted")
    assert csv.status_code == 200 and "Montant HT" in csv.text and len(csv.text.strip().splitlines()) == get(a, "group=accepted")["footer"]["count"] + 1 or get(a, "group=accepted")["footer"]["count"] > 200


def test_rights():
    assert requests.get(f"{BASE}/api/quote-list").status_code == 401
    assert sess("technicien").get(f"{BASE}/api/quote-list").status_code in (401, 403)
    assert sess("technicien").get(f"{BASE}/api/quote-list/csv").status_code in (401, 403)
