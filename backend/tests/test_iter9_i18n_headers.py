import json
import re
from pathlib import Path

import requests

from conftest import API

ROOT = Path(__file__).resolve().parents[2]
PORTAL = ROOT / "frontend/src/portal"


def test_portal_locales_have_same_keys_and_no_empty_value():
    loc = json.loads((PORTAL / "locales.json").read_text())
    assert set(loc["fr"]) == set(loc["en"])
    assert all(v.strip() for lg in loc.values() for v in lg.values())


def test_every_portal_key_used_exists():
    loc = json.loads((PORTAL / "locales.json").read_text())["fr"]
    src = (PORTAL / "Portal.jsx").read_text() + (PORTAL / "Music.jsx").read_text() + (PORTAL / "Staff.jsx").read_text()
    keys = set(re.findall(r"\bt\(\"([a-z0-9_]+)\"", src))
    assert keys and not (keys - set(loc)), keys - set(loc)
    for prefix in re.findall(r"\bt\(`([a-z_]+)\$\{", src):
        assert any(k.startswith(prefix) for k in loc), prefix


def test_email_templates_bilingual():
    import sys
    sys.path.insert(0, str(ROOT / "backend"))
    src = (ROOT / "backend/portal_core.py").read_text()
    for key in re.findall(r'^    "([a-z_]+)": \{"fr": \(', src, re.M):
        assert f'"{key}"' in src and '"en": (' in src


def test_security_headers():
    h = requests.get(f"{API}/health").headers
    for k in ("Strict-Transport-Security", "X-Content-Type-Options", "Referrer-Policy", "X-Frame-Options", "Permissions-Policy", "Content-Security-Policy"):
        assert k in h, k
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
