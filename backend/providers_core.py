import logging
import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from pymongo.errors import BulkWriteError

import messaging_core as mc
from core import db, new_id, now_iso
from i18n import LANGS, doc_lang, fmt_date  # noqa: F401

logger = logging.getLogger(__name__)
PARIS = ZoneInfo("Europe/Paris")
MAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ORGANIZERS = ["wedding_planner", "agence_evenementielle", "agence_communication"]
CATEGORIES = [("wedding_planner", "Wedding planner"), ("traiteur", "Traiteur"), ("photographe", "Photographe"), ("videaste", "Vidéaste"), ("location_mobilier", "Location mobilier / vaisselle"), ("dj", "DJ"), ("technicien_polyvalent", "Technicien polyvalent"),
              ("manutentionnaire", "Manutentionnaire"), ("fournisseur_son_lumiere", "Fournisseur son & lumière"),
              ("saxophoniste", "Saxophoniste"), ("violoniste", "Violoniste"), ("percussionniste", "Percussionniste"),
              ("autres", "Autre"), ("agence_evenementielle", "Agence événementielle"), ("agence_communication", "Agence de communication")]
EQUIPMENT = {"sono": "Sono / table de mixage", "micro": "Micro", "retour": "Retour", "prise_220v": "Prise 220 V", "pupitre": "Pupitre",
             "eclairage": "Éclairage", "loge": "Loge", "repas": "Repas", "parking": "Parking"}
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
OPEN = ["sent", "in_progress"]
TEMPLATES = {
    "request": ("Demande de disponibilité — {métier} le {date} à {ville}",
                "Bonjour {prénom},\n\nNous recherchons un(e) {métier} pour un événement ({type_evenement}) le {date}, {horaires}, à {ville}.\n\n"
                "{brief}\n\nMatériel disponible sur place : {materiel_sur_place}\nBudget : {budget}\n\n"
                "Merci de nous répondre avant le {date_limite}, en un clic et sans créer de compte :\n{lien_reponse}\n\nBien cordialement,"),
    "reminder": ("Relance — {métier} le {date} à {ville}",
                 "Bonjour {prénom},\n\nNous n'avons pas encore reçu votre réponse pour notre demande de {métier} le {date}, {horaires}, à {ville}.\n\n"
                 "Vous pouvez répondre en un clic avant le {date_limite} :\n{lien_reponse}\n\nBien cordialement,"),
    "confirmation": ("Confirmation — {métier} le {date} à {ville}",
                     "Bonjour {prénom},\n\nNous avons le plaisir de vous confirmer la prestation suivante.\n\nDate : {date}, {horaires}\nAdresse : {adresse}\n"
                     "Contact sur place : {contact_sur_place}\nAccès : {acces}\n\nConsignes et tenue :\n{brief}\n\nMontant convenu : {montants}\n"
                     "Matériel fourni sur place : {materiel_sur_place}\nMatériel à prévoir : {materiel_a_prevoir}\n\nMerci de nous confirmer la bonne réception de ce message.\n\nBien cordialement,"),
    "filled": ("Date pourvue — {métier} le {date}",
               "Bonjour {prénom},\n\nMerci pour votre réponse. La prestation de {métier} du {date} à {ville} est désormais pourvue.\n\n"
               "Nous ne manquerons pas de vous solliciter pour une prochaine date.\n\nBien cordialement,"),
    "roadmap": ("Feuille de route J-3 — {métier} le {date} à {ville}",
                "Bonjour {prénom},\n\nRappel de votre prestation dans trois jours.\n\nDate : {date}, {horaires}\nAdresse : {adresse}\nContact sur place : {contact_sur_place}\n"
                "Accès : {acces}\n\nConsignes et tenue :\n{brief}\n\nMontant convenu : {montants}\nMatériel fourni sur place : {materiel_sur_place}\n"
                "Matériel à prévoir : {materiel_a_prevoir}\n\nÀ très bientôt,"),
}
TEMPLATES_EN = {
    "request": ("Availability request — {métier} on {date} in {ville}",
                "Hello {prénom},\n\nWe are looking for a {métier} for an event ({type_evenement}) on {date}, {horaires}, in {ville}.\n\n"
                "{brief}\n\nEquipment available on site: {materiel_sur_place}\nBudget: {budget}\n\n"
                "Please reply before {date_limite}, in one click and without creating an account:\n{lien_reponse}\n\nKind regards,"),
    "reminder": ("Reminder — {métier} on {date} in {ville}",
                 "Hello {prénom},\n\nWe have not yet received your reply to our request for a {métier} on {date}, {horaires}, in {ville}.\n\n"
                 "You can reply in one click before {date_limite}:\n{lien_reponse}\n\nKind regards,"),
    "confirmation": ("Confirmation — {métier} on {date} in {ville}",
                     "Hello {prénom},\n\nWe are pleased to confirm the following booking.\n\nDate: {date}, {horaires}\nAddress: {adresse}\n"
                     "On-site contact: {contact_sur_place}\nAccess: {acces}\n\nInstructions and dress code:\n{brief}\n\nAgreed amount: {montants}\n"
                     "Equipment provided on site: {materiel_sur_place}\nEquipment to bring: {materiel_a_prevoir}\n\nPlease confirm receipt of this message.\n\nKind regards,"),
    "filled": ("Date filled — {métier} on {date}",
               "Hello {prénom},\n\nThank you for your reply. The {métier} booking on {date} in {ville} has now been filled.\n\n"
               "We will be in touch for a future date.\n\nKind regards,"),
    "roadmap": ("Run sheet D-3 — {métier} on {date} in {ville}",
                "Hello {prénom},\n\nA reminder of your booking in three days.\n\nDate: {date}, {horaires}\nAddress: {adresse}\nOn-site contact: {contact_sur_place}\n"
                "Access: {acces}\n\nInstructions and dress code:\n{brief}\n\nAgreed amount: {montants}\nEquipment provided on site: {materiel_sur_place}\n"
                "Equipment to bring: {materiel_a_prevoir}\n\nSee you soon,"),
}
RGPD_EN = ("\n\n—\nYou are receiving this message because your professional contact details are in the supplier file of {org}, which uses them only to "
           "offer you bookings. You may request access, correction or deletion by replying to this message. Stop receiving requests: {stop}")
