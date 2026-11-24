import csv
import hashlib
import hmac
import io
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Literal
from xml.sax.saxutils import escape

import requests
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

import portal_core as po
from core import Ctx, db, need, new_id, now_iso
from i18n import doc_lang
from routes_comms import base_url
from routes_portal import VISIBLE, TextIn, _mission, _org, c_event, nf
from security import SECRET, sha256

router = APIRouter(prefix="/api")
ID = r"^[\w-]{0,40}$"
TEMPLATES = {
    "wedding": [("Cérémonie", "Ceremony", True, False), ("Entrée en salle", "Grand entrance", True, True), ("Cocktail / vin d'honneur", "Cocktail hour", False, False), ("Dîner", "Dinner", False, False),
                ("Première danse / ouverture de bal", "First dance", True, True), ("Dessert / gâteau", "Cake cutting", True, True), ("Soirée dansante", "Dance floor", False, False), ("Dernière chanson", "Last song", True, True)],
    "corporate": [("Accueil", "Welcome", False, False), ("Cocktail", "Cocktail", False, False), ("Dîner", "Dinner", False, False), ("Discours / remise de prix", "Speeches / awards", True, False), ("Soirée dansante", "Dance floor", False, False)],
    "birthday": [("Arrivée des invités", "Guests arrival", False, False), ("Apéritif", "Drinks", False, False), ("Dîner", "Dinner", False, False), ("Gâteau", "Cake", True, True), ("Soirée dansante", "Dance floor", False, False), ("Dernière chanson", "Last song", True, True)],
}
TEMPLATE_LABELS = {"wedding": "Mariage complet", "corporate": "Soirée d'entreprise", "birthday": "Anniversaire"}
BY_TYPE = {"Mariage": "wedding", "Anniversaire": "birthday", "Soirée privée": "birthday"}
GENRES = {"pop": ("Pop", "Pop"), "rock": ("Rock", "Rock"), "80s": ("Années 80", "80s"), "2000s": ("Années 2000", "2000s"), "rap": ("Rap / hip-hop", "Rap / hip-hop"), "electro": ("Électro / house", "Electro / house"),
          "latino": ("Latino", "Latin"), "french": ("Variété française", "French pop"), "funk": ("Funk / disco", "Funk / disco"), "rnb": ("R&B", "R&B"), "reggaeton": ("Reggaeton", "Reggaeton"), "jazz": ("Jazz", "Jazz")}
TAGS = {"chill": ("chill", "chill"), "festive": ("festif", "festive"), "romantic": ("romantique", "romantic"), "lounge": ("lounge", "lounge"), "80s": ("années 80", "80s"), "elegant": ("élégant", "elegant")}
PDF = {"fr": {"title": "Feuille de route DJ", "key": "MOMENT CLÉ", "must": "Incontournable", "banned": "À NE JAMAIS PASSER", "genres": "Genres", "love": "J'adore", "ok": "OK", "avoid": "À éviter", "info": "Infos utiles",
              "instr": "Consignes", "mood": "Ambiance", "start": "démarrer à", "playlist": "Playlist de référence", "empty": "Aucun morceau", "guest": "suggestion d'invité",
              "languages": "Langues des invités", "ages": "Âges", "dancers": "Personnes à faire danser", "constraints": "Contraintes"},
       "en": {"title": "DJ run sheet", "key": "KEY MOMENT", "must": "Must play", "banned": "NEVER PLAY", "genres": "Genres", "love": "Love", "ok": "OK", "avoid": "Avoid", "info": "Useful information",
              "instr": "Instructions", "mood": "Mood", "start": "start at", "playlist": "Reference playlist", "empty": "No track", "guest": "guest suggestion",
              "languages": "Guests' languages", "ages": "Ages", "dancers": "People to get dancing", "constraints": "Constraints"}}
HOSTS = {"spotify": ("open.spotify.com", "https://open.spotify.com/oembed"), "youtube": ("youtu", "https://www.youtube.com/oembed"), "soundcloud": ("soundcloud.com", "https://soundcloud.com/oembed"),
         "deezer": ("deezer.", ""), "apple": ("music.apple.com", "")}


