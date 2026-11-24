"""Travaux internes — lot 1 : critères d'acceptation du cahier des charges (partie ordres de travail)."""
from datetime import date, timedelta

import tenant_router as tenants
from conftest import ORG_A


async def _team(platform, *people):
    t = platform.tenant(ORG_A)
    for tid, name in people:
        await t.team.insert_one({"id": tid, "org_id": ORG_A, "name": name, "active": True, "skills": [], "deleted_at": None})


def _next(weekday: int) -> date:
    d = date.today() + timedelta(days=1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


async def test_backlog_then_schedule(client, as_user, platform):
    await _team(platform, ("t-maxime", "Maxime"))
    friday = _next(4).isoformat()
    r = await client.post("/api/work-orders", headers=as_user("alice"), json={
        "title": "Ranger et étiqueter le rack 3", "type": "rangement", "required_people": 2,
        "estimated_minutes": 360, "deadline": friday})
    assert r.status_code == 200, r.text
    w = r.json()
    assert w["status"] == "a_planifier"
    backlog = (await client.get("/api/work-orders?backlog=true", headers=as_user("alice"))).json()["orders"]
    assert [x["id"] for x in backlog] == [w["id"]]

    thursday = _next(3).isoformat()
    r = await client.patch(f"/api/work-orders/{w['id']}", headers=as_user("alice"),
                           json={"scheduled_start": f"{thursday}T09:00", "assignee_ids": ["t-maxime"]})
    assert r.status_code == 200, r.text
    w = r.json()
    assert w["status"] == "planifie"
    assert w["scheduled_end"] == f"{thursday}T12:00"  # 6 h-personne sur 2 personnes = 9 h–12 h
    assert (await client.get("/api/work-orders?backlog=true", headers=as_user("alice"))).json()["orders"] == []


async def test_backlog_sorted_by_urgency(client, as_user):
    today = date.today()
    for title, deadline, prio in (("Plus tard", (today + timedelta(days=20)).isoformat(), "urgente"),
                                  ("Bientôt", (today + timedelta(days=2)).isoformat(), "normale"),
                                  ("Même jour, haute", (today + timedelta(days=2)).isoformat(), "haute")):
        await client.post("/api/work-orders", headers=as_user("alice"), json={"title": title, "deadline": deadline, "priority": prio})
    rows = (await client.get("/api/work-orders?backlog=true", headers=as_user("alice"))).json()["orders"]
    assert [r["title"] for r in rows] == ["Même jour, haute", "Bientôt", "Plus tard"]


async def test_multi_day_project_with_drying_delay(client, as_user):
    arche = (await client.post("/api/work-orders", headers=as_user("alice"), json={"title": "Arche mariage X", "type": "construction"})).json()
    d = _next(0)

    async def step(title, order, start, deps=(), delay=0):
        return await client.post("/api/work-orders", headers=as_user("alice"), json={
            "title": title, "parent_id": arche["id"], "step_order": order, "estimated_minutes": 240,
            "scheduled_start": start, "depends_on_ids": list(deps), "min_delay_after_hours": delay})

    peinture = (await step("Peinture", 3, f"{d}T09:00")).json()
    r = await step("Montage test", 4, f"{d + timedelta(days=1)}T08:00", [peinture["id"]], 24)
    assert r.status_code == 422 and "ne peut pas commencer avant" in r.json()["detail"]
    r = await step("Montage test", 4, f"{d + timedelta(days=1)}T13:00", [peinture["id"]], 24)
    assert r.status_code == 200, r.text

    full = (await client.get(f"/api/work-orders/{arche['id']}", headers=as_user("alice"))).json()
    assert [s["title"] for s in full["steps"]] == ["Peinture", "Montage test"]
    assert full["progress"] == {"done": 0, "total": 2, "percent": 0, "estimated_minutes": 480, "actual_minutes": 0}
    await client.patch(f"/api/work-orders/{peinture['id']}", headers=as_user("alice"), json={"status": "fait"})
    full = (await client.get(f"/api/work-orders/{arche['id']}", headers=as_user("alice"))).json()
    assert full["progress"]["percent"] == 50
    # Les étapes n'encombrent pas la liste principale
    assert [o["title"] for o in (await client.get("/api/work-orders", headers=as_user("alice"))).json()["orders"]] == ["Arche mariage X"]


async def test_weekly_recurrence_generates_and_detaches(client, as_user, platform):
    tpl = (await client.post("/api/work-templates", headers=as_user("alice"), json={
        "title": "Rangement entrepôt", "type": "rangement", "estimated_minutes": 120, "checklist": [{"label": "Balayer"}]})).json()
    rec = (await client.post("/api/work-recurrences", headers=as_user("alice"), json={
        "template_id": tpl["id"], "freq": "weekly", "weekdays": [0], "start_time": "08:00", "end_time": "10:00",
        "start": date.today().isoformat()})).json()
    assert rec["generated"] == 8
    rows = (await client.get("/api/work-orders?status=planifie", headers=as_user("alice"))).json()["orders"]
    assert len(rows) == 8 and all(r["scheduled_start"].endswith("T08:00") and r["checklist"][0]["label"] == "Balayer" for r in rows)
    first = rows[0]
    moved = first["scheduled_start"][:10] + "T14:00"
    r = await client.patch(f"/api/work-orders/{first['id']}", headers=as_user("alice"), json={"scheduled_start": moved, "scheduled_end": ""})
    assert r.json()["detached"] is True
    # Régénération (tâche planifiée) : rien en double, l'occurrence déplacée reste où elle est
    import routes_works
    await tenants.for_each_org(routes_works.tick)
    rows = (await client.get("/api/work-orders?status=planifie", headers=as_user("alice"))).json()["orders"]
    assert len(rows) == 8
    assert next(r for r in rows if r["id"] == first["id"])["scheduled_start"] == moved


async def test_regeneration_is_idempotent(client, as_user, platform):
    import routes_works
    tpl = (await client.post("/api/work-templates", headers=as_user("alice"), json={"title": "Inventaire chaises", "type": "inventaire"})).json()
    await client.post("/api/work-recurrences", headers=as_user("alice"), json={
        "template_id": tpl["id"], "freq": "monthly", "monthday": 1, "start": date.today().isoformat()})
    before = await platform.tenant(ORG_A).work_orders.count_documents({"deleted_at": None})
    await tenants.for_each_org(routes_works.tick)
    assert await platform.tenant(ORG_A).work_orders.count_documents({"deleted_at": None}) == before
    assert before in (1, 2)  # le 1er du mois sur 8 semaines


async def test_technician_sees_only_own_orders_without_costs(client, as_user, platform):
    await _team(platform, ("t-tech", "Tech"), ("t-autre", "Autre"))
    await platform.control.users.insert_one({"user_id": "tech", "email": "tech@test.fr", "name": "Tech", "org_id": ORG_A,
                                             "role": "technicien", "team_id": "t-tech", "env": "preview", "status": "active", "last_login_at": "2999"})
    mine = (await client.post("/api/work-orders", headers=as_user("alice"), json={"title": "À moi", "assignee_ids": ["t-tech"]})).json()
    await client.post("/api/work-orders", headers=as_user("alice"), json={"title": "Pas à moi", "assignee_ids": ["t-autre"]})
    rows = (await client.get("/api/work-orders", headers=as_user("tech"))).json()["orders"]
    assert [r["title"] for r in rows] == ["À moi"]
    assert "cost_labor" not in rows[0]
    assert (await client.get(f"/api/work-orders/{mine['id']}", headers=as_user("tech"))).status_code == 200
    assert (await client.post("/api/work-orders", headers=as_user("tech"), json={"title": "x"})).status_code == 403


async def test_todo_to_work_order(client, as_user):
    t = (await client.post("/api/tasks", headers=as_user("alice"), json={"title": "Réparer la table pliante", "priority": "high"})).json()
    w = (await client.post(f"/api/tasks/{t['id']}/to-work-order", headers=as_user("alice"))).json()
    assert w["title"] == "Réparer la table pliante" and w["priority"] == "haute" and w["status"] == "a_planifier"


async def test_unknown_references_refused(client, as_user):
    r = await client.post("/api/work-orders", headers=as_user("alice"), json={"title": "x", "type": "inexistant"})
    assert r.status_code == 422
    r = await client.post("/api/work-orders", headers=as_user("alice"), json={"title": "x", "assignee_ids": ["fantome"]})
    assert r.status_code == 422


async def test_not_in_essentiel_plan(client, as_user, platform):
    await platform.control.orgs.update_one({"id": ORG_A}, {"$set": {"subscription": {"plan": "essentiel", "status": "active"}}})
    assert (await client.get("/api/work-orders", headers=as_user("alice"))).status_code == 403