RGPD = ("\n\n—\nVous recevez ce message car vos coordonnées professionnelles figurent dans le fichier prestataires de {org}, qui les utilise uniquement pour vous "
        "proposer des missions. Vous pouvez demander leur accès, leur rectification ou leur suppression en répondant à ce message. Ne plus être sollicité : {stop}")


def money(v: float) -> str:
    return f"{v:,.2f}".replace(",", " ").replace(".", ",") + " €"


def fr_date(d: str) -> str:
    x = datetime.strptime(d, "%Y-%m-%d")
    return f"{DAYS[x.weekday()]} {x.day} {MONTHS[x.month - 1]} {x.year}"


def fr_deadline(iso: str) -> str:
    x = datetime.fromisoformat(iso).astimezone(PARIS)
    return f"{x.day:02d}/{x.month:02d}/{x.year} à {x.hour}h{x.minute:02d}"


def duration_h(start: str, end: str) -> float:
    a, b = (int(t[:2]) * 60 + int(t[3:]) for t in (start, end))
    return round(((b - a) % 1440 or 1440) / 60, 2)


def distance_km(lat1, lng1, lat2, lng2) -> float | None:
    if None in (lat1, lng1, lat2, lng2):
        return None
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return round(6371 * 2 * math.asin(math.sqrt(a)) * 1.2, 1)


def totals(rate: float, travel: float, vat_mode: str, vat_rate: float) -> tuple:
    ht = round(rate + travel, 2)
    return ht, round(ht * (1 + vat_rate / 100), 2) if vat_mode == "subject" else ht


def price_text(vat_mode: str, vat_rate: float, ht: float, ttc: float) -> str:
    if vat_mode == "subject":
        return f"{money(ht)} HT, soit {money(ttc)} TTC (TVA {vat_rate:g} %)"
    return f"{money(ht)} net — TVA non applicable, art. 293 B du CGI"