def _https(v: str) -> str:
    v = (v or "").strip()
    if v and not v.lower().startswith("https://"):
        raise ValueError("Le lien doit commencer par https://")
    return v


class Track(BaseModel):
    id: str = Field("", pattern=ID)
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field("", max_length=200)
    url: str = Field("", max_length=500)
    platform: str = Field("", max_length=20)
    artwork_url: str = Field("", max_length=500)
    duration_ms: int = Field(0, ge=0, le=36_000_000)
    preview_url: str = Field("", max_length=500)
    priority: Literal["must", "nice"] = "nice"
    version_note: str = Field("", max_length=200)
    start_at: str = Field("", max_length=20)
    note: str = Field("", max_length=500)
    source: Literal["manual", "link", "search", "import", "guest"] = "manual"
    _u = field_validator("url", "artwork_url", "preview_url")(_https)


class Playlist(BaseModel):
    id: str = Field("", pattern=ID)
    url: str = Field(min_length=9, max_length=500)
    platform: str = Field("", max_length=20)
    mode: Literal["reference", "imported"] = "reference"
    count: int = 0
    duration_ms: int = 0
    _u = field_validator("url")(_https)


class Moment(BaseModel):
    id: str = Field("", pattern=ID)
    name: str = Field(min_length=1, max_length=80)
    name_en: str = Field("", max_length=80)
    enabled: bool = True
    is_key_moment: bool = False
    single_track_mode: bool = False
    scheduled_time: str = Field("", pattern=r"^(([01]\d|2[0-3]):[0-5]\d)?$")
    duration_min: int = Field(0, ge=0, le=1440)
    mood: str = Field("", max_length=300)
    mood_tags: List[str] = Field(default_factory=list, max_length=10)
    instructions: str = Field("", max_length=2000)
    tracks: List[Track] = Field(default_factory=list, max_length=300)
    playlists: List[Playlist] = Field(default_factory=list, max_length=20)


class PlanIn(BaseModel):
    moments: List[Moment] = Field(max_length=40)
    genre_preferences: Dict[str, Literal["love", "ok", "avoid"]] = Field(default_factory=dict)
    banned: List[str] = Field(default_factory=list, max_length=100)
    useful_info: Dict[Literal["languages", "ages", "dancers", "constraints"], str] = Field(default_factory=dict)
    guest_requests_enabled: bool = False


def _moments(key: str) -> list:
    return [{"id": new_id(), "name": fr, "name_en": en, "order": i, "enabled": True, "is_key_moment": k, "single_track_mode": s, "scheduled_time": "", "duration_min": 0, "mood": "", "mood_tags": [],
             "instructions": "", "tracks": [], "playlists": []} for i, (fr, en, k, s) in enumerate(TEMPLATES[key])]


async def get_plan(org_id: str, ev: dict) -> dict:
    q = {"org_id": org_id, "event_id": ev["id"]}
    p = {"id": new_id(), **q, "status": "draft", "guest_requests_enabled": False, "guest_nonce": "", "guest_token_hash": "", "genre_preferences": {}, "banned": [], "useful_info": {},
         "moments": _moments(BY_TYPE.get(ev.get("type"), "corporate")), "comments": [], "activity": [], "created_at": now_iso(), "updated_at": now_iso()}
    await db.music_plans.update_one(q, {"$setOnInsert": p}, upsert=True)
    return await db.music_plans.find_one(q, {"_id": 0})


def completion(p: dict) -> int:
    ms = [m for m in p["moments"] if m.get("enabled", True)]
    done = sum(1 for m in ms if m["tracks"] or m.get("playlists")) + bool(p.get("genre_preferences")) + any((p.get("useful_info") or {}).values())
    return round(100 * done / (len(ms) + 2))


def guest_token(p: dict) -> str:
    return hmac.new(SECRET, f"guest:{p['id']}:{p['guest_nonce']}".encode(), hashlib.sha256).hexdigest()[:40] if p.get("guest_nonce") else ""


