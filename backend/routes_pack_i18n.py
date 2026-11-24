"""Packs multilingues, versions de pack, et révisions des devis acceptés classées en 3 niveaux."""
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import routes_quote_blocks as qb
from core import Ctx, db, link_doc, need, new_id, now_iso
from i18n import LANGS
from routes_billing import quote_writer, totals
from security import APP_ENV, DATA_GUARD

router = APIRouter(prefix="/api")
CAT, FIN = need("catalog:write"), need("finance:read")
GROUPS = {"fr": ("Prestations incluses : ", "Matériel inclus : "), "en": ("Services included: ", "Equipment included: "), "es": ("Servicios incluidos: ", "Material incluido: "),
          "it": ("Servizi inclusi: ", "Materiale incluso: "), "de": ("Inklusive Leistungen: ", "Inklusive Ausstattung: ")}
OPENQ = ["brouillon", "envoye", "vu", "negociation"]


# ---------- Traductions ----------
def tr_all(e: dict) -> dict:
    """Traductions par langue ; les anciens champs *_en sont lus comme en-US tant qu'ils n'ont pas été remplacés."""
    t = {k: dict(v) for k, v in (e.get("translations") or {}).items()}
    if "en-US" not in t and (e.get("name_en") or e.get("description_en") or any(c.get("client_label_en") for c in e.get("components") or [])):
        t["en-US"] = {"name": e.get("name_en", ""), "client_description": e.get("description_en", ""), "notes_client": "", "labels": {c["equipment_id"]: c["client_label_en"] for c in e.get("components") or [] if c.get("client_label_en")}, "legacy": True}
    return t


def chain(lang: str) -> list:
    base = lang[:2]
    return [lang] + [l for l in LANGS if l[:2] == base and l != lang] + ([] if base == "en" else ["en-US", "en-GB"])


def pick(e: dict, lang: str) -> dict:
    t = tr_all(e)
    return next((t[l] for l in chain(lang) if (t.get(l) or {}).get("name")), {})


def source(e: dict) -> str:
    fr = (e.get("translations") or {}).get("fr-FR") or {}
    return hashlib.sha256(json.dumps([e.get("name"), fr.get("client_description") or e.get("description", ""), fr.get("notes_client", ""), [(c["equipment_id"], c.get("client_label", "")) for c in e.get("components") or [] if c.get("visible_client", True)]], ensure_ascii=False).encode()).hexdigest()[:16]


def state(e: dict, lang: str) -> str:
    t = tr_all(e).get(lang) or {}
    need_l = [c["equipment_id"] for c in e.get("components") or [] if c.get("visible_client", True) and c.get("client_label")]
    done = [bool(t.get("name"))] + [bool((t.get("labels") or {}).get(i)) for i in need_l]
    return "absent" if not any(done) else "complete" if all(done) else "partial"


def view(e: dict) -> dict:
    t, src = tr_all(e), source(e)
    fr = t.get("fr-FR") or {}
    return {"id": e["id"], "name": e["name"], "version": e.get("version") or 1, "versions": [{k: v.get(k) for k in ("version", "created_at", "author", "comment")} for v in e.get("versions") or []],
            "fr": {"name": e["name"], "client_description": fr.get("client_description") or e.get("description", ""), "notes_client": fr.get("notes_client", "")},
            "components": [{"equipment_id": c["equipment_id"], "client_label": c.get("client_label", ""), "qty": c["qty"]} for c in e.get("components") or [] if c.get("visible_client", True)],
            "languages": [{"code": l, "label": n, "state": state(e, l), "stale": bool(t.get(l)) and not t[l].get("legacy") and t[l].get("source") != src, **{k: (t.get(l) or {}).get(k, "" if k != "labels" else {}) for k in ("name", "client_description", "notes_client", "labels")}}
                          for l, n in LANGS.items() if l != "fr-FR"]}


@router.get("/equipment/{eid}/translations")
async def get_tr(eid: str, ctx: Ctx = Depends(need("events:read"))):
    return view(await ctx.get("equipment", eid))


class TrIn(BaseModel):
    lang: str
    name: str = Field("", max_length=300)
    client_description: str = Field("", max_length=2000)
    notes_client: str = Field("", max_length=1000)
    labels: Dict[str, str] = Field(default_factory=dict, max_length=60)