def estimate(p: dict, req: dict) -> dict:
    dist = distance_km(p.get("base_lat"), p.get("base_lng"), req.get("venue_lat"), req.get("venue_lng"))
    dept = (req.get("venue_zip") or "")[:2]
    in_zone = bool(p.get("travels_everywhere") or (dept and dept in p.get("departments", [])) or (dist is not None and p.get("radius_km") and dist <= p["radius_km"]))
    extra = math.ceil(max(0, duration_h(req["start_time"], req["end_time"]) - p["included_hours"])) if p.get("included_hours") else 0
    rate = round(p.get("base_rate", 0) + extra * p.get("extra_hour_rate", 0), 2)
    mode, travel = p.get("travel_fee_mode", "included"), 0.0
    if mode == "flat":
        travel = p.get("travel_fee_amount", 0)
    elif mode == "per_km" and dist is not None:
        travel = float(round(max(0, 2 * dist - p.get("travel_km_included", 0)) * p.get("travel_fee_amount", 0)))
    ht, ttc = totals(rate, travel, p["vat_mode"], p["vat_rate"])
    return {"distance_km": dist, "in_zone": in_zone, "rate": rate, "extra_hours": extra, "travel_fee": travel,
            "travel_on_quote": mode == "quote" or (mode == "per_km" and dist is None), "total_ht": ht, "total_ttc": ttc,
            "missing_equipment": [e for e in p.get("equipment_needed", []) if e not in req.get("onsite_equipment", [])]}


async def geocode(q: str, municipality: bool = False) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            f = (await c.get("https://data.geopf.fr/geocodage/search", params={"q": q, "limit": 1, **({"type": "municipality"} if municipality else {})})).json()["features"][0]
        return {"lat": f["geometry"]["coordinates"][1], "lng": f["geometry"]["coordinates"][0], "city": f["properties"].get("city", ""), "zip": f["properties"].get("postcode", "")}
    except Exception:
        return None


async def ensure_categories(org_id: str) -> None:
    if await db.provider_categories.find_one({"org_id": org_id}):
        return
    try:
        await db.provider_categories.insert_many([{"id": new_id(), "org_id": org_id, "key": k, "label": lab, "order": i + 1, "active": True, "is_organizer": k in ORGANIZERS, "created_at": now_iso()}
                                                  for i, (k, lab) in enumerate(CATEGORIES)], ordered=False)
    except BulkWriteError:
        pass


async def migrate_organizers() -> None:
    for org_id in await db.provider_categories.distinct("org_id", {"key": "wedding_planner"}):
        o = {"org_id": org_id}
        if await db.provider_categories.find_one({**o, "key": "agence_evenementielle"}):
            continue
        base = (await db.provider_categories.find_one({**o, "key": "wedding_planner"}))["order"]
        await db.provider_categories.update_many({**o, "order": {"$gt": base}}, {"$inc": {"order": 2}})
        await db.provider_categories.insert_many([{"id": new_id(), **o, "key": k, "label": dict(CATEGORIES)[k], "order": base + i, "active": True, "is_organizer": True,
                                                   "created_at": now_iso()} for i, k in enumerate(ORGANIZERS[1:], start=1)])
        await db.provider_categories.update_many({**o, "is_organizer": {"$exists": False}}, {"$set": {"is_organizer": False}})
        await db.provider_categories.update_one({**o, "key": "wedding_planner"}, {"$set": {"is_organizer": True}})


async def labels(org_id: str) -> dict:
    await ensure_categories(org_id)
    return {c["key"]: c["label"] async for c in db.provider_categories.find({"org_id": org_id}, {"_id": 0})}


async def template(org_id: str, kind: str, category_key: str, language: str = "fr") -> tuple:
    base = {"org_id": org_id, "type": kind, "channel": "email", "language": language}
    for key in (category_key, ""):
        t = await db.message_templates.find_one({**base, "category_key": key}, {"_id": 0})
        if t:
            return t["subject"], t["body"]
    return (TEMPLATES_EN if language == "en" else TEMPLATES)[kind]


def equipment_text(keys: list, note: str = "") -> str:
    return ", ".join([EQUIPMENT.get(k, k) for k in keys] + ([note] if note else [])) or "non précisé"


def budget_text(req: dict) -> str:
    lo, hi = req.get("budget_min") or 0, req.get("budget_max") or 0
    if req.get("hide_budget") or not (lo or hi):
        return "à nous proposer"
    return (f"de {money(lo)} à {money(hi)}" if lo and hi and lo != hi else money(hi or lo)) + f" {req.get('budget_tax_mode', 'HT')}"


