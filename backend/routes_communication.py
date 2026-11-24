"""Communication (étapes 1 à 5) : marques, médiathèque, collectes photo, crédits Instagram, Studio et calendrier en rappel manuel. Ni Meta, ni Canva, ni statistiques."""
import hashlib
import io
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta
from typing import List, Literal, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

import messaging_core as mc
import routes_files as rf
from core import Ctx, audit, db, ensure_link, link_doc, need, new_id, now_iso
from security import DATA_GUARD, PROD

router = APIRouter(prefix="/api")
R, W = need("comms:view"), need("comms:manage")
BRANDS = [{"id": "exclusivity_events", "name": "Exclusivity Events"}, {"id": "le_frenchie", "name": "Le Frenchie"}, {"id": "exclusivity_music", "name": "Exclusivity Music"}]
REMINDER_DAYS = [3, 14, 30, 45]
MESSAGE = "Nous serions ravis de recevoir vos photos et vidéos de cet événement afin de les partager, avec votre crédit, sur nos réseaux."
TMP = os.path.join(tempfile.gettempdir(), "comm_uploads")
CHUNK, IMG_MAX, VID_MAX = 5 * 1024 * 1024, 40 * 1024 * 1024, 200 * 1024 * 1024
VIDEO_EXT = {"mp4", "mov", "webm"}
EXT = {"jpg", "jpeg", "png", "webp", "heic", "heif"} | VIDEO_EXT
RIGHTS = {"ok": "Droits accordés", "to_confirm": "Droits à confirmer", "refused": "Droits refusés"}
DAY = r"^(\d{4}-\d{2}-\d{2})?$"