@router.put("/equipment/{eid}/translations")
async def put_tr(eid: str, body: TrIn, ctx: Ctx = Depends(CAT)):
    e = await ctx.get("equipment", eid)
    if body.lang not in LANGS:
        raise HTTPException(400, "Langue inconnue")
    data = {"name": body.name.strip(), "client_description": body.client_description, "notes_client": body.notes_client, "updated_at": now_iso()}
    if body.lang == "fr-FR":  # langue de référence : le nom reste celui de la fiche
        data.pop("name")
    else:
        data.update(labels={k: v[:160] for k, v in body.labels.items() if v.strip()}, source=source(e))
    await db.equipment.update_one(ctx.q({"id": eid}), {"$set": {f"translations.{body.lang}": data}})
    e = await ctx.get("equipment", eid)
    if body.lang == "fr-FR":
        return view(e)
    await db.equipment.update_one(ctx.q({"id": eid}), {"$set": {f"translations.{body.lang}.source": source(e)}})
    return view(await ctx.get("equipment", eid))


class AiIn(BaseModel):
    lang: str


@router.post("/equipment/{eid}/translations/ai")
async def ai_tr(eid: str, body: AiIn, ctx: Ctx = Depends(CAT)):
    """Brouillon à relire : rien n'est enregistré."""
    e = await ctx.get("equipment", eid)
    if body.lang not in LANGS or body.lang == "fr-FR":
        raise HTTPException(400, "Langue inconnue")
    v = view(e)
    src = {"name": v["fr"]["name"], "client_description": v["fr"]["client_description"], "notes_client": v["fr"]["notes_client"], "labels": {c["equipment_id"]: c["client_label"] for c in v["components"] if c["client_label"]}}
    import messaging_core as mc
    from routes_admin import _json
    try:
        r = await mc.claude().messages.create(model=os.environ.get("LLM_MODEL") or os.environ.get("CLAUDE_REPLY_MODEL") or "claude-sonnet-5-5", max_tokens=3000, messages=[{"role": "user", "content": json.dumps(src, ensure_ascii=False)}],
                                              system=f"{DATA_GUARD} Tu traduis du français vers {LANGS[body.lang]} les textes commerciaux d'un pack de prestation événementielle haut de gamme (ton premium, naturel, sans sur-promesse). Réponds uniquement par le même JSON, mêmes clés, valeurs traduites.")
        out = _json("".join(b.text for b in r.content if b.type == "text"))
    except Exception as exc:
        mc.ai_fail(exc)
    return {"name": str(out.get("name") or ""), "client_description": str(out.get("client_description") or ""), "notes_client": str(out.get("notes_client") or ""), "labels": {k: str(x) for k, x in (out.get("labels") or {}).items() if k in src["labels"]}}


async def localize(q: dict) -> dict:
    """Libellés client des lignes catalogue et des composants dans la langue du devis (repli : même langue, anglais, français)."""
    lang = q.get("language") or "fr-FR"
    if lang.startswith("fr") or not q.get("blocks"):
        return q
    ids = {b.get("equipment_id") for b in q["blocks"]} | {c.get("equipment_id") for b in q["blocks"] for c in b.get("pack_components") or []}
    eqs = {e["id"]: e async for e in db.equipment.find({"org_id": q["org_id"], "id": {"$in": [i for i in ids if i]}}, {"_id": 0})}
    out = []
    for b in q["blocks"]:
        e = eqs.get(b.get("equipment_id"))
        if b["type"] == "line" and e:
            t, fr = pick(e, lang), (e.get("translations") or {}).get("fr-FR") or {}
            b = {**b, "label": t["name"] if t.get("name") and b["label"] == e["name"] else b["label"],
                 "description": t["client_description"] if t.get("client_description") and b.get("description", "") in ("", e.get("description", ""), fr.get("client_description", "")) else b.get("description", "")}
            if b.get("pack_components"):
                b["pack_components"] = [{**c, "loc": (t.get("labels") or {}).get(c.get("equipment_id")) or (not c.get("client_label") and pick(eqs.get(c.get("equipment_id")) or {}, lang).get("name")) or ""} for c in b["pack_components"]]
        out.append(b)
    return {**q, "blocks": out}


