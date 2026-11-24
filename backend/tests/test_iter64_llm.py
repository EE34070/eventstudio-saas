"""Iter 64 — couche LLM unique (QA)."""
from tests.test_iter54_dj_tab_roadmap import BASE, sess


def test_llm_check():
    r = sess("admin").get(f"{BASE}/api/admin/llm-check")
    d = r.json()
    assert r.status_code == 200 and d["provider"] in ("anthropic", "emergent") and d["model"] and d["status"] in ("ok", "error") and "latency_ms" in d
    assert d["status"] == "ok" or d["reason"]
    assert sess("technicien").get(f"{BASE}/api/admin/llm-check").status_code == 403
