"""Travaux internes — lot 2 : planning d'équipe, placement et contrôles."""
from datetime import date, timedelta

from conftest import ORG_A


def _next(weekday: int) -> date:
    d = date.today() + timedelta(days=1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d


async def _team(platform, *people):
    t = platform.tenant(ORG_A)
    for p in people:
        await t.team.insert_one({"active": True, "skills": [], "deleted_at": None, "org_id": ORG_A, "contract_type": "cdi", **p})


async def _work(client, as_user, **kw):
    r = await client.post("/api/work-orders", headers=as_user("alice"), json={"title": "Travail", **kw})
    assert r.status_code == 200, r.text
    return r.json()


async def test_drop_on_person_places_and_computes_end(client, as_user, platform):
    await _team(platform, {"id": "t-max", "name": "Maxime"})
    w = await _work(client, as_user, title="Ranger le rack 3", estimated_minutes=180)
    mon = _next(0)
    r = await client.post(f"/api/work-orders/{w['id']}/place", headers=as_user("alice"),
                          json={"scheduled_start": f"{mon}T09:00", "add_assignee_id": "t-max"})
    assert r.status_code == 200, r.text
    assert r.json()["scheduled_end"] == f"{mon}T12:00" and r.json()["status"] == "planifie"

    b = (await client.get(f"/api/work-planning?start={mon}", headers=as_user("alice"))).json()
    row = next(m for m in b["members"] if m["id"] == "t-max")
    assert row["cells"][0]["hours"] == 3 and row["cells"][0]["items"][0]["title"] == "Ranger le rack 3"
    assert row["capacity"] == 35 and row["load_pct"] == 9   # 3 h sur 35 h

    r = await client.post(f"/api/work-orders/{w['id']}/unplace", headers=as_user("alice"))
    assert r.status_code == 200
    back = (await client.get("/api/work-orders?backlog=true", headers=as_user("alice"))).json()["orders"]
    assert [x["id"] for x in back] == [w["id"]]


async def test_conflicts_are_reported_then_forced(client, as_user, platform):
    mon = _next(0)
    await _team(platform, {"id": "t-max", "name": "Maxime", "skills": ["peinture"],
                           "unavailabilities": [{"start": (mon + timedelta(days=1)).isoformat(), "end": (mon + timedelta(days=1)).isoformat(), "reason": "Congés payés"}]})
    await platform.tenant(ORG_A).events.insert_one({"id": "ev1", "org_id": ORG_A, "title": "Mariage X", "code": "EV-001", "status": "confirme", "deleted_at": None,
                                                    "start": f"{mon}T14:00", "end": f"{mon}T23:00", "team": [{"member_id": "t-max", "role": ""}]})
    a = await _work(client, as_user, title="Atelier soudure", estimated_minutes=240, required_people=2, required_skills=["soudure"],
                    deadline=mon.isoformat())

    r = await client.post(f"/api/work-orders/{a['id']}/place", headers=as_user("alice"),
                          json={"scheduled_start": f"{mon}T12:00", "scheduled_end": f"{mon}T16:00", "assignee_ids": ["t-max"]})
    assert r.status_code == 409
    msgs = r.json()["detail"]["conflicts"]
    assert any("Effectif insuffisant" in m for m in msgs)
    assert any("soudure" in m for m in msgs)
    assert any("déjà sur « Mariage X »" in m for m in msgs)
    assert any("13 h" in m and "maximum 10 h" in m for m in msgs)   # 4 h + 9 h d'événement

    r = await client.post(f"/api/work-orders/{a['id']}/place", headers=as_user("alice"),
                          json={"scheduled_start": f"{mon + timedelta(days=1)}T09:00", "assignee_ids": ["t-max"]})
    assert r.status_code == 409
    msgs = r.json()["detail"]["conflicts"]
    assert any("indisponible" in m and "Congés payés" in m for m in msgs)
    assert any("date limite" in m for m in msgs)

    r = await client.post(f"/api/work-orders/{a['id']}/place", headers=as_user("alice"),
                          json={"scheduled_start": f"{mon + timedelta(days=1)}T09:00", "assignee_ids": ["t-max"], "force": True})
    assert r.status_code == 200 and r.json()["forced"] is True and r.json()["forced_conflicts"]


async def test_rest_between_days(client, as_user, platform):
    mon = _next(0)
    await _team(platform, {"id": "t-max", "name": "Maxime"})
    await platform.tenant(ORG_A).events.insert_one({"id": "ev1", "org_id": ORG_A, "title": "Soirée", "code": "EV-002", "status": "confirme", "deleted_at": None,
                                                    "start": f"{mon}T18:00", "end": f"{mon + timedelta(days=1)}T02:00", "team": [{"member_id": "t-max"}]})
    w = await _work(client, as_user, estimated_minutes=120)
    r = await client.post(f"/api/work-orders/{w['id']}/place", headers=as_user("alice"),
                          json={"scheduled_start": f"{mon + timedelta(days=1)}T08:00", "assignee_ids": ["t-max"]})
    assert r.status_code == 409 and any("repos de moins de 11 h" in m for m in r.json()["detail"]["conflicts"])
    r = await client.post(f"/api/work-orders/{w['id']}/place", headers=as_user("alice"),
                          json={"scheduled_start": f"{mon + timedelta(days=1)}T14:00", "assignee_ids": ["t-max"]})
    assert r.status_code == 200, r.text


async def test_dependencies_still_block(client, as_user, platform):
    await _team(platform, {"id": "t-max", "name": "Maxime"})
    mon = _next(0)
    arche = await _work(client, as_user, title="Arche")
    peinture = await _work(client, as_user, title="Peinture", parent_id=arche["id"], scheduled_start=f"{mon}T09:00", estimated_minutes=240)
    montage = await _work(client, as_user, title="Montage", parent_id=arche["id"], depends_on_ids=[peinture["id"]], min_delay_after_hours=24)
    r = await client.post(f"/api/work-orders/{montage['id']}/place", headers=as_user("alice"),
                          json={"scheduled_start": f"{mon + timedelta(days=1)}T08:00", "assignee_ids": ["t-max"], "force": True})
    assert r.status_code == 422


async def test_intermittent_has_no_capacity_and_pdf(client, as_user, platform):
    mon = _next(0)
    await _team(platform, {"id": "t-cddu", "name": "Inter", "contract_type": "cddu"})
    b = (await client.get(f"/api/work-planning?start={mon}", headers=as_user("alice"))).json()
    row = next(m for m in b["members"] if m["id"] == "t-cddu")
    assert row["intermittent"] is True
    r = await client.get(f"/api/work-planning/pdf?start={mon}", headers=as_user("alice"))
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


async def test_technician_sees_only_own_row_and_cannot_place(client, as_user, platform):
    await _team(platform, {"id": "t-tech", "name": "Tech"}, {"id": "t-autre", "name": "Autre"})
    await platform.control.users.insert_one({"user_id": "tech", "email": "tech@test.fr", "name": "Tech", "org_id": ORG_A,
                                             "role": "technicien", "team_id": "t-tech", "env": "preview", "status": "active", "last_login_at": "2999"})
    b = (await client.get("/api/work-planning", headers=as_user("tech"))).json()
    assert [m["id"] for m in b["members"]] == ["t-tech"]
    w = await _work(client, as_user)
    r = await client.post(f"/api/work-orders/{w['id']}/place", headers=as_user("tech"), json={"scheduled_start": f"{_next(0)}T09:00"})
    assert r.status_code == 403