@router.get("/quotes/{qid}/translation-check")
async def tr_check(qid: str, ctx: Ctx = Depends(FIN)):
    q = await ctx.get("quotes", qid)
    lang = q.get("language") or "fr-FR"
    import routes_titles
    warn = await routes_titles.warnings(q, await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}) or {})
    if lang.startswith("fr"):
        return {"language": lang, "missing": [], "warnings": warn}
    ids = [b["equipment_id"] for b in q.get("blocks") or [] if b.get("pack_components") and b.get("equipment_id")]
    miss = []
    async for e in db.equipment.find(ctx.q({"id": {"$in": ids}}), {"_id": 0}):
        best = max((state(e, l) for l in chain(lang) if l[:2] == lang[:2]), key=["absent", "partial", "complete"].index)
        if best != "complete":
            fb = next((l for l in chain(lang) if l[:2] != lang[:2] and state(e, l) != "absent"), "fr-FR")
            miss.append({"equipment_id": e["id"], "name": e["name"], "state": best, "fallback": LANGS[fb]})
    return {"language": lang, "language_label": LANGS.get(lang, lang), "missing": miss, "warnings": warn}


# ---------- Classement 1 / 2 / 3 ----------
def client_view(blocks: list, gd: float) -> dict:
    by, out = {b["id"]: b for b in blocks}, {}
    for b in blocks:
        if b["type"] == "line":
            comps = {((c.get("equipment_id") if c.get("show_exact_reference") else ""), c.get("client_label") or c.get("name", "")): c["qty"] for c in b.get("pack_components") or [] if c.get("visible_client", True)} if b.get("show_components", True) else {}
            out[b["id"]] = {"label": b["label"], "description": b.get("description", ""), "qty": b["qty"], "price": qb._eff(b, qb._chain(by, b), gd), "vat": b["vat"], "comps": comps}
    return out


def classify(old: list, new: list, gd: float, equivalent: bool = False) -> tuple:
    a, b, lv, diff, need_eq = client_view(old, gd), client_view(new, gd), 0, [], False

    def add(n: int, text: str) -> None:
        nonlocal lv
        lv = max(lv, n)
        diff.append({"level": n, "text": text})
    for i, x in a.items():
        if i not in b:
            add(3, f"Ligne retirée : {x['label']}")
    for i, y in b.items():
        x = a.get(i)
        if not x:
            add(3 if y["price"] * y["qty"] else 2, f"Ligne ajoutée : {y['label']}" + ("" if y["price"] * y["qty"] else " (offerte)"))
            continue
        if x["price"] != y["price"] or x["vat"] != y["vat"]:
            add(3, f"Prix modifié : {y['label']}")
        if x["qty"] != y["qty"]:
            add(3 if y["price"] or y["qty"] < x["qty"] else 2, f"Quantité {x['qty']:g} → {y['qty']:g} : {y['label']}")
        if (x["label"], x["description"]) != (y["label"], y["description"]):
            add(2, f"Libellé ou description reformulé : {y['label']}")
        gone, came = [k for k in x["comps"] if k not in y["comps"]], [k for k in y["comps"] if k not in x["comps"]]
        for k in gone[:len(came)]:
            need_eq = True
            add(2 if equivalent else 3, f"{y['label']} : « {k[1]} » remplacé par « {came[gone.index(k)][1]} »" + ("" if equivalent else " — cochez « Équivalent ou supérieur », sinon nouvelle signature"))
        for k in gone[len(came):]:
            add(3, f"{y['label']} : élément visible retiré « {k[1]} »")
        for k in came[len(gone):]:
            add(2, f"{y['label']} : élément visible ajouté « {k[1]} »")
        for k, n in y["comps"].items():
            if k in x["comps"] and n != x["comps"][k]:
                add(3 if n < x["comps"][k] else 2, f"{y['label']} : « {k[1]} » {x['comps'][k]:g} → {n:g}")
    if not lv and json.dumps(old, sort_keys=True, default=str) != json.dumps(new, sort_keys=True, default=str):
        add(1, "Composition technique interne modifiée (invisible pour le client)")
    return lv, diff, need_eq


async def snapshot(org_id: str, q: dict) -> None:
    """Copie en lecture seule de ce que le client a accepté."""
    await db.quotes.update_one({"org_id": org_id, "id": q["id"], "signed_snapshot": None}, {"$set": {"signed_snapshot": {"at": now_iso(), "blocks": q.get("blocks") or [], "lines": q.get("lines") or [], "total_ht": q.get("total_ht"), "total_ttc": q.get("total_ttc")}}})


