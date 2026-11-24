import os

import requests
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from starlette.concurrency import run_in_threadpool

from core import Ctx, db, need, new_id, now_iso

from core import check_expiry, ensure_link, link_doc, link_limit  # noqa: E402,F401
router = APIRouter(prefix="/api")
APP_NAME = "exclusivity-erp"
MAX_SIZE = 15 * 1024 * 1024
TYPES = {"image/jpeg": ("jpg", b"\xff\xd8"), "image/png": ("png", b"\x89PNG"), "image/webp": ("webp", b"RIFF"),
         "application/pdf": ("pdf", b"%PDF")}
PROVIDER = (os.environ.get("STORAGE_PROVIDER") or "s3").strip().lower()  # s3 (R2, S3…) | local (développement)
LOCAL_DIR = os.path.realpath(os.environ.get("LOCAL_STORAGE_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads"))
_s3 = None


def s3_client():
    global _s3
    if _s3 is None:
        import boto3
        from botocore.config import Config
        _s3 = boto3.client("s3", config=Config(signature_version="s3v4"), endpoint_url=os.environ["S3_ENDPOINT"], aws_access_key_id=os.environ["S3_ACCESS_KEY"],
                           aws_secret_access_key=os.environ["S3_SECRET_KEY"], region_name=os.environ.get("S3_REGION", "auto"))
    return _s3


def _local(path: str) -> str:
    full = os.path.realpath(os.path.join(LOCAL_DIR, path))
    if not full.startswith(LOCAL_DIR + os.sep):
        raise ValueError("Chemin de fichier invalide")
    return full


def _put(path: str, data: bytes, ctype: str) -> str:
    if PROVIDER == "s3":
        s3_client().put_object(Bucket=os.environ["S3_BUCKET"], Key=path, Body=data, ContentType=ctype)
        return path
    if PROVIDER == "local":
        full = _local(path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(data)
        return path
    raise RuntimeError(f"STORAGE_PROVIDER inconnu : {PROVIDER} (s3 ou local)")


def _get(path: str) -> bytes:
    if PROVIDER == "s3":
        return s3_client().get_object(Bucket=os.environ["S3_BUCKET"], Key=path)["Body"].read()
    if PROVIDER == "local":
        with open(_local(path), "rb") as fh:
            return fh.read()
    raise RuntimeError(f"STORAGE_PROVIDER inconnu : {PROVIDER} (s3 ou local)")


async def read_upload(file: UploadFile) -> tuple:
    ctype = (file.content_type or "").lower()
    if ctype not in TYPES:
        raise HTTPException(400, "Format non accepté (JPEG, PNG, WebP ou PDF)")
    limit = 20 * 1024 * 1024 if ctype == "application/pdf" else MAX_SIZE
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"Fichier trop volumineux ({limit // 1024 // 1024} Mo maximum)")
    if not data.startswith(TYPES[ctype][1]):
        raise HTTPException(400, "Le contenu du fichier ne correspond pas à son format")
    return data, ctype


async def store_bytes(org_id: str, data: bytes, ctype: str, filename: str, by: str = "") -> str:
    fid = new_id()
    try:
        res = await run_in_threadpool(_put, f"{APP_NAME}/{org_id}/{fid}.{TYPES[ctype][0]}", data, ctype)
    except Exception:
        raise HTTPException(502, "Stockage indisponible, réessayez")
    await db.files.insert_one({"id": fid, "org_id": org_id, "storage_path": res, "filename": filename[:200], "content_type": ctype,
                               "size": len(data), "is_deleted": False, "created_by": by, "created_at": now_iso()})
    return f"file:{fid}"


async def remove_stored(path: str) -> None:
    """Efface un fichier du stockage (purge de la Corbeille)."""
    def go():
        if PROVIDER == "s3":
            s3_client().delete_object(Bucket=os.environ["S3_BUCKET"], Key=path)
        elif PROVIDER == "local" and os.path.exists(_local(path)):
            os.remove(_local(path))
    try:
        await run_in_threadpool(go)
    except Exception:
        pass


@router.post("/files")
async def upload_file(file: UploadFile = File(...), ctx: Ctx = Depends(need())):
    if not ({"catalog:write", "venues:write", "events:write"} & ctx.perms):
        raise HTTPException(403, "Action non autorisée pour votre rôle")
    data, ctype = await read_upload(file)
    ref = await store_bytes(ctx.org_id, data, ctype, file.filename or "", ctx.member.get("name"))
    return {"id": ref[5:], "ref": ref, "content_type": ctype}


async def file_bytes(org_id: str, ref: str):
    if not (ref or "").startswith("file:"):
        return None
    rec = await db.files.find_one({"id": ref[5:], "org_id": org_id, "is_deleted": False}, {"_id": 0})
    if not rec:
        return None
    try:
        r = await run_in_threadpool(_get, rec["storage_path"])
    except Exception:
        return None
    return r, rec["content_type"]