async def view(p: dict, ev: dict, org: dict, role: str, editable: bool) -> dict:
    lock = ((await po.event_modules(org, ev)).get("music") or {}).get("lock_date") or ""
    out = {**{k: p.get(k) for k in ("id", "status", "moments", "genre_preferences", "banned", "useful_info", "comments", "guest_requests_enabled", "updated_at", "sent_at", "validated_at")},
           "event": {"id": ev["id"], "title": ev["title"], "start": ev.get("start"), "type": ev.get("type")}, "role": role, "editable": editable, "lock_date": lock, "locked": bool(lock) and lock < po.today(),
           "completion": completion(p), "spotify": bool(os.environ.get("SPOTIFY_CLIENT_ID")), "activity": (p.get("activity") or [])[-30:][::-1]}
    if role != "dj":
        out["guest_url"] = f"/musique/{guest_token(p)}" if p.get("guest_requests_enabled") else ""
        out["suggestions"] = await db.guest_suggestions.find({"org_id": p["org_id"], "plan_id": p["id"], "status": "pending"}, {"_id": 0, "org_id": 0, "device": 0}).sort("created_at", 1).to_list(200)
        out["templates"] = TEMPLATE_LABELS
    return out


async def notify_team(org: dict, ev: dict, fr: str, en: str, base: str) -> None:
    async for m in db.missions.find({"org_id": org["id"], "event_id": ev["id"], "category_key": "dj", "status": {"$in": VISIBLE}}, {"_id": 0}):
        prof = await db.provider_profiles.find_one({"org_id": org["id"], "id": m["provider_id"]}, {"_id": 0, "contact_id": 1}) or {}
        c = await db.contacts.find_one({"org_id": org["id"], "id": prof.get("contact_id")}, {"_id": 0}) or {}
        if c.get("email"):
            e = doc_lang(c.get("language")) == "en"
            await po.send_tpl(org, "alert", c.get("language"), c["email"], {"prenom": c.get("first_name") or "", "sujet": f"{'Music' if e else 'Musique'} — {ev['title']}", "message": en if e else fr, "lien": base}, base)
    acc = await db.channel_accounts.find_one({"org_id": org["id"], "channel": "gmail", "status": "connected"}, {"_id": 0})
    if acc:
        await po.send_tpl(org, "alert", "fr-FR", acc["email"], {"prenom": "", "sujet": f"Musique — {ev['title']}", "message": fr, "lien": f"{base}/musique-plans"}, base)


def _log(ctx: Ctx, action: str) -> dict:
    return {"at": now_iso(), "by": ctx.member.get("name") or "", "role": ctx.role if ctx.role in ("client", "provider") else "staff", "action": action}


def _sp():
    cid, sec = os.environ.get("SPOTIFY_CLIENT_ID"), os.environ.get("SPOTIFY_CLIENT_SECRET")
    if not (cid and sec):
        return None
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    return spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=cid, client_secret=sec), requests_timeout=8)


def _sp_track(t: dict, source: str) -> dict:
    return {"title": t["name"][:200], "artist": ", ".join(a["name"] for a in t.get("artists") or [])[:200], "url": (t.get("external_urls") or {}).get("spotify", ""), "platform": "spotify",
            "artwork_url": ((t.get("album") or {}).get("images") or [{}])[-1].get("url", ""), "duration_ms": t.get("duration_ms") or 0, "preview_url": t.get("preview_url") or "", "source": source}


def platform_of(url: str) -> str:
    host = url.split("/")[2].lower() if url.count("/") >= 2 else ""
    return next((k for k, (h, _) in HOSTS.items() if h in host), "")


def _resolve(url: str) -> dict:
    plat = platform_of(url)
    out = {"url": url, "platform": plat, "title": "", "artist": "", "artwork_url": "", "playlist": "playlist" in url or "list=" in url}
    if plat and HOSTS[plat][1]:
        try:
            d = requests.get(HOSTS[plat][1], params={"url": url, "format": "json"}, timeout=5).json()
            title = (d.get("title") or "")[:200]
            out["artwork_url"] = d["thumbnail_url"] if str(d.get("thumbnail_url", "")).startswith("https://") else ""
            if plat != "spotify" and " - " in title:
                out["artist"], out["title"] = [x.strip() for x in title.split(" - ", 1)]
            else:
                out["title"], out["artist"] = title, (d.get("author_name") or "")[:200] if plat != "spotify" else ""
        except Exception:
            pass
    return out