def today() -> str:
    return datetime.now(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%d")


def plus(day: str, n: int) -> str:
    return (datetime.strptime(day[:10], "%Y-%m-%d") + timedelta(days=n)).strftime("%Y-%m-%d")


def fr(day: str) -> str:
    return f"{day[8:10]}/{day[5:7]}/{day[:4]}" if day else ""


def handle_of(s: str, strict: bool = False) -> str:
    s = re.sub(r"^https?://(www\.)?instagram\.com/", "", (s or "").strip(), flags=re.I).strip("/@ ").split("/")[0].split("?")[0]
    if s and not re.fullmatch(r"[A-Za-z0-9._]{1,30}", s):
        if strict:
            raise HTTPException(400, "Identifiant Instagram invalide (lettres, chiffres, points et tirets bas, 30 caractères au plus)")
        return ""
    return s


async def settings(org_id: str) -> dict:
    d = await db.comm_settings.find_one({"org_id": org_id}, {"_id": 0}) or {}
    saved = {b["id"]: b for b in d.get("brands") or []}
    return {"brands": [{**b, "handle": saved.get(b["id"], {}).get("handle", ""), "hashtags": saved.get(b["id"], {}).get("hashtags", [])} for b in BRANDS],
            "reminder_days": d.get("reminder_days") or REMINDER_DAYS, "request_message": d.get("request_message") or MESSAGE}


def brand_ok(bid: str) -> str:
    if bid and bid not in {b["id"] for b in BRANDS}:
        raise HTTPException(400, "Marque inconnue")
    return bid


# ---------- Vue d'ensemble et réglages ----------
class BrandIn(BaseModel):
    id: str
    handle: str = Field("", max_length=80)
    hashtags: List[str] = Field([], max_length=30)


class SettingsIn(BaseModel):
    brands: List[BrandIn] = []
    reminder_days: List[int] = Field(REMINDER_DAYS, min_length=1, max_length=6)
    request_message: str = Field("", max_length=1500)


@router.get("/communication/overview")
async def overview(ctx: Ctx = Depends(R)):
    evs = await db.events.find(ctx.q({}), {"_id": 0, "id": 1, "title": 1, "start": 1}).sort("start", -1).to_list(400)
    n = lambda c, f=None: db[c].count_documents(ctx.q({"deleted_at": None, **(f or {})}))  # noqa: E731
    return {**await settings(ctx.org_id), "events": evs, "write": ctx.can("comms:manage"), "ai": mc.ai_ready(), "video": bool(ffmpeg()), "sending": PROD,
            "counts": {"media": await n("media_assets"), "requests_open": await n("media_requests", {"status": {"$in": ["a_envoyer", "demandee"]}}), "posts_planned": await n("comm_posts", {"status": "planifie"})},
            "connectors": [{"key": "meta", "label": "Meta (publication Instagram / Facebook)"}, {"key": "canva", "label": "Canva (modèles)"}, {"key": "stats", "label": "Statistiques"}]}


@router.put("/communication/settings")
async def put_settings(body: SettingsIn, ctx: Ctx = Depends(W)):
    brands = [{"id": brand_ok(b.id), "handle": handle_of(b.handle, True), "hashtags": [h.strip().lstrip("#") for h in b.hashtags if h.strip()]} for b in body.brands]
    days = sorted({d for d in body.reminder_days if 0 < d <= 365})
    await db.comm_settings.update_one({"org_id": ctx.org_id}, {"$set": {"brands": brands, "reminder_days": days or REMINDER_DAYS, "request_message": body.request_message.strip(), "updated_at": now_iso()}}, upsert=True)
    await audit(ctx.org_id, ctx.member, "comm_settings", "Réglages Communication")
    return await settings(ctx.org_id)


# ---------- Import par morceaux, conversions, dédoublonnage ----------
class UploadIn(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    size: int = Field(gt=0, le=VID_MAX)


def ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            exe = ""
    return exe or ""


def sniff(head: bytes) -> str:
    if head[:2] == b"\xff\xd8":
        return "image/jpeg"
    if head[:4] == b"\x89PNG":
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"
    if head[4:8] == b"ftyp":
        b = head[8:12]
        return "image/heic" if b in (b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"heim", b"heis") else "video/quicktime" if b.strip() == b"qt" else "video/mp4"
    if head[4:8] in (b"moov", b"mdat", b"wide", b"free"):
        return "video/quicktime"
    return ""


def process(path: str) -> dict:
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        head = fh.read(16)
        fh.seek(0)
        for block in iter(lambda: fh.read(1 << 20), b""):
            sha.update(block)
    ctype = sniff(head)
    if not ctype:
        raise ValueError("Le contenu du fichier n'est ni une photo ni une vidéo reconnue")
    out = {"ctype": ctype, "sha": sha.hexdigest(), "duration": 0, "thumb": b""}
    if ctype.startswith("image/"):
        import pillow_heif
        from PIL import Image, ImageOps
        pillow_heif.register_heif_opener()
        if os.path.getsize(path) > IMG_MAX:
            raise ValueError("Photo trop volumineuse (40 Mo maximum)")
        im = ImageOps.exif_transpose(Image.open(path))
        out.update(kind="image", width=im.size[0], height=im.size[1], ext={"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(ctype, "jpg"))
        if ctype == "image/heic":
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=92)
            out.update(data=buf.getvalue(), ctype="image/jpeg", converted="HEIC → JPEG")
        else:
            with open(path, "rb") as fh:
                out["data"] = fh.read()
        t = im.convert("RGB")
        t.thumbnail((640, 640))
        buf = io.BytesIO()
        t.save(buf, "JPEG", quality=80)
        out["thumb"] = buf.getvalue()
        return out
    exe = ffmpeg()
    out.update(kind="video", width=0, height=0, ext={"video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm"}[ctype])
    if exe:
        err = subprocess.run([exe, "-hide_banner", "-i", path], capture_output=True, text=True, timeout=60, errors="ignore").stderr
        d, s = re.search(r"Duration: (\d+):(\d+):(\d+\.?\d*)", err), re.search(r"Video:.*?\b(\d{2,5})x(\d{2,5})\b", err)
        if not s:
            raise ValueError("Vidéo illisible")
        out.update(duration=round(int(d[1]) * 3600 + int(d[2]) * 60 + float(d[3]), 1) if d else 0, width=int(s[1]), height=int(s[2]))
        cover = path + ".jpg"
        subprocess.run([exe, "-y", "-hide_banner", "-ss", str(min(1, out["duration"] / 2)), "-i", path, "-frames:v", "1", "-vf", "scale=640:-2", cover], capture_output=True, timeout=120)
        if os.path.exists(cover):
            with open(cover, "rb") as fh:
                out["thumb"] = fh.read()
    with open(path, "rb") as fh:
        out["data"] = fh.read()
    return out


async def put(org_id: str, data: bytes, ctype: str, ext: str, filename: str, by: str) -> str:
    fid = new_id()
    try:
        res = await run_in_threadpool(rf._put, f"{rf.APP_NAME}/{org_id}/{fid}.{ext}", data, ctype)
    except Exception:
        raise HTTPException(502, "Stockage indisponible, réessayez")
    await db.files.insert_one({"id": fid, "org_id": org_id, "storage_path": res, "filename": filename[:200], "content_type": ctype, "size": len(data), "is_deleted": False, "created_by": by, "created_at": now_iso()})
    return f"file:{fid}"


async def start_upload(org_id: str, body: UploadIn, by: str) -> dict:
    ext = body.filename.rsplit(".", 1)[-1].lower() if "." in body.filename else ""
    if ext not in EXT:
        raise HTTPException(400, "Format non accepté (JPEG, PNG, WebP, HEIC, MP4, MOV ou WebM)")
    if ext not in VIDEO_EXT and body.size > IMG_MAX:
        raise HTTPException(413, "Photo trop volumineuse (40 Mo maximum)")
    u = {"id": new_id(), "org_id": org_id, "filename": body.filename, "size": body.size, "chunks": -(-body.size // CHUNK), "by": by, "created_at": now_iso(), "done_at": None}
    await db.media_uploads.insert_one({**u})
    return {"id": u["id"], "chunk_size": CHUNK, "chunks": u["chunks"]}


async def put_chunk(org_id: str, uid: str, n: int, request: Request) -> dict:
    u = await db.media_uploads.find_one({"id": uid, "org_id": org_id, "done_at": None}, {"_id": 0})
    if not u or not 0 <= n < u["chunks"]:
        raise HTTPException(404, "Envoi introuvable")
    data = await request.body()
    if not data or len(data) > CHUNK:
        raise HTTPException(413, "Morceau invalide")
    os.makedirs(os.path.join(TMP, u["id"]), exist_ok=True)
    with open(os.path.join(TMP, u["id"], str(n)), "wb") as fh:
        fh.write(data)
    return {"ok": True}


async def finish_upload(org_id: str, uid: str, meta: dict) -> dict:
    u = await db.media_uploads.find_one({"id": uid, "org_id": org_id, "done_at": None}, {"_id": 0})
    if not u:
        raise HTTPException(404, "Envoi introuvable")
    d = os.path.join(TMP, u["id"])
    parts, path = [os.path.join(d, str(i)) for i in range(u["chunks"])], os.path.join(d, "file")
    if not all(os.path.exists(p) for p in parts):
        raise HTTPException(400, "Envoi incomplet : relancez le fichier")

    def work():
        with open(path, "wb") as dst:
            for p in parts:
                with open(p, "rb") as src:
                    shutil.copyfileobj(src, dst)
        if os.path.getsize(path) != u["size"]:
            raise ValueError("Envoi incomplet : relancez le fichier")
        return process(path)
    try:
        try:
            p = await run_in_threadpool(work)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception:
            raise HTTPException(400, "Fichier illisible")
        dup = await db.media_assets.find_one({"org_id": org_id, "sha256": p["sha"], "deleted_at": None}, {"_id": 0})
        if dup:
            return {**dup, "duplicate": True}
        a = {"id": new_id(), "org_id": org_id, "created_at": now_iso(), "file_ref": await put(org_id, p["data"], p["ctype"], p["ext"], u["filename"], u["by"]),
             "thumb_ref": await put(org_id, p["thumb"], "image/jpeg", "jpg", "vignette.jpg", u["by"]) if p["thumb"] else "", "kind": p["kind"], "filename": u["filename"], "size": len(p["data"]),
             "sha256": p["sha"], "width": p["width"], "height": p["height"], "duration": p["duration"], "content_type": p["ctype"], "converted": p.get("converted", ""), "event_id": "", "brand_id": "",
             "author_name": "", "author_handle": "", "author_contact_id": "", "rights": "to_confirm", "rights_note": "", "tags": [], "source": "import", "request_id": "", "uploaded_by": u["by"], "deleted_at": None, **meta}
        await db.media_assets.insert_one({**a})
        return {**a, "duplicate": False}
    finally:
        shutil.rmtree(d, ignore_errors=True)
        await db.media_uploads.update_one({"id": uid, "org_id": org_id}, {"$set": {"done_at": now_iso()}})


class CompleteIn(BaseModel):
    event_id: str = ""
    brand_id: str = ""
    author_name: str = Field("", max_length=120)
    author_handle: str = Field("", max_length=80)
    rights: Literal["ok", "to_confirm", "refused"] = "to_confirm"


@router.post("/communication/uploads")
async def new_upload(body: UploadIn, ctx: Ctx = Depends(W)):
    return await start_upload(ctx.org_id, body, ctx.member.get("name") or "")


@router.put("/communication/uploads/{uid}/chunks/{n}")
async def upload_chunk(uid: str, n: int, request: Request, ctx: Ctx = Depends(W)):
    return await put_chunk(ctx.org_id, uid, n, request)


@router.post("/communication/uploads/{uid}/complete")
async def complete_upload(uid: str, body: CompleteIn, ctx: Ctx = Depends(W)):
    if body.event_id:
        await ctx.get("events", body.event_id)
    a = await finish_upload(ctx.org_id, uid, {**body.model_dump(), "brand_id": brand_ok(body.brand_id), "author_handle": handle_of(body.author_handle, True)})
    return (await states(ctx.org_id, [a]))[0]


# ---------- Médiathèque ----------
def state(a: dict, ce: Optional[dict], day: str) -> dict:
    why = [] if a["rights"] == "ok" else [RIGHTS[a["rights"]]]
    if a.get("event_id"):
        c = (ce or {}).get("consent") or "a_demander"
        if c != "accorde":
            why.append("Publication refusée par le client" if c == "refuse" else "Accord du client à demander")
        if ((ce or {}).get("embargo_date") or "") > day:
            why.append(f"Sous embargo jusqu'au {fr(ce['embargo_date'])}")
    return {**a, "status": "bloque" if why else "publiable", "blocked_reasons": why}


async def states(org_id: str, rows: list) -> list:
    eids = list({a["event_id"] for a in rows if a.get("event_id")})
    ces = {c["event_id"]: c async for c in db.comm_events.find({"org_id": org_id, "event_id": {"$in": eids}}, {"_id": 0})}
    titles = {e["id"]: e.get("title", "") async for e in db.events.find({"org_id": org_id, "id": {"$in": eids}}, {"_id": 0, "id": 1, "title": 1})}
    day = today()
    return [{**state(a, ces.get(a.get("event_id")), day), "event_title": titles.get(a.get("event_id"), "")} for a in rows]


class MediaPatch(BaseModel):
    event_id: Optional[str] = None
    brand_id: Optional[str] = None
    author_name: Optional[str] = Field(None, max_length=120)
    author_handle: Optional[str] = Field(None, max_length=80)
    rights: Optional[Literal["ok", "to_confirm", "refused"]] = None
    rights_note: Optional[str] = Field(None, max_length=500)
    tags: Optional[List[str]] = Field(None, max_length=30)


class BulkIn(BaseModel):
    ids: List[str] = Field(min_length=1, max_length=500)
    patch: MediaPatch


async def _patch(ctx: Ctx, p: MediaPatch) -> dict:
    d = p.model_dump(exclude_none=True)
    if d.get("event_id"):
        await ctx.get("events", d["event_id"])
    if "brand_id" in d:
        brand_ok(d["brand_id"])
    if "author_handle" in d:
        d["author_handle"] = handle_of(d["author_handle"], True)
    if "rights" in d:
        d.update(rights_by=ctx.member.get("name"), rights_at=now_iso())
    return d


@router.get("/communication/media")
async def list_media(event_id: str = "", brand_id: str = "", kind: str = "", status: str = "", q: str = "", ctx: Ctx = Depends(R)):
    f = {"deleted_at": None, **({"event_id": event_id} if event_id else {}), **({"brand_id": brand_id} if brand_id else {}), **({"kind": kind} if kind else {})}
    rows = await states(ctx.org_id, await ctx.list("media_assets", f, sort=[("created_at", -1)], limit=3000))
    ql = q.strip().lower()
    return [a for a in rows if (not status or a["status"] == status) and (not ql or ql in f"{a['filename']} {a['author_name']} {a['author_handle']} {a['event_title']} {' '.join(a['tags'])}".lower())]


@router.put("/communication/media/bulk")
async def bulk_media(body: BulkIn, ctx: Ctx = Depends(W)):
    d = await _patch(ctx, body.patch)
    if d:
        await db.media_assets.update_many(ctx.q({"id": {"$in": body.ids}, "deleted_at": None}), {"$set": {**d, "updated_at": now_iso()}})
    return {"updated": len(body.ids)}


@router.put("/communication/media/{aid}")
async def put_media(aid: str, body: MediaPatch, ctx: Ctx = Depends(W)):
    await ctx.get("media_assets", aid, {"deleted_at": None})
    return (await states(ctx.org_id, [await ctx.update("media_assets", aid, await _patch(ctx, body))]))[0]


@router.delete("/communication/media/{aid}")
async def del_media(aid: str, ctx: Ctx = Depends(W)):
    a = await ctx.get("media_assets", aid, {"deleted_at": None})
    if await db.comm_posts.find_one(ctx.q({"asset_ids": aid, "deleted_at": None, "status": {"$in": ["planifie", "pret"]}})):
        raise HTTPException(409, "Ce média est utilisé dans une publication prête ou planifiée")
    await ctx.delete("media_assets", aid)
    await audit(ctx.org_id, ctx.member, "media_deleted", a["filename"])
    return {"ok": True}


# ---------- Événement : marque, accord client, crédits ----------
class CreditIn(BaseModel):
    key: str = Field("", max_length=80)
    role: str = Field("", max_length=80)
    name: str = Field("", max_length=120)
    handle: str = Field("", max_length=80)
    included: bool = True


class EventCommIn(BaseModel):
    brand_id: str = ""
    consent: Literal["a_demander", "accorde", "refuse"] = "a_demander"
    consent_note: str = Field("", max_length=500)
    embargo_date: str = Field("", pattern=DAY)
    notes: str = Field("", max_length=2000)
    credits: List[CreditIn] = Field([], max_length=60)


def _name(c: dict) -> str:
    return c.get("company") or f"{c.get('first_name', '')} {c.get('last_name', '')}".strip() or "—"


async def credits(org_id: str, ev: dict, ce: dict) -> list:
    import routes_dj
    rows, q = [], {"org_id": org_id}
    if ev.get("venue_id"):
        v = await db.venues.find_one({**q, "id": ev["venue_id"]}, {"_id": 0, "id": 1, "name": 1, "instagram_handle": 1})
        if v:
            rows.append({"key": f"venue:{v['id']}", "role": "Lieu", "name": v["name"], "handle": v.get("instagram_handle") or "", "target": {"kind": "venue", "id": v["id"]}})
    people = [(ev["planner_contact_id"], "Wedding planner", "")] if ev.get("planner_contact_id") else []
    labels = {c["key"]: c["label"] async for c in db.provider_categories.find(q, {"_id": 0, "key": 1, "label": 1})}
    pids = {m["provider_id"]: labels.get(m.get("category_key"), "Prestataire") async for m in db.missions.find({**q, "event_id": ev["id"], "status": {"$ne": "cancelled"}}, {"_id": 0, "provider_id": 1, "category_key": 1})}
    pids.update({b["provider_id"]: "DJ" async for b in db.dj_bookings.find({**q, "event_id": ev["id"], "status": {"$in": routes_dj.LIVE + ["done"]}}, {"_id": 0, "provider_id": 1})})
    async for p in db.provider_profiles.find({**q, "id": {"$in": list(pids)}}, {"_id": 0, "id": 1, "contact_id": 1, "instagram": 1, "stage_name": 1}):
        people.append((p.get("contact_id"), pids[p["id"]], handle_of(p.get("instagram"))))
    async for r in db.media_requests.find({**q, "event_id": ev["id"], "deleted_at": None}, {"_id": 0, "contact_id": 1, "name": 1, "handle": 1, "id": 1}):
        if r.get("contact_id"):
            people.append((r["contact_id"], "Photographe / vidéaste", r.get("handle") or ""))
        else:
            rows.append({"key": f"request:{r['id']}", "role": "Photographe / vidéaste", "name": r["name"], "handle": r.get("handle") or "", "target": None})
    cs = {c["id"]: c async for c in db.contacts.find({**q, "id": {"$in": [p[0] for p in people if p[0]]}}, {"_id": 0, "id": 1, "company": 1, "first_name": 1, "last_name": 1, "instagram_handle": 1})}
    for cid, role, alt in people:
        if cid in cs and not any(r["key"] == f"contact:{cid}" for r in rows):
            rows.append({"key": f"contact:{cid}", "role": role, "name": _name(cs[cid]), "handle": handle_of(cs[cid].get("instagram_handle")) or alt, "target": {"kind": "contact", "id": cid}})
    saved = {c["key"]: c for c in ce.get("credits") or []}
    out = [{**r, "role": saved.get(r["key"], {}).get("role") or r["role"], "handle": saved.get(r["key"], {}).get("handle") or r["handle"], "included": saved.get(r["key"], {}).get("included", True), "manual": False} for r in rows]
    return out + [{**c, "target": None, "manual": True} for c in ce.get("credits") or [] if c["key"].startswith("manual:")]


def credit_text(rows: list) -> str:
    return "\n".join(f"{r['role']} : @{r['handle']}" for r in rows if r["included"] and r["handle"])


async def event_view(ctx: Ctx, eid: str) -> dict:
    ev = await ctx.get("events", eid)
    ce = await db.comm_events.find_one(ctx.q({"event_id": eid}), {"_id": 0}) or {}
    cr = await credits(ctx.org_id, ev, ce)
    media = await states(ctx.org_id, await ctx.list("media_assets", {"event_id": eid, "deleted_at": None}))
    return {"event": {k: ev.get(k) for k in ("id", "title", "start", "type")}, "brands": (await settings(ctx.org_id))["brands"], "write": ctx.can("comms:manage"),
            "comm": {"brand_id": ce.get("brand_id", ""), "consent": ce.get("consent", "a_demander"), "consent_note": ce.get("consent_note", ""), "embargo_date": ce.get("embargo_date", ""), "notes": ce.get("notes", "")},
            "credits": cr, "credit_text": credit_text(cr), "missing_handles": sum(1 for r in cr if r["included"] and not r["handle"]),
            "media": {"total": len(media), "publiable": sum(1 for a in media if a["status"] == "publiable"), "thumbs": [a["thumb_ref"] for a in media if a["thumb_ref"]][:8]},
            "posts": await ctx.list("comm_posts", {"event_id": eid, "deleted_at": None}, sort=[("scheduled_at", 1)])}


@router.get("/communication/events/{eid}")
async def get_event(eid: str, ctx: Ctx = Depends(R)):
    return await event_view(ctx, eid)


@router.put("/communication/events/{eid}")
async def put_event(eid: str, body: EventCommIn, ctx: Ctx = Depends(W)):
    await ctx.get("events", eid)
    d = body.model_dump()
    brand_ok(d["brand_id"])
    d["credits"] = [{**c, "handle": handle_of(c["handle"], True), "key": c["key"] if not c["key"].startswith("manual:") and c["key"] else c["key"] or f"manual:{new_id()}"} for c in d["credits"]]
    old = await db.comm_events.find_one(ctx.q({"event_id": eid}), {"_id": 0}) or {}
    await db.comm_events.update_one(ctx.q({"event_id": eid}), {"$set": {**d, "updated_at": now_iso()}, "$setOnInsert": {"id": new_id(), "created_at": now_iso()}}, upsert=True)
    if old.get("consent", "a_demander") != d["consent"]:
        await audit(ctx.org_id, ctx.member, "comm_consent", eid, f"{old.get('consent', 'a_demander')} → {d['consent']}")
    return await event_view(ctx, eid)


class HandleIn(BaseModel):
    kind: Literal["contact", "venue"]
    id: str
    handle: str = Field("", max_length=80)


@router.put("/communication/handles")
async def put_handle(body: HandleIn, ctx: Ctx = Depends(W)):
    await ctx.update("contacts" if body.kind == "contact" else "venues", body.id, {"instagram_handle": handle_of(body.handle, True)})
    return {"ok": True}


@router.get("/communication/credits")
async def all_credits(ctx: Ctx = Depends(R)):
    day = today()
    evs = await db.events.find(ctx.q({"start": {"$gte": plus(day, -120), "$lte": plus(day, 61)}, "status": {"$nin": ["annule", "perdu"]}}), {"_id": 0}).sort("start", -1).to_list(60)
    ces = {c["event_id"]: c async for c in db.comm_events.find(ctx.q({"event_id": {"$in": [e["id"] for e in evs]}}), {"_id": 0})}
    out = []
    for e in evs:
        cr = await credits(ctx.org_id, e, ces.get(e["id"], {}))
        if cr:
            out.append({"event": {"id": e["id"], "title": e.get("title", ""), "start": e.get("start", "")}, "credits": cr, "missing": sum(1 for r in cr if r["included"] and not r["handle"]), "credit_text": credit_text(cr)})
    return out


# ---------- Collectes photo ----------
class RequestIn(BaseModel):
    event_id: str
    contact_id: str = ""
    name: str = Field(min_length=1, max_length=120)
    email: str = Field("", max_length=160)
    due_date: str = Field("", pattern=DAY)
    message: str = Field("", max_length=1500)


class RequestPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    email: Optional[str] = Field(None, max_length=160)
    due_date: Optional[str] = Field(None, pattern=DAY)
    status: Optional[Literal["a_envoyer", "demandee", "recue", "close"]] = None


async def req_view(org_id: str, rows: list) -> list:
    titles = {e["id"]: e async for e in db.events.find({"org_id": org_id, "id": {"$in": [r["event_id"] for r in rows]}}, {"_id": 0, "id": 1, "title": 1, "start": 1})}
    out = []
    for r in rows:
        tok = await ensure_link("media_requests", r)
        out.append({**{k: v for k, v in r.items() if k not in ("share_nonce", "share_hash")}, "token": tok, "event_title": titles.get(r["event_id"], {}).get("title", ""), "event_start": titles.get(r["event_id"], {}).get("start", "")})
    return out


async def deliver(req: dict, subject: str, lines: list) -> bool:
    """Envoi réel uniquement en production et jamais pour la société de test."""
    org = await db.orgs.find_one({"id": req["org_id"]}, {"_id": 0, "name": 1, "slug": 1, "email": 1}) or {}
    if not PROD or org.get("slug") == "qa-sandbox" or not req.get("email"):
        return False
    from emailer import mail_html, send_email
    url = f"{(os.environ.get('APP_URL') or '').rstrip('/')}/depot/{await ensure_link('media_requests', req)}"
    await send_email(to=req["email"], subject=subject, html=mail_html(org.get("name", ""), f"Bonjour {req['name']},", lines, ("Déposer mes photos et vidéos", url)), reply_to=org.get("email") or None)
    return True


@router.get("/communication/requests")
async def list_requests(event_id: str = "", ctx: Ctx = Depends(R)):
    return await req_view(ctx.org_id, await ctx.list("media_requests", {"deleted_at": None, **({"event_id": event_id} if event_id else {})}, sort=[("created_at", -1)]))


@router.post("/communication/requests")
async def create_request(body: RequestIn, ctx: Ctx = Depends(W)):
    ev = await ctx.get("events", body.event_id)
    if body.contact_id:
        await ctx.get("contacts", body.contact_id)
    cfg = await settings(ctx.org_id)
    base = (ev.get("start") or today())[:10]
    r = await ctx.insert("media_requests", {**body.model_dump(), "email": body.email.strip().lower(), "message": body.message.strip() or cfg["request_message"], "status": "a_envoyer", "sent_at": None, "sent_real": False,
                                            "received": 0, "handle": "", "reminders": [{"offset": d, "date": plus(base, d), "status": "planifiee"} for d in cfg["reminder_days"]], "deleted_at": None})
    return (await req_view(ctx.org_id, [r]))[0]


@router.post("/communication/requests/{rid}/send")
async def send_request(rid: str, ctx: Ctx = Depends(W)):
    r = await ctx.get("media_requests", rid, {"deleted_at": None})
    if r["status"] == "close":
        raise HTTPException(409, "Cette collecte est clôturée")
    ev = await ctx.get("events", r["event_id"])
    sent = await deliver(r, f"Vos photos — {ev.get('type', 'événement')} du {fr((ev.get('start') or '')[:10])}", [r["message"], "Le lien ci-dessous vous est personnel : vous pouvez y déposer vos fichiers en plusieurs fois."])
    r = await ctx.update("media_requests", rid, {"status": "demandee" if r["status"] == "a_envoyer" else r["status"], "sent_at": now_iso(), "sent_real": sent})
    return {**(await req_view(ctx.org_id, [r]))[0], "sent": sent,
            "message": "Demande envoyée par e-mail" if sent else "Demande enregistrée. Aucun e-mail n'est envoyé hors production : transmettez le lien de dépôt vous-même si besoin."}


@router.put("/communication/requests/{rid}")
async def put_request(rid: str, body: RequestPatch, ctx: Ctx = Depends(W)):
    await ctx.get("media_requests", rid, {"deleted_at": None})
    return (await req_view(ctx.org_id, [await ctx.update("media_requests", rid, body.model_dump(exclude_none=True))]))[0]


@router.delete("/communication/requests/{rid}")
async def del_request(rid: str, ctx: Ctx = Depends(W)):
    await ctx.get("media_requests", rid, {"deleted_at": None})
    await ctx.update("media_requests", rid, {"deleted_at": now_iso(), "status": "close"})
    return {"ok": True}


async def _drop(token: str) -> tuple:
    r = await link_doc("media_requests", token)
    if not r or r.get("deleted_at"):
        raise HTTPException(404, "Lien introuvable")
    ev = await db.events.find_one({"org_id": r["org_id"], "id": r["event_id"]}, {"_id": 0}) or {}
    if r["status"] == "close" or today() > plus((ev.get("start") or r["created_at"])[:10], 180):
        raise HTTPException(410, "Ce lien de dépôt est clôturé")
    return r, ev


class DropDone(BaseModel):
    authorize: bool = False
    handle: str = Field("", max_length=80)


@router.get("/public/media-drop/{token}")
async def drop_info(token: str):
    r, ev = await _drop(token)
    org = await db.orgs.find_one({"id": r["org_id"]}, {"_id": 0, "name": 1}) or {}
    return {"org": org.get("name", ""), "name": r["name"], "event": f"{ev.get('type') or 'Événement'} du {fr((ev.get('start') or '')[:10])}", "message": r["message"], "received": r["received"], "handle": r.get("handle", ""),
            "max_photo_mb": IMG_MAX // 1048576, "max_video_mb": VID_MAX // 1048576}


@router.post("/public/media-drop/{token}/uploads")
async def drop_start(token: str, body: UploadIn):
    r, _ = await _drop(token)
    return await start_upload(r["org_id"], body, f"Dépôt : {r['name']}")


@router.put("/public/media-drop/{token}/uploads/{uid}/chunks/{n}")
async def drop_chunk(token: str, uid: str, n: int, request: Request):
    r, _ = await _drop(token)
    return await put_chunk(r["org_id"], uid, n, request)


@router.post("/public/media-drop/{token}/uploads/{uid}/complete")
async def drop_done(token: str, uid: str, body: DropDone):
    import routes_stock
    r, ev = await _drop(token)
    h = handle_of(body.handle, True)
    a = await finish_upload(r["org_id"], uid, {"event_id": r["event_id"], "author_name": r["name"], "author_handle": h, "author_contact_id": r.get("contact_id", ""), "source": "collecte", "request_id": r["id"],
                                               "rights": "ok" if body.authorize else "to_confirm", "rights_note": "Autorisation donnée sur la page de dépôt" if body.authorize else ""})
    if not a["duplicate"]:
        await db.media_requests.update_one({"org_id": r["org_id"], "id": r["id"]}, {"$inc": {"received": 1}, "$set": {"status": "recue", "handle": h or r.get("handle", ""), "last_received_at": now_iso()}})
        await routes_stock.task(r["org_id"], f"Photos reçues de {r['name']} — {ev.get('title', '')}", f"comm-drop:{r['id']}", desc="Vérifiez les droits et le tri dans Communication › Médiathèque.")
    return {"ok": True, "duplicate": a["duplicate"], "filename": a["filename"]}


# ---------- Studio et calendrier (rappel manuel) ----------
class PostIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    brand_id: str
    type: Literal["post", "carrousel", "reel", "story"] = "post"
    event_id: str = ""
    asset_ids: List[str] = Field([], max_length=20)
    caption_fr: str = Field("", max_length=2200)
    caption_en: str = Field("", max_length=2200)
    hashtags: List[str] = Field([], max_length=30)
    credits_text: str = Field("", max_length=1500)
    scheduled_at: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})?$")
    status: Literal["idee", "brouillon", "pret", "planifie", "publie"] = "brouillon"
    permalink: str = Field("", max_length=300)


async def _post(ctx: Ctx, body: PostIn) -> dict:
    d = body.model_dump()
    brand_ok(d["brand_id"])
    if d["event_id"]:
        await ctx.get("events", d["event_id"])
    d["hashtags"] = [h.strip().lstrip("#") for h in d["hashtags"] if h.strip()]
    rows = await states(ctx.org_id, await ctx.list("media_assets", {"id": {"$in": d["asset_ids"]}, "deleted_at": None}))
    if len(rows) != len(set(d["asset_ids"])):
        raise HTTPException(400, "Média introuvable")
    if d["status"] in ("pret", "planifie", "publie"):
        bad = [f"{a['filename']} : {', '.join(a['blocked_reasons'])}" for a in rows if a["status"] == "bloque"]
        if bad:
            raise HTTPException(400, "Publication impossible, média bloqué — " + " ; ".join(bad[:5]))
        if not rows and d["type"] != "story":
            raise HTTPException(400, "Ajoutez au moins un média publiable")
    if d["status"] == "planifie" and not d["scheduled_at"]:
        raise HTTPException(400, "Indiquez la date et l'heure de publication")
    if d["permalink"] and not d["permalink"].startswith("https://"):
        raise HTTPException(400, "Le lien de la publication doit commencer par https://")
    return {**d, "publish_mode": "rappel_manuel"}


async def post_view(org_id: str, rows: list) -> list:
    ids = [i for p in rows for i in p["asset_ids"]]
    media = {a["id"]: a for a in await states(org_id, await db.media_assets.find({"org_id": org_id, "id": {"$in": ids}}, {"_id": 0}).to_list(2000))}
    return [{**p, "assets": [{k: media[i][k] for k in ("id", "thumb_ref", "file_ref", "kind", "filename", "status", "blocked_reasons")} for i in p["asset_ids"] if i in media]} for p in rows]


@router.get("/communication/posts")
async def list_posts(start: str = "", end: str = "", ctx: Ctx = Depends(R)):
    f = {"deleted_at": None, **({"$or": [{"scheduled_at": {"$gte": start, "$lte": end + "T99"}}, {"scheduled_at": ""}]} if start and end else {})}
    return await post_view(ctx.org_id, await ctx.list("comm_posts", f, sort=[("scheduled_at", 1)]))


@router.post("/communication/posts")
async def create_post(body: PostIn, ctx: Ctx = Depends(W)):
    return (await post_view(ctx.org_id, [await ctx.insert("comm_posts", {**await _post(ctx, body), "reminded_at": None, "published_at": None, "created_by": ctx.member.get("name"), "deleted_at": None})]))[0]


@router.put("/communication/posts/{pid}")
async def put_post(pid: str, body: PostIn, ctx: Ctx = Depends(W)):
    old = await ctx.get("comm_posts", pid, {"deleted_at": None})
    d = await _post(ctx, body)
    extra = {"reminded_at": None} if d["scheduled_at"] != old["scheduled_at"] else {}
    if d["status"] == "publie" and not old.get("published_at"):
        extra["published_at"] = now_iso()
    return (await post_view(ctx.org_id, [await ctx.update("comm_posts", pid, {**d, **extra})]))[0]


@router.delete("/communication/posts/{pid}")
async def del_post(pid: str, ctx: Ctx = Depends(W)):
    await ctx.get("comm_posts", pid, {"deleted_at": None})
    await ctx.delete("comm_posts", pid)
    return {"ok": True}


class CaptionIn(BaseModel):
    brand_id: str
    event_id: str = ""
    type: str = Field("post", max_length=20)
    brief: str = Field("", max_length=800)


@router.post("/communication/captions")
async def captions(body: CaptionIn, ctx: Ctx = Depends(W)):
    from routes_admin import _json
    if not mc.ai_ready():
        mc.ai_fail()
    cfg = await settings(ctx.org_id)
    brand = next((b for b in cfg["brands"] if b["id"] == brand_ok(body.brand_id)), None)
    if not brand:
        raise HTTPException(400, "Marque inconnue")
    ctxt = ""
    if body.event_id:
        ev = await ctx.get("events", body.event_id)
        v = await db.venues.find_one(ctx.q({"id": ev.get("venue_id")}), {"_id": 0, "name": 1, "city": 1}) or {}
        ctxt = f"Événement : {ev.get('type', '')}, {(ev.get('start') or '')[:7]}, lieu : {v.get('name', '')} {v.get('city', '')}."
    try:
        r = await mc.claude().messages.create(
            model=os.environ.get("LLM_MODEL") or os.environ.get("CLAUDE_REPLY_MODEL") or "claude-sonnet-5-5", max_tokens=1800,
            system=DATA_GUARD + f" Tu rédiges des légendes Instagram pour la marque « {brand['name']} » (événementiel haut de gamme). Ton chaleureux et sobre, pas de superlatifs creux, aucun nom de client, aucun prix, "
                                "n'invente aucun fait. Réponds uniquement en JSON : {\"proposals\": [{\"fr\": \"\", \"en\": \"\", \"hashtags\": [\"sans dièse\"]}]} avec exactement 3 propositions de styles différents "
                                "(courte, narrative, coulisses), 5 à 10 hashtags chacune. N'inclus pas les crédits : ils sont ajoutés à part.",
            messages=[{"role": "user", "content": f"Format : {body.type}. {ctxt}\nHashtags habituels de la marque : {', '.join(brand['hashtags']) or 'aucun'}.\nConsigne de l'équipe : {body.brief or 'aucune'}"}])
        props = (_json("".join(b.text for b in r.content if b.type == "text")) or {}).get("proposals") or []
    except Exception as exc:
        mc.ai_fail(exc)
    return {"proposals": [{"fr": str(p.get("fr", ""))[:2200], "en": str(p.get("en", ""))[:2200], "hashtags": [str(h).lstrip("#") for h in (p.get("hashtags") or [])][:15]} for p in props[:3] if isinstance(p, dict)]}


# ---------- Tâche de fond : relances des collectes et rappels de publication ----------
async def tick() -> None:
    import routes_stock
    day, now = today(), datetime.now(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%dT%H:%M")
    async for r in db.media_requests.find({"status": "demandee", "deleted_at": None, "reminders": {"$elemMatch": {"status": "planifiee", "date": {"$lte": day}}}}, {"_id": 0}):
        due = [x for x in r["reminders"] if x["status"] == "planifiee" and x["date"] <= day]
        ev = await db.events.find_one({"org_id": r["org_id"], "id": r["event_id"]}, {"_id": 0, "type": 1, "start": 1}) or {}
        sent = await deliver(r, f"Rappel — vos photos du {fr((ev.get('start') or '')[:10])}", ["Nous n'avons pas encore reçu vos photos et vidéos de cet événement.", r["message"]])
        for x in due:
            x.update(status=("envoyee" if sent else "retenue") if x is due[-1] else "sautee", at=now_iso())
        await db.media_requests.update_one({"org_id": r["org_id"], "id": r["id"]}, {"$set": {"reminders": r["reminders"]}})
    async for p in db.comm_posts.find({"status": "planifie", "deleted_at": None, "reminded_at": None, "scheduled_at": {"$lte": now, "$ne": ""}}, {"_id": 0}):
        await routes_stock.task(p["org_id"], f"Publier sur Instagram : {p['title']}", f"comm-post:{p['id']}", desc="Publication en rappel manuel : publiez depuis Instagram puis marquez-la « Publiée » dans Communication › Studio.")
        await db.comm_posts.update_one({"org_id": p["org_id"], "id": p["id"]}, {"$set": {"reminded_at": now_iso()}})