def manager(ctx: Ctx) -> None:
    quote_writer(ctx)
    if ctx.member.get("role") not in ("admin", "gerant"):
        raise HTTPException(403, "Réservé à l'administrateur et au gérant")


async def _write(org_id: str, q: dict, blocks: list, by: str) -> None:
    lines = qb.flatten(blocks, q.get("global_discount_percent", 0))
    await db.quotes.update_one({"org_id": org_id, "id": q["id"]}, {"$set": {"blocks": blocks, "lines": lines, **totals(lines), "updated_at": now_iso()}})
    if q.get("event_id"):
        import routes_quote_sync
        await routes_quote_sync.recalc_event(org_id, q["event_id"], by)


async def _journal(ctx: Ctx, q: dict, level: int, diff: list, **k) -> dict:
    return await ctx.insert("quote_revisions", {"quote_id": q["id"], "level": level, "diff": diff, "author": ctx.member.get("name", ""), "language": q.get("language") or "fr-FR", "number": "", "pdf_file_ref": "", "notified_at": None, "status": "applied", **k})


async def apply_change(ctx: Ctx, q: dict, blocks: list, level: int = 0, equivalent: bool = False, mode: str = "") -> dict:
    if q["status"] != "accepte" or q.get("active") is False:
        raise HTTPException(400, "Les révisions concernent la version acceptée du devis")
    await snapshot(ctx.org_id, q)
    lv, diff, _ = classify(q.get("blocks") or [], blocks, q.get("global_discount_percent", 0), equivalent)
    lv = max(lv, level if lv else 0)  # reclassement possible vers plus strict uniquement
    by = ctx.member.get("name", "")
    if lv == 0:
        return {"level": 0, "diff": []}
    if lv == 1:
        await _write(ctx.org_id, q, blocks, by)
        return await _journal(ctx, q, 1, diff)
    if lv == 2:
        await _write(ctx.org_id, q, blocks, by)
        n = await db.quote_revisions.count_documents(ctx.q({"quote_id": q["id"], "level": 2})) + 1
        from routes_billing import quote_pdf_bytes
        from routes_files import store_bytes
        nq = await ctx.get("quotes", q["id"])
        number = f"V{q.get('version', 1)}.{n}"
        pdf = await quote_pdf_bytes(await qb.pdf_doc(nq), await db.orgs.find_one({"id": ctx.org_id}, {"_id": 0}) or {})
        ref = await store_bytes(ctx.org_id, pdf, "application/pdf", f"{q['number']}-{number}.pdf", by)
        en, to = (q.get("language") or "fr").startswith("en"), (q.get("client") or {}).get("email", "")
        subject = f"Your quote {q['number']} has been updated — no action required" if en else f"Votre devis {q['number']} a été mis à jour — aucune action requise"
        if APP_ENV == "production" and to:
            from emailer import send_email
            await send_email(to=to, subject=subject, html=f"<p>{subject}.</p>")
        return await _journal(ctx, q, 2, diff, number=number, pdf_file_ref=ref, notified_at=now_iso(), notification={"to": to, "subject": subject, "sent": APP_ENV == "production" and bool(to)})
    if mode == "v2":
        import routes_quote_docs
        doc = await routes_quote_docs.new_version(q["id"], ctx)
        await _write(ctx.org_id, doc, blocks, by)
        return {**await _journal(ctx, q, 3, diff, status="v2", new_quote_id=doc["id"]), "new_quote_id": doc["id"]}
    if mode == "avenant":
        await db.quote_revisions.update_many(ctx.q({"quote_id": q["id"], "status": "pending"}), {"$set": {"status": "replaced"}})
        lines = qb.flatten(blocks, q.get("global_discount_percent", 0))
        return await _journal(ctx, q, 3, diff, status="pending", blocks=blocks, new_totals=totals(lines))
    return {"level": 3, "diff": diff, "status": "blocked", "message": "Changement contractuel : créez une V2 à signer ou un avenant à faire accepter par le client"}


class RevIn(BaseModel):
    blocks: List[qb.Block] = Field(min_length=1, max_length=400)
    level: Literal[0, 1, 2, 3] = 0
    equivalent: bool = False
    mode: Literal["", "v2", "avenant"] = ""
    preview: bool = False


