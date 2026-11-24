"""Balayage : aucune route ne doit planter (500) à cause du routage par société."""
import re

from fastapi.routing import APIRoute

import security
import server

SKIP = ("/api/auth/google", "/api/clerk", "/api/__clerk", "/api/cron/", "/api/webhooks/", "/api/health")


class _R:
    def __init__(self, path, methods):
        self.path, self.methods = path, methods


def _walk(routes, prefix=""):
    for r in routes:
        if isinstance(r, APIRoute):
            yield _R(prefix + r.path, r.methods)
        elif hasattr(r, "original_router"):
            yield from _walk(r.original_router.routes, prefix + (r.include_context.prefix or ""))


def _routes():
    out = list(_walk(server.app.router.routes))
    assert len(out) > 400, len(out)
    return out


async def test_authenticated_get_routes_do_not_crash(client, as_user, caplog):
    failures = []
    for r in _routes():
        if "GET" not in r.methods or "{" in r.path or r.path.startswith(SKIP):
            continue
        security._hits.clear()
        res = await client.get(r.path, headers=as_user("alice"))
        if res.status_code >= 500:
            failures.append((r.path, res.status_code))
        assert res.status_code != 429
    assert not failures, failures
    assert "sans société active" not in caplog.text


async def test_public_token_routes_do_not_crash(client, caplog):
    failures = []
    for r in _routes():
        if "GET" not in r.methods or not r.path.startswith("/api/public/"):
            continue
        path = re.sub(r"\{[^}]+\}", "x" * 43, r.path)
        security._hits.clear()
        res = await client.get(path)
        if res.status_code >= 500:
            failures.append((r.path, res.status_code))
    assert not failures, failures


async def test_public_post_routes_do_not_crash(client):
    failures = []
    for r in _routes():
        if not ({"POST", "PUT"} & r.methods) or not r.path.startswith(("/api/public/", "/api/crm/leads")):
            continue
        path = re.sub(r"\{[^}]+\}", "x" * 43, r.path)
        security._hits.clear()
        method = "POST" if "POST" in r.methods else "PUT"
        res = await client.request(method, path, json={})
        if res.status_code == 500:  # 503 = intégration non configurée, attendu en test
            failures.append((method, r.path, res.status_code, res.text[:120]))
    assert not failures, failures
