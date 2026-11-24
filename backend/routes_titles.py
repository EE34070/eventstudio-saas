"""Titres d'événement et de devis traduisibles + données du devis telles que le client les voit."""
import os
import re
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core import Ctx, db, need, now_iso
from i18n import LANGS
from routes_pack_i18n import chain
from security import DATA_GUARD

router = APIRouter(prefix="/api")
FIN = need("finance:read")


def ev_title(ev: dict, lang: str) -> str:
    t = ev.get("title_translations") or {}
    if (lang or "fr").startswith("fr"):
        return ev.get("title", "")
    return next((t[l]["title"] for l in chain(lang) if (t.get(l) or {}).get("title")), ev.get("title", ""))


async def quote_title(q: dict, ev: dict | None = None) -> str:
    lang, own = q.get("language") or "fr-FR", q.get("title_translations") or {}
    if own.get(lang):
        return own[lang]
    if lang.startswith("fr"):
        return q.get("event_title", "")
    if ev is None:
        ev = await db.events.find_one({"org_id": q["org_id"], "id": q.get("event_id") or "-"}, {"_id": 0, "title": 1, "title_translations": 1}) or {}
    return next((own[l] for l in chain(lang) if own.get(l)), "") or (ev_title(ev, lang) if ev.get("title") else q.get("event_title", ""))


def validity(q: dict, org: dict) -> str:
    """Jamais de validité antérieure à la date d'émission (cas des devis importés)."""
    d, vu = q.get("date") or "", q.get("valid_until") or ""
    if vu and vu >= d:
        return vu
    return (date.fromisoformat(d[:10]) + timedelta(days=org.get("quote_validity_days") or 30)).isoformat() if len(d) >= 10 else vu


def client_notes(notes: str) -> str:
    return "\n".join(l for l in (notes or "").split("\n") if not l.strip().startswith("Réf. Odoo")).strip()


async def client_doc(doc: dict, org: dict) -> dict:
    ev = await db.events.find_one({"org_id": doc["org_id"], "id": doc.get("event_id") or "-"}, {"_id": 0, "title": 1, "title_translations": 1, "venue_id": 1}) or {}
    v = await db.venues.find_one({"org_id": doc["org_id"], "id": ev.get("venue_id") or "-"}, {"_id": 0, "name": 1, "city": 1}) or {}
    c = await db.contacts.find_one({"org_id": doc["org_id"], "id": doc.get("client_id") or "-"}, {"_id": 0, "kind": 1}) or {}
    return {**doc, "event_title": await quote_title(doc, ev), "venue_line": ", ".join(x for x in (v.get("name"), v.get("city")) if x), "valid_until": validity(doc, org),
            "notes": client_notes(doc.get("notes", "")), "client_pro": c.get("kind") not in (None, "", "particulier")}


def _view(title: str, tr: dict, own: dict | None = None) -> dict:
    rows = []
    for l, n in LANGS.items():
        if l == "fr-FR" and own is None:
            continue
        t = tr.get(l) or {}
        rows.append({"code": l, "label": n, "title": (own or {}).get(l, "") if own is not None else t.get("title", ""), "inherited": title if l == "fr-FR" else ev_title({"title": title, "title_translations": tr}, l),
                     "state": "complete" if t.get("title") or (own or {}).get(l) else "absent", "stale": own is None and bool(t.get("title")) and t.get("source") != title})
    return {"title": title, "languages": rows}


class TitleIn(BaseModel):
    lang: str
    title: str = Field("", max_length=200)


@router.get("/events/{eid}/title-translations")
async def get_ev(eid: str, ctx: Ctx = Depends(need("events:read"))):
    ev = await ctx.get("events", eid, ctx.event_scope())
    return _view(ev["title"], ev.get("title_translations") or {})


@router.put("/events/{eid}/title-translations")
async def put_ev(eid: str, body: TitleIn, ctx: Ctx = Depends(need("events:write"))):
    ev = await ctx.get("events", eid, ctx.event_scope())
    if body.lang not in LANGS or body.lang == "fr-FR":
        raise HTTPException(400, "Langue inconnue")
    await db.events.update_one(ctx.q({"id": eid}), {"$set": {f"title_translations.{body.lang}": {"title": body.title.strip(), "source": ev["title"], "updated_at": now_iso()}}})
    return await get_ev(eid, ctx)