@router.post("/quotes/{qid}/revision")
async def revision(qid: str, body: RevIn, ctx: Ctx = Depends(FIN)):
    manager(ctx)
    q = await ctx.get("quotes", qid)
    blocks = [b.model_dump() for b in body.blocks]
    if body.preview:
        lv, diff, need_eq = classify(q.get("blocks") or [], blocks, q.get("global_discount_percent", 0), body.equivalent)
        return {"level": lv, "diff": diff, "needs_equivalent": need_eq}
    return await apply_change(ctx, q, blocks, body.level, body.equivalent, body.mode)


@router.get("/quotes/{qid}/revisions")
async def revisions(qid: str, ctx: Ctx = Depends(FIN)):
    q = await ctx.get("quotes", qid)
    rows = await ctx.list("quote_revisions", {"quote_id": qid}, sort=[("created_at", -1)], limit=100)
    return {"signed_at": (q.get("signed_snapshot") or {}).get("at", ""), "revisions": [{k: v for k, v in r.items() if k not in ("blocks", "otp_hash", "otp_salt")} for r in rows]}


# ---------- Avenant simplifié : acceptation en ligne par code ----------
async def _pending(token: str) -> tuple:
    q = await link_doc("quotes", token)
    r = await db.quote_revisions.find_one({"org_id": q["org_id"], "quote_id": q["id"], "status": "pending"}, {"_id": 0}) if q else None
    if not r:
        raise HTTPException(404, "Aucun avenant en attente")
    return q, r


def _h(salt: str, code: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode()).hexdigest()


@router.get("/public/quotes/{token}/amendment")
async def pub_amendment(token: str):
    q, r = await _pending(token)
    return {"number": q["number"], "changes": [d["text"] for d in r["diff"] if d["level"] > 1], "total_ttc_before": q["total_ttc"], "total_ttc_after": r["new_totals"]["total_ttc"], "code_sent": bool(r.get("otp_hash"))}


@router.post("/public/quotes/{token}/amendment/request")
async def pub_amendment_code(token: str):
    q, r = await _pending(token)
    if r.get("otp_sent_at", "") > (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat():
        raise HTTPException(429, "Un code vient d'être envoyé : patientez une minute")
    code, salt, to = f"{secrets.randbelow(10 ** 6):06d}", secrets.token_hex(8), (q.get("client") or {}).get("email", "")
    await db.quote_revisions.update_one({"org_id": q["org_id"], "id": r["id"]}, {"$set": {"otp_hash": _h(salt, code), "otp_salt": salt, "otp_tries": 0, "otp_sent_at": now_iso(), "otp_expires": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}})
    if APP_ENV == "production" and to:
        from emailer import send_email
        await send_email(to=to, subject=f"Code de confirmation — avenant au devis {q['number']}", html=f"<p>Votre code : <b>{code}</b> (valable 15 minutes).</p>")
    return {"sent_to": (to[:2] + "…" + to[to.find("@"):]) if "@" in to else ""}


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)


@router.post("/public/quotes/{token}/amendment/confirm")
async def pub_amendment_ok(token: str, body: CodeIn):
    q, r = await _pending(token)
    key = {"org_id": q["org_id"], "id": r["id"]}
    if not r.get("otp_hash") or r.get("otp_expires", "") < now_iso() or r.get("otp_tries", 0) >= 5:
        raise HTTPException(400, "Code expiré : demandez-en un nouveau")
    if not secrets.compare_digest(_h(r["otp_salt"], body.code), r["otp_hash"]):
        await db.quote_revisions.update_one(key, {"$inc": {"otp_tries": 1}})
        raise HTTPException(400, "Code incorrect")
    await _write(q["org_id"], q, r["blocks"], "Client (avenant)")
    await db.quote_revisions.update_one(key, {"$set": {"status": "accepted", "client_ack": now_iso()}, "$unset": {"otp_hash": "", "otp_salt": ""}})
    return {"ok": True}


# ---------- Versions de pack et propagation ----------
async def bump(ctx: Ctx, e: dict, comment: str = "", first: bool = False) -> int:
    v = (e.get("version") or 1) + (0 if first else 1)
    await db.equipment.update_one(ctx.q({"id": e["id"]}), {"$set": {"version": v}, "$push": {"versions": {"$each": [{"version": v, "created_at": now_iso(), "author": ctx.member.get("name", ""), "comment": comment[:300], "components": e.get("components") or []}], "$slice": -30}}})
    return v