def variables(org: dict, req: dict, prof: dict, contact: dict, rec: dict, lab: dict, mission: dict | None = None) -> dict:
    m = mission or {}
    return {"prénom": contact.get("first_name") or prof.get("stage_name") or contact.get("company") or "", "métier": lab.get(req["category_key"], req["category_key"]),
            "date": fr_date(req["date"]), "horaires": f"de {req['start_time'].replace(':', 'h')} à {req['end_time'].replace(':', 'h')}",
            "ville": req.get("venue_city") or req.get("venue_address", ""), "type_evenement": req.get("event_type") or "événement privé",
            "brief": req.get("brief") or "Les détails vous seront précisés.", "materiel_sur_place": equipment_text(req.get("onsite_equipment", []), req.get("onsite_equipment_note", "")),
            "budget": budget_text(req), "date_limite": fr_deadline(req["reply_deadline"]), "lien_reponse": f"{req.get('app_url', '')}/reponse/{rec['token']}",
            "adresse": ", ".join(filter(None, [req.get("venue_name"), req.get("venue_address"), f"{req.get('venue_zip', '')} {req.get('venue_city', '')}".strip()])),
            "contact_sur_place": req.get("onsite_contact") or "à préciser", "acces": req.get("access_instructions") or "à préciser",
            "montants": price_text(m["vat_mode"], m["vat_rate"], m["total_ht"], m["total_ttc"]) + f" (dont déplacement {money(m['agreed_travel_fee'])})" if m else "",
            "materiel_a_prevoir": equipment_text([e for e in m.get("equipment_needed", []) if e not in req.get("onsite_equipment", [])]) if m else ""}


def render(text: str, v: dict) -> str:
    return re.sub(r"\{([a-zé_]+)\}", lambda x: str(v.get(x.group(1), x.group(0))), text)


async def deliver(org: dict, req: dict, rec: dict, kind: str, mission: dict | None = None) -> None:
    oid = org["id"]
    acc = await db.channel_accounts.find_one({"org_id": oid, "channel": "gmail", "status": "connected"}, {"_id": 0})
    if not acc:
        raise RuntimeError("La boîte Gmail n'est pas connectée")
    prof = await db.provider_profiles.find_one({"org_id": oid, "id": rec["provider_id"]}, {"_id": 0})
    contact = await db.contacts.find_one({"org_id": oid, "id": prof["contact_id"]}, {"_id": 0}) if prof else None
    if not contact or not MAIL_RE.match(contact.get("email") or ""):
        raise RuntimeError("Adresse e-mail du prestataire manquante ou invalide")
    from core import ensure_link
    rec = {**rec, "token": await ensure_link("request_recipients", rec)}
    v = variables(org, req, prof, contact, rec, await labels(oid), mission)
    lg = doc_lang(contact.get("language"))
    if lg == "en":
        v.update(date=fmt_date(req["date"], contact["language"]), horaires=f"from {req['start_time']} to {req['end_time']}")
    subject, body = (req["message_subject"], req["message_body"]) if kind == "request" and req.get("message_body") and lg == "fr" else await template(oid, kind, req["category_key"], lg)
    text = render(body, v)
    if kind in ("request", "reminder"):
        text += (RGPD_EN if lg == "en" else RGPD).format(org=org.get("name", ""), stop=v["lien_reponse"] + "?stop=1")
    cid = await mc.send_mail(acc, org, contact["email"], render(subject, v), text)
    await db.conversations.update_one({"org_id": oid, "id": cid}, {"$set": {"contact_id": contact["id"], **({"event_id": req["event_id"]} if req.get("event_id") else {})}})


async def send_recipient(org: dict, req: dict, rec: dict, kind: str = "request") -> bool:
    field = "sent_at" if kind == "request" else "reminded_at"
    now = datetime.now(timezone.utc)
    key = {"org_id": org["id"], "id": rec["id"]}
    claim = await db.request_recipients.update_one({**key, field: None, "$or": [{"claim": None}, {"claim": {"$lt": now.isoformat()}}]},
                                                   {"$set": {"claim": (now + timedelta(minutes=5)).isoformat()}})
    if not claim.modified_count:
        return False
    try:
        await deliver(org, req, rec, kind)
    except Exception as exc:
        reason = mc.explain(exc) if isinstance(exc, (mc.GmailError, mc.GmailAuthError)) else str(exc)[:200]
        logger.error("Envoi prestataire %s (%s) en échec : %s", rec["id"], kind, reason)
        await db.request_recipients.update_one(key, {"$set": {"send_error": reason, "claim": None}})
        return False
    await db.request_recipients.update_one(key, {"$set": {field: now_iso(), "send_error": None, "claim": None}})
    return True


async def send_batch(org: dict, req: dict, n: int | None = None) -> int:
    rows = await db.request_recipients.find({"org_id": org["id"], "request_id": req["id"], "sent_at": None, "send_error": None}, {"_id": 0}).sort("order", 1).to_list(n or 500)
    return sum([await send_recipient(org, req, r) for r in rows])