def _serve(got) -> Response:
    if not got:
        raise HTTPException(404, "Introuvable")
    return Response(got[0], media_type=got[1], headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


def _link(path: str) -> str | None:
    if PROVIDER != "s3":
        return None
    from security import PROD
    base = "" if PROD else (os.environ.get("S3_PUBLIC_BASE_URL") or "").strip()
    if base:
        return f"{base.rstrip('/')}/{path}"
    return s3_client().generate_presigned_url("get_object", Params={"Bucket": os.environ["S3_BUCKET"], "Key": path}, ExpiresIn=300)


@router.get("/files/{fid}/link")
async def file_link(fid: str, ctx: Ctx = Depends(need())):
    rec = await db.files.find_one({"id": fid, "org_id": ctx.org_id, "is_deleted": False}, {"_id": 0})
    if not rec or (rec.get("restricted") == "social" and not ctx.can("social:view")):
        raise HTTPException(404, "Introuvable")
    return {"url": _link(rec["storage_path"])}


@router.get("/files/{fid}")
async def download_file(fid: str, ctx: Ctx = Depends(need())):
    if not ctx.can("social:view") and await db.files.find_one({"id": fid, "org_id": ctx.org_id, "restricted": "social"}):
        raise HTTPException(404, "Introuvable")
    return _serve(await file_bytes(ctx.org_id, f"file:{fid}"))


async def quote_products(quote: dict) -> list:
    ids = list(dict.fromkeys(l.get("equipment_id") for l in quote["lines"] if l.get("equipment_id")))
    eqs = {e["id"]: e for e in await db.equipment.find({"org_id": quote["org_id"], "id": {"$in": ids}}, {"_id": 0}).to_list(500)}
    en = not (quote.get("language") or "fr").startswith("fr")
    return [{"equipment_id": i, "ref": eqs[i]["ref"], "name": (en and eqs[i].get("name_en")) or eqs[i]["name"], "description": (en and eqs[i].get("description_en")) or eqs[i].get("description", ""),
             "photo": eqs[i].get("photo", "")} for i in ids if i in eqs and (eqs[i].get("description") or eqs[i].get("photo"))]


async def _shared_quote(token: str) -> dict:
    q = await link_doc("quotes", token)
    if not q:
        raise HTTPException(404, "Devis introuvable")
    return q


@router.get("/public/quotes/{token}")
async def public_quote(token: str):
    q = await _shared_quote(token)
    org = await db.orgs.find_one({"id": q["org_id"]}, {"_id": 0}) or {}
    products = await quote_products(q)
    for p in products:
        if p["photo"].startswith("file:"):
            p["photo"] = f"/api/public/quotes/{token}/files/{p['photo'][5:]}"
        elif not p["photo"].startswith("https://"):
            p["photo"] = ""
    return {**{k: q.get(k) for k in ("number", "status", "date", "valid_until", "lines", "vat_breakdown", "total_ht", "total_vat",
                                    "total_ttc", "deposit_percent", "notes", "event_title", "event_date")}, "language": q.get("language") or "fr-FR",
            "event_title": await __import__("routes_titles").quote_title(q), "valid_until": __import__("routes_titles").validity(q, org), "notes": __import__("routes_titles").client_notes(q.get("notes", "")),
            "lines": [{k: v for k, v in l.items() if k not in ("reused", "pack_components", "unit_cost")} for l in q.get("lines") or []],
            "client_name": (q.get("client") or {}).get("name", ""),
            "org": {k: org.get(k, "") for k in ("name", "address", "zip", "city", "phone", "email", "payment_terms", "payment_terms_en")},
            "terms": {"text": "" if __import__("routes_titles").cgv(org, q.get("language") or "fr-FR")["file"] else __import__("routes_titles").cgv(org, q.get("language") or "fr-FR")["text"],
                      "url": f"/api/public/quotes/{token}/terms" if __import__("routes_titles").cgv(org, q.get("language") or "fr-FR")["file"] else ""},
            "products": products, "documents": await __import__("routes_material").public_docs(q, token), **(await __import__("routes_quote_blocks").public_extra(q)), **(await __import__("routes_quote_docs").public_extra(q, token))}


@router.get("/public/quotes/{token}/terms")
async def public_quote_terms(token: str):
    q = await _shared_quote(token)
    org = await db.orgs.find_one({"id": q["org_id"]}, {"_id": 0}) or {}
    fid = __import__("routes_titles").cgv(org, q.get("language") or "fr-FR")["file"]
    if not fid:
        raise HTTPException(404, "Introuvable")
    return _serve(await file_bytes(q["org_id"], f"file:{fid}"))


@router.get("/public/quotes/{token}/files/{fid}")
async def public_quote_file(token: str, fid: str):
    q = await _shared_quote(token)
    if f"file:{fid}" not in {p["photo"] for p in await quote_products(q)}:
        raise HTTPException(404, "Introuvable")
    return _serve(await file_bytes(q["org_id"], f"file:{fid}"))