def _import(url: str) -> list:
    plat = platform_of(url)
    if plat == "spotify" and "/playlist/" in url:
        sp = _sp()
        if not sp:
            raise ValueError("nokey")
        pid, items, page = url.split("/playlist/")[1].split("?")[0], [], None
        page = sp.playlist_items(pid, limit=100, additional_types=("track",))
        while page and len(items) < 300:
            items += [_sp_track(i["track"], "import") for i in page["items"] if i.get("track") and i["track"].get("name")]
            page = sp.next(page) if page.get("next") else None
        return items[:300]
    if plat == "youtube" and "list=" in url:
        key = os.environ.get("YOUTUBE_API_KEY")
        if not key:
            raise ValueError("nokey")
        lid, items, tok = url.split("list=")[1].split("&")[0], [], ""
        while len(items) < 300:
            d = requests.get("https://www.googleapis.com/youtube/v3/playlistItems", params={"part": "snippet", "maxResults": 50, "playlistId": lid, "key": key, "pageToken": tok}, timeout=8).json()
            if "items" not in d:
                raise ValueError("api")
            for i in d["items"]:
                s = i["snippet"]
                a, _, t = s["title"].partition(" - ")
                items.append({"title": (t or a)[:200], "artist": a[:200] if t else "", "url": f"https://www.youtube.com/watch?v={s['resourceId']['videoId']}", "platform": "youtube", "source": "import"})
            tok = d.get("nextPageToken") or ""
            if not tok:
                break
        return items
    raise ValueError("unsupported")


def _pdf(p: dict, ev: dict, org: dict, lang: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    L, en, ss = PDF[lang], lang == "en", getSampleStyleSheet()
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], spaceBefore=14)
    red = ParagraphStyle("red", parent=ss["Normal"], textColor=colors.red, fontName="Helvetica-Bold")
    n, e = ss["Normal"], lambda s: escape(str(s or ""))  # noqa: E731
    out = [Paragraph(f"{L['title']} — {e(ev['title'])}", ss["Title"]), Paragraph(f"{e(org.get('name'))} · {e((ev.get('start') or '')[:10])}", n)]
    if p.get("banned"):
        out += [Paragraph(L["banned"], ParagraphStyle("rh", parent=h2, textColor=colors.red))] + [Paragraph("✕ " + e(b), red) for b in p["banned"]]
    for m in [m for m in p["moments"] if m.get("enabled", True)]:
        name = (en and m.get("name_en")) or m["name"]
        out.append(Paragraph(f"{e(m.get('scheduled_time'))} {e(name)}" + (f" — <font color='#b45309'>{L['key']}</font>" if m.get("is_key_moment") else ""), h2))
        if m.get("mood") or m.get("mood_tags"):
            out.append(Paragraph(f"<i>{L['mood']} : {e(' · '.join(filter(None, [m.get('mood'), *[TAGS.get(k, (k, k))[en] for k in m.get('mood_tags', [])]])))}</i>", n))
        if m.get("instructions"):
            out.append(Paragraph(f"<b>{L['instr']} :</b> {e(m['instructions'])}", n))
        for i, t in enumerate(m["tracks"], 1):
            extra = " · ".join(filter(None, [t.get("version_note"), f"{L['start']} {t['start_at']}" if t.get("start_at") else "", t.get("note"), L["guest"] if t.get("source") == "guest" else ""]))
            star = f"<b>★ {L['must']}</b> — " if t.get("priority") == "must" or m.get("is_key_moment") else ""
            out.append(Paragraph(f"{i}. {star}<b>{e(t['title'])}</b> {e('— ' + t['artist'] if t.get('artist') else '')}" + (f" <i>({e(extra)})</i>" if extra else "") + (f"<br/><font size=7 color='#666666'>{e(t['url'])}</font>" if t.get("url") else ""), n))
        out += [Paragraph(f"{L['playlist']} : {e(pl['url'])}", n) for pl in m.get("playlists") or []]
        if not m["tracks"] and not m.get("playlists"):
            out.append(Paragraph(f"<i>{L['empty']}</i>", n))
    if p.get("genre_preferences"):
        out.append(Paragraph(L["genres"], h2))
        for lvl in ("love", "ok", "avoid"):
            gs = [GENRES.get(k, (k, k))[en] for k, v in p["genre_preferences"].items() if v == lvl]
            if gs:
                out.append(Paragraph(f"<b>{L[lvl]} :</b> {e(', '.join(gs))}", red if lvl == "avoid" else n))
    if any((p.get("useful_info") or {}).values()):
        out += [Paragraph(L["info"], h2)] + [Paragraph(f"<b>{L[k]} :</b> {e(v)}", n) for k, v in p["useful_info"].items() if v]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, title=L["title"], leftMargin=40, rightMargin=40, topMargin=36, bottomMargin=36).build(out + [Spacer(1, 6)])
    return buf.getvalue()