async def tick() -> None:
    now = datetime.now(timezone.utc)
    async for req in db.service_requests.find({"status": {"$in": OPEN}, "reply_deadline": {"$gt": now.isoformat()}}, {"_id": 0}):
        org = await db.orgs.find_one({"id": req["org_id"]}, {"_id": 0})
        recs = await db.request_recipients.find({"org_id": req["org_id"], "request_id": req["id"], "send_error": None}, {"_id": 0}).to_list(500)
        deadline = datetime.fromisoformat(req["reply_deadline"])
        sent, queued = [r for r in recs if r.get("sent_at")], [r for r in recs if not r.get("sent_at")]
        for r in sent:
            at = datetime.fromisoformat(r["sent_at"])
            if r["reply"] == "none" and not r.get("reminded_at") and now >= at + (deadline - at) / 2:
                await send_recipient(org, req, r, "reminder")
        if not queued:
            continue
        if not req.get("cascade_enabled"):
            if any(r["created_at"] < (now - timedelta(minutes=10)).isoformat() for r in queued):
                await send_batch(org, req)
        elif len([r for r in recs if r["reply"] == "available"]) < req["quantity"]:
            last = max((r["sent_at"] for r in sent), default=None)
            if not last or now >= datetime.fromisoformat(last) + timedelta(hours=req["cascade_delay_h"]):
                n = await send_batch(org, req, req["cascade_batch_size"])
                logger.info("Cascade : %s envoi(s) pour la demande %s", n, req["id"])
    today = now.astimezone(PARIS)
    async for m in db.missions.find({"status": "confirmed", "roadmap_sent_at": None, "date": {"$gte": today.strftime("%Y-%m-%d"), "$lte": (today + timedelta(days=3)).strftime("%Y-%m-%d")}}, {"_id": 0}):
        key = {"org_id": m["org_id"], "id": m["id"]}
        if not (await db.missions.update_one({**key, "roadmap_sent_at": None}, {"$set": {"roadmap_sent_at": now_iso()}})).modified_count:
            continue
        req = await db.service_requests.find_one({"org_id": m["org_id"], "id": m["request_id"]}, {"_id": 0})
        rec = await db.request_recipients.find_one({"org_id": m["org_id"], "id": m["recipient_id"]}, {"_id": 0})
        try:
            await deliver(await db.orgs.find_one({"id": m["org_id"]}, {"_id": 0}), req, rec, "roadmap", m)
        except Exception as exc:
            logger.error("Feuille de route %s en échec : %s", m["id"], exc)
            await db.missions.update_one(key, {"$set": {"roadmap_error": str(exc)[:200]}})


async def alerts(org_id: str) -> list:
    out = []
    reqs = {r["id"]: r async for r in db.service_requests.find({"org_id": org_id, "status": {"$in": OPEN}}, {"_id": 0})}
    if reqs:
        lab = await labels(org_id)
        async for r in db.request_recipients.find({"org_id": org_id, "request_id": {"$in": list(reqs)}, "reply": {"$in": ["available", "conditional"]}, "retained": {"$ne": True}}, {"_id": 0}):
            req = reqs[r["request_id"]]
            out.append({"type": "prestataire", "severity": "warning", "event_id": req.get("event_id") or None, "request_id": req["id"],
                        "title": f"{r.get('provider_name', 'Un prestataire')} est disponible" + (" sous conditions" if r["reply"] == "conditional" else ""),
                        "detail": f"{lab.get(req['category_key'], '')} le {req['date'][8:]}/{req['date'][5:7]} à {req.get('venue_city', '')} — {price_text(r['vat_mode'], r['vat_rate'], r['total_ht'], r['total_ttc'])}."})
    soon = (datetime.now(PARIS) + timedelta(days=30)).strftime("%Y-%m-%d")
    async for d in db.provider_documents.find({"org_id": org_id, "type": "urssaf", "expires_at": {"$gt": "", "$lte": soon}}, {"_id": 0}):
        out.append({"type": "prestataire", "severity": "warning", "event_id": None, "provider_id": d["provider_id"], "title": "Attestation URSSAF à renouveler",
                    "detail": f"{d.get('provider_name', 'Prestataire')} : échéance le {d['expires_at'][8:]}/{d['expires_at'][5:7]}/{d['expires_at'][:4]}."})
    return out