async def _rebuilt(ctx: Ctx, e: dict, q: dict, overwrite: bool) -> tuple:
    eqs = {x["id"]: x async for x in db.equipment.find(ctx.q({"id": {"$in": [c["equipment_id"] for c in e.get("components") or []]}}), {"_id": 0, "id": 1, "name": 1, "product_type": 1})}
    out, kept = [], 0
    for b in q.get("blocks") or []:
        if b["type"] == "line" and b.get("equipment_id") == e["id"] and b.get("pack_components") is not None and (b.get("pack_version") or 1) < (e.get("version") or 1):
            old = {c["equipment_id"]: c for c in b["pack_components"]}
            comps = []
            for c in e.get("components") or []:
                o = old.get(c["equipment_id"]) or {}
                adj = not overwrite and o and o.get("qty") != o.get("base_qty", o.get("qty"))
                kept += bool(adj)
                comps.append({"equipment_id": c["equipment_id"], "qty": o["qty"] if adj else c["qty"], "base_qty": c["qty"], "visible_client": c.get("visible_client", True), "client_label": c.get("client_label", ""), "client_label_en": c.get("client_label_en", ""),
                              "show_exact_reference": bool(c.get("show_exact_reference")), "name": (eqs.get(c["equipment_id"]) or {}).get("name", ""), "service": (eqs.get(c["equipment_id"]) or {}).get("product_type") in ("Service", "Prestation artistique")})
            b = {**b, "pack_components": comps, "pack_version": e.get("version") or 1}
        out.append(b)
    return out, kept


async def _targets(ctx: Ctx, e: dict, past: bool, overwrite: bool = False) -> list:
    today, rows = datetime.now(timezone.utc).date().isoformat(), []
    async for q in db.quotes.find(ctx.q({"blocks.equipment_id": e["id"], "active": {"$ne": False}, "status": {"$in": OPENQ + ["accepte"]}}), {"_id": 0}).sort("event_date", 1):
        if not past and q.get("event_date") and q["event_date"] < today:
            continue
        blocks, kept = await _rebuilt(ctx, e, q, overwrite)
        if blocks == (q.get("blocks") or []):
            continue
        lv, diff, need_eq = classify(q["blocks"], blocks, q.get("global_discount_percent", 0)) if q["status"] == "accepte" else (0, [], False)
        rows.append({"q": q, "blocks": blocks, "row": {"id": q["id"], "number": q["number"], "client": (q.get("client") or {}).get("name", ""), "event_date": q.get("event_date", ""), "status": q["status"], "level": lv, "diff": diff, "needs_equivalent": need_eq, "kept_adjustments": kept}})
    return rows


@router.get("/equipment/{eid}/pack/quotes")
async def pack_quotes(eid: str, past: bool = False, ctx: Ctx = Depends(FIN)):
    e = await ctx.get("equipment", eid)
    return {"version": e.get("version") or 1, "quotes": [t["row"] for t in await _targets(ctx, e, past)]}


class ApplyIn(BaseModel):
    quote_ids: List[str] = Field(min_length=1, max_length=200)
    overwrite: bool = False
    equivalent_ids: List[str] = Field(default_factory=list, max_length=200)
    past: bool = False


@router.post("/equipment/{eid}/pack/apply")
async def pack_apply(eid: str, body: ApplyIn, ctx: Ctx = Depends(FIN)):
    """Le prix d'une ligne n'est jamais modifié ici ; les niveaux 3 ne sont pas appliqués en masse."""
    manager(ctx)
    e, out = await ctx.get("equipment", eid), []
    for t in await _targets(ctx, e, body.past, body.overwrite):
        q = t["q"]
        if q["id"] not in body.quote_ids:
            continue
        if q["status"] != "accepte":
            await _write(ctx.org_id, q, t["blocks"], ctx.member.get("name", ""))
            out.append({"id": q["id"], "number": q["number"], "result": "updated", "resend": q["status"] != "brouillon"})
            continue
        lv, _, _ = classify(q["blocks"], t["blocks"], q.get("global_discount_percent", 0), q["id"] in body.equivalent_ids)
        if lv == 3:
            out.append({"id": q["id"], "number": q["number"], "result": "level3", "level": 3})
            continue
        r = await apply_change(ctx, q, t["blocks"], 0, q["id"] in body.equivalent_ids)
        out.append({"id": q["id"], "number": q["number"], "result": "applied", "level": r["level"], "revision": r.get("number", "")})
    return out