# ---------- Accès : client / staff / DJ ----------
async def as_client(ctx: Ctx, request: Request, key: str, action: str):
    if action in ("validate", "unlock", "template"):
        raise HTTPException(403, "Action non autorisée")
    ev, org, mods, state = await c_event(ctx, request, key, "music", write=action in ("edit", "send", "suggest"))
    mine = ctx.contact_id in (ev.get("client_contact_ids") or [])
    if action == "comment" and (not mine or state != "active"):
        raise HTTPException(403, "Lecture seule")
    return ev, org, "client", state == "active" and mods["music"]["editable"] and mine


async def as_staff(ctx: Ctx, request: Request, key: str, action: str):
    ev = await ctx.get("events", key, ctx.event_scope())
    if action == "validate" or (action != "read" and not ctx.can("events:write")):
        raise HTTPException(403, "Action non autorisée pour votre rôle")
    return ev, await _org(ctx), "staff", ctx.can("events:write")


async def as_dj(ctx: Ctx, request: Request, key: str, action: str):
    m, _ = await _mission(ctx, request, key)
    ev = await db.events.find_one(ctx.q({"id": m.get("event_id") or "__none__"}), {"_id": 0}) if m["category_key"] == "dj" else None
    if not ev:
        await nf(ctx, request)
    if action not in ("read", "comment", "validate"):
        raise HTTPException(403, "Action non autorisée")
    return ev, await _org(ctx), "dj", False


class UrlIn(BaseModel):
    url: str = Field(min_length=9, max_length=500)
    moment_id: str = Field("", pattern=ID)
    _u = field_validator("url")(_https)


class DecideIn(BaseModel):
    action: Literal["accept", "refuse"]
    moment_id: str = Field("", pattern=ID)


class TemplateIn(BaseModel):
    key: Literal["wedding", "corporate", "birthday"]