@router.post("/events/{eid}/title-translations/ai")
async def ai_ev(eid: str, body: TitleIn, ctx: Ctx = Depends(need("events:write"))):
    """Brouillon à relire : rien n'est enregistré."""
    ev = await ctx.get("events", eid, ctx.event_scope())
    if body.lang not in LANGS or body.lang == "fr-FR":
        raise HTTPException(400, "Langue inconnue")
    import messaging_core as mc
    try:
        r = await mc.claude().messages.create(model=os.environ.get("LLM_MODEL") or os.environ.get("CLAUDE_REPLY_MODEL") or "claude-sonnet-5-5", max_tokens=200, messages=[{"role": "user", "content": ev["title"]}],
                                              system=f"{DATA_GUARD} Traduis ce titre d'événement du français vers {LANGS[body.lang]}, naturellement, en gardant les prénoms tels quels. Réponds uniquement par le titre traduit.")
        return {"title": "".join(b.text for b in r.content if b.type == "text").strip()[:200]}
    except Exception as exc:
        mc.ai_fail(exc)


@router.get("/quotes/{qid}/title-translations")
async def get_q(qid: str, ctx: Ctx = Depends(FIN)):
    q = await ctx.get("quotes", qid)
    ev = await db.events.find_one(ctx.q({"id": q.get("event_id") or "-"}), {"_id": 0, "title": 1, "title_translations": 1}) or {}
    return {**_view(ev.get("title") or q.get("event_title", ""), ev.get("title_translations") or {}, q.get("title_translations") or {}), "language": q.get("language") or "fr-FR"}


@router.put("/quotes/{qid}/title-translations")
async def put_q(qid: str, body: TitleIn, ctx: Ctx = Depends(FIN)):
    from routes_billing import quote_writer
    quote_writer(ctx)
    await ctx.get("quotes", qid)
    if body.lang not in LANGS:
        raise HTTPException(400, "Langue inconnue")
    await db.quotes.update_one(ctx.q({"id": qid}), {"$set": {f"title_translations.{body.lang}": body.title.strip()}})
    return await get_q(qid, ctx)


def cgv(org: dict, lang: str) -> dict:
    """CGV de la langue du devis : français pour fr, anglais pour toute autre langue. Pas de repli."""
    k = "fr" if (lang or "fr").startswith("fr") else "en"
    return {"lang": k, "text": (org.get("terms") if k == "fr" else org.get("terms_en")) or "", "file": (org.get(f"terms_file_{k}") or {}).get("id", "")}


async def warnings(q: dict, org: dict) -> list:
    out, lang = [], q.get("language") or "fr-FR"
    c = cgv(org, lang)
    if not c["text"] and not c["file"]:
        out.append(f"Aucune CGV {'française' if c['lang'] == 'fr' else 'anglaise'} n'est enregistrée (Entreprise) : ce devis partira sans conditions générales de vente.")
    if q.get("valid_until") and q["valid_until"] < (q.get("date") or ""):
        d = validity(q, org)
        out.append(f"La validité enregistrée ({q['valid_until'][8:10]}/{q['valid_until'][5:7]}/{q['valid_until'][:4]}) est antérieure à la date d'émission : le client verra {d[8:10]}/{d[5:7]}/{d[:4]}.")
    if not lang.startswith("fr"):
        ev = await db.events.find_one({"org_id": q["org_id"], "id": q.get("event_id") or "-"}, {"_id": 0, "title": 1, "title_translations": 1}) or {}
        own, t = q.get("title_translations") or {}, ev.get("title_translations") or {}
        if not any(own.get(l) or (t.get(l) or {}).get("title") for l in LANGS if l[:2] == lang[:2]):
            out.append(f"Le titre « {q.get('event_title', '')} » n'est pas traduit en {LANGS.get(lang, lang)} — le client verra : « {await quote_title(q, ev)} ».")
    return out