def mount(base: str, dep, resolve):
    async def load(ctx, request, key, action):
        ev, org, role, editable = await resolve(ctx, request, key, action)
        return ev, org, role, editable, await get_plan(ctx.org_id, ev)

    async def upd(ctx, p, ch, log=None):
        op = {"$set": {**ch, "updated_at": now_iso()}}
        if log:
            op["$push"] = {"activity": {"$each": [_log(ctx, log)], "$slice": -100}}
        await db.music_plans.update_one(ctx.q({"id": p["id"]}), op)

    @router.get(base)
    async def read(key: str, request: Request, ctx: Ctx = Depends(dep)):
        ev, org, role, editable, p = await load(ctx, request, key, "read")
        return await view(p, ev, org, role, editable)

    @router.put(base)
    async def save(key: str, body: PlanIn, request: Request, ctx: Ctx = Depends(dep)):
        ev, org, role, editable, p = await load(ctx, request, key, "edit")
        if any(m.single_track_mode and len(m.tracks) > 1 for m in body.moments):
            raise HTTPException(400, "Ce moment n'accepte qu'un seul morceau")
        ch = {"moments": [{**m.model_dump(), "id": m.id or new_id(), "order": i, "tracks": [{**t.model_dump(), "id": t.id or new_id(), "order": j} for j, t in enumerate(m.tracks)],
                           "playlists": [{**x.model_dump(), "id": x.id or new_id()} for x in m.playlists]} for i, m in enumerate(body.moments)],
              "genre_preferences": {k: v for k, v in body.genre_preferences.items() if k in GENRES}, "banned": [b.strip()[:200] for b in body.banned if b.strip()], "useful_info": {k: v[:1000] for k, v in body.useful_info.items()},
              "guest_requests_enabled": body.guest_requests_enabled}
        if body.guest_requests_enabled and not p.get("guest_nonce"):
            p["guest_nonce"] = ch["guest_nonce"] = new_id()
            ch["guest_token_hash"] = sha256(guest_token(p))
        last = (p.get("activity") or [{}])[-1]
        fresh = last.get("action") == "updated" and last.get("by") == ctx.member.get("name") and last.get("at", "") > (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        if p["status"] != "draft":
            ch["status"] = "sent"
            if role == "client" and (p.get("change_notified_at") or "") < (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat():
                ch["change_notified_at"] = now_iso()
                await notify_team(org, ev, "Le client a modifié sa sélection musicale après l'envoi.", "The client changed their music selection after sending it.", base_url(request))
        await upd(ctx, p, ch, None if fresh else "updated")
        return {"saved_at": now_iso(), "status": ch.get("status", p["status"]), "completion": completion({**p, **ch}), "guest_url": f"/musique/{guest_token(p)}" if body.guest_requests_enabled else ""}

    @router.post(base + "/send")
    async def send(key: str, request: Request, ctx: Ctx = Depends(dep)):
        ev, org, role, editable, p = await load(ctx, request, key, "send")
        await upd(ctx, p, {"status": "sent", "sent_at": now_iso()}, "sent")
        await notify_team(org, ev, "La sélection musicale a été envoyée au DJ. Elle est prête à être relue et validée.", "The music selection has been sent to the DJ. It is ready for review and approval.", base_url(request))
        return {"ok": True}

    @router.post(base + "/validate")
    async def validate(key: str, request: Request, ctx: Ctx = Depends(dep)):
        ev, org, role, editable, p = await load(ctx, request, key, "validate")
        if p["status"] != "sent":
            raise HTTPException(409, "La sélection n'a pas encore été envoyée")
        await upd(ctx, p, {"status": "validated", "validated_at": now_iso()}, "validated")
        await po.notify_clients(org, ev, "new_message", {"message": "Votre DJ a validé votre sélection musicale. / Your DJ approved your music selection."}, base_url(request))
        return {"ok": True}

    @router.post(base + "/unlock")
    async def unlock(key: str, request: Request, ctx: Ctx = Depends(dep)):
        ev, org, role, editable, p = await load(ctx, request, key, "unlock")
        await po.event_modules(org, ev)
        await db.event_portal_modules.update_one(ctx.q({"event_id": ev["id"], "module_key": "music"}), {"$set": {"lock_date": "", "client_editable": True}})
        await upd(ctx, p, {}, "unlocked")
        return {"ok": True}

    @router.post(base + "/template")
    async def apply_template(key: str, body: TemplateIn, request: Request, ctx: Ctx = Depends(dep)):
        ev, org, role, editable, p = await load(ctx, request, key, "template")
        if any(m["tracks"] for m in p["moments"]):
            raise HTTPException(409, "Des morceaux existent déjà : le modèle ne peut plus être remplacé")
        await upd(ctx, p, {"moments": _moments(body.key)}, "template")
        return {"ok": True}

    @router.post(base + "/moments/{mom}/comments")
    async def comment(key: str, mom: str, body: TextIn, request: Request, ctx: Ctx = Depends(dep)):
        ev, org, role, editable, p = await load(ctx, request, key, "comment")
        m = next((x for x in p["moments"] if x["id"] == mom), None)
        if not m:
            raise HTTPException(404, "Introuvable")
        c = {"id": new_id(), "moment_id": mom, "by": ctx.member.get("name") or "", "role": role, "at": now_iso(), "body": body.body.strip()}
        await db.music_plans.update_one(ctx.q({"id": p["id"]}), {"$push": {"comments": c}})
        if role == "client":
            await notify_team(org, ev, f"Nouveau commentaire du client sur « {m['name']} » : {c['body']}", f"New comment from the client on “{m.get('name_en') or m['name']}”: {c['body']}", base_url(request))
        else:
            await po.notify_clients(org, ev, "new_message", {"message": f"{m['name']} — {c['body']}"}, base_url(request))
        return c

    @router.get(base + "/search")
    async def search(key: str, request: Request, q: str = "", ctx: Ctx = Depends(dep)):
        await resolve(ctx, request, key, "read")
        sp = _sp() if len(q.strip()) >= 2 else None
        if not sp:
            return {"enabled": bool(os.environ.get("SPOTIFY_CLIENT_ID")), "results": []}
        try:
            r = await run_in_threadpool(lambda: sp.search(q.strip()[:80], limit=8, type="track"))
            return {"enabled": True, "results": [_sp_track(t, "search") for t in r["tracks"]["items"]]}
        except Exception:
            return {"enabled": True, "results": []}

    @router.post(base + "/resolve")
    async def resolve_link(key: str, body: UrlIn, request: Request, ctx: Ctx = Depends(dep)):
        await resolve(ctx, request, key, "edit")
        return await run_in_threadpool(_resolve, body.url)

    @router.post(base + "/import")
    async def import_playlist(key: str, body: UrlIn, request: Request, ctx: Ctx = Depends(dep)):
        await resolve(ctx, request, key, "edit")
        try:
            tracks = await run_in_threadpool(_import, body.url)
            return {"ok": True, "tracks": tracks, "count": len(tracks), "duration_ms": sum(t.get("duration_ms") or 0 for t in tracks), "platform": platform_of(body.url)}
        except ValueError as exc:
            return {"ok": False, "reason": str(exc), "platform": platform_of(body.url)}
        except Exception:
            return {"ok": False, "reason": "api", "platform": platform_of(body.url)}

    @router.post(base + "/suggestions/{sid}")
    async def decide(key: str, sid: str, body: DecideIn, request: Request, ctx: Ctx = Depends(dep)):
        ev, org, role, editable, p = await load(ctx, request, key, "suggest" if ctx.role == "client" else "edit")
        s = await db.guest_suggestions.find_one(ctx.q({"id": sid, "plan_id": p["id"], "status": "pending"}), {"_id": 0})
        if not s:
            raise HTTPException(404, "Introuvable")
        if body.action == "accept":
            m = next((x for x in p["moments"] if x["id"] == body.moment_id), None)
            if not m or (m.get("single_track_mode") and m["tracks"]):
                raise HTTPException(400, "Choisissez un moment qui accepte ce morceau")
            t = Track(title=s["title"], artist=s.get("artist", ""), url=s.get("url", ""), platform=platform_of(s.get("url", "")), source="guest", note=f"Suggéré par {s['name']}"[:500]).model_dump()
            await db.music_plans.update_one(ctx.q({"id": p["id"], "moments.id": m["id"]}), {"$push": {"moments.$.tracks": {**t, "id": new_id(), "order": len(m["tracks"])}}})
        await db.guest_suggestions.update_one(ctx.q({"id": sid}), {"$set": {"status": "accepted" if body.action == "accept" else "refused", "decided_at": now_iso()}})
        return await view(await get_plan(ctx.org_id, ev), ev, org, role, editable)

    @router.get(base + "/pdf")
    async def pdf(key: str, request: Request, lang: str = "", ctx: Ctx = Depends(dep)):
        ev, org, role, editable, p = await load(ctx, request, key, "read")
        c = await db.contacts.find_one(ctx.q({"id": ctx.contact_id or "__none__"}), {"_id": 0, "language": 1}) or {}
        lg = lang if lang in ("fr", "en") else doc_lang(c.get("language") or ev.get("language"))
        return Response(await run_in_threadpool(_pdf, p, ev, org, lg), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="feuille-de-route-dj.pdf"'})

    @router.get(base + "/csv")
    async def tracks_csv(key: str, request: Request, ctx: Ctx = Depends(dep)):
        ev, org, role, editable, p = await load(ctx, request, key, "read")
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["Moment", "Heure", "N°", "Titre", "Artiste", "Lien", "Priorité", "Version", "Départ", "Note"])
        for m in p["moments"]:
            for i, t in enumerate(m["tracks"], 1):
                w.writerow([m["name"], m.get("scheduled_time", ""), i, t["title"], t.get("artist", ""), t.get("url", ""), "Incontournable" if t.get("priority") == "must" else "Si possible", t.get("version_note", ""), t.get("start_at", ""), t.get("note", "")])
        return Response("\ufeff" + buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="morceaux.csv"'})


mount("/portal/client/events/{key}/music", need("portal:client"), as_client)
mount("/events/{key}/music", need("events:read"), as_staff)
mount("/portal/provider/missions/{key}/music", need("portal:provider"), as_dj)


@router.get("/music-plans")
async def music_plans(ctx: Ctx = Depends(need("events:read"))):
    plans = {p["event_id"]: p for p in await ctx.list("music_plans", limit=1000)}
    org, out = await _org(ctx), []
    evs = await ctx.list("events", {**ctx.event_scope(), "start": {"$gte": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()[:10]}}, sort=[("start", 1)], limit=500)
    for ev in evs:
        row = (await po.event_modules(org, ev)).get("music") or {}
        p = plans.get(ev["id"])
        if p or row.get("client_visible"):
            out.append({"event_id": ev["id"], "title": ev["title"], "start": ev.get("start"), "status": (p or {}).get("status") or "none", "lock_date": row.get("lock_date") or "", "completion": completion(p) if p else 0,
                        "visible": bool(row.get("client_visible")), "pending": await db.guest_suggestions.count_documents(ctx.q({"event_id": ev["id"], "status": "pending"}))})
    return out


# ---------- Lien invités (public) ----------
def _challenge() -> dict:
    a, b, exp = int.from_bytes(os.urandom(1), "big") % 8 + 1, int.from_bytes(os.urandom(1), "big") % 8 + 1, int(time.time()) + 1800
    return {"a": a, "b": b, "exp": exp, "sig": hmac.new(SECRET, f"cap:{a + b}:{exp}".encode(), hashlib.sha256).hexdigest()}


async def _guest_plan(token: str) -> dict:
    p = await db.music_plans.find_one({"guest_token_hash": sha256(token), "guest_requests_enabled": True}, {"_id": 0}) if 30 <= len(token) <= 64 else None
    if not p:
        raise HTTPException(404, "Lien introuvable")
    from core import check_expiry
    ev = await db.events.find_one({"org_id": p["org_id"], "id": p["event_id"]}, {"_id": 0, "end": 1}) or {}
    check_expiry((datetime.strptime((ev.get("end") or "9000-01-01")[:10], "%Y-%m-%d") + timedelta(days=7)).strftime("%Y-%m-%d"))
    return p


@router.get("/public/music/{token}")
async def guest_page(token: str):
    p = await _guest_plan(token)
    ev = await db.events.find_one({"org_id": p["org_id"], "id": p["event_id"]}, {"_id": 0, "title": 1, "language": 1}) or {}
    return {"event": ev.get("title", ""), "language": ev.get("language") or "fr-FR", "challenge": _challenge()}


class GuestIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    artist: str = Field("", max_length=200)
    url: str = Field("", max_length=500)
    device: str = Field("", max_length=64)
    website: str = Field("", max_length=200)
    answer: int
    exp: int
    sig: str = Field(max_length=64)
    _u = field_validator("url")(_https)


@router.post("/public/music/{token}")
async def guest_suggest(token: str, body: GuestIn, request: Request):
    p = await _guest_plan(token)
    good = hmac.new(SECRET, f"cap:{body.answer}:{body.exp}".encode(), hashlib.sha256).hexdigest()
    if body.website or body.exp < time.time() or not hmac.compare_digest(good, body.sig):
        raise HTTPException(400, "Vérification échouée")
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    device = sha256(f"{ip}:{body.device}")
    if await db.guest_suggestions.count_documents({"plan_id": p["id"], "device": device}) >= 5:
        raise HTTPException(429, "Limite atteinte")
    await db.guest_suggestions.insert_one({"id": new_id(), "org_id": p["org_id"], "plan_id": p["id"], "event_id": p["event_id"], "name": body.name.strip(), "title": body.title.strip(), "artist": body.artist.strip(),
                                           "url": body.url, "device": device, "status": "pending", "created_at": now_iso()})
    return {"ok": True}
