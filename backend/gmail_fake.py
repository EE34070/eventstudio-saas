"""Gmail simulé pour la société de test : mêmes chemins que l'API Gmail, données dans `fake_gmail`. Jamais utilisé en production."""
import base64
import email
import time

from pymongo import ReturnDocument

from core import db

SYSTEM = ["INBOX", "SENT", "UNREAD", "STARRED", "SPAM", "TRASH", "IMPORTANT", "CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_FORUMS"]


async def _seq(aid: str, inc: int = 1) -> int:
    d = await db.fake_gmail.find_one_and_update({"account_id": aid, "kind": "counter"}, {"$inc": {"n": inc}}, upsert=True, return_document=ReturnDocument.AFTER)
    return d["n"]


async def _event(aid: str, key: str, ids: list) -> None:
    for g in ids:
        await db.fake_gmail.insert_one({"account_id": aid, "kind": "history", "n": await _seq(aid), "key": key, "gmail_id": g})


def _b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


async def add(aid: str, frm: str, subject: str, text: str, labels: list, thread: str = "", days_ago: float = 0, headers: dict | None = None, html: str = "", to: str = "qa@example.com") -> dict:
    n = await _seq(aid)
    gid = f"fake{n:06d}"
    hs = [{"name": k, "value": v} for k, v in {"From": frm, "To": to, "Subject": subject, "Message-ID": f"<{gid}@fake>", **(headers or {})}.items()]
    parts = [{"mimeType": "text/plain", "body": {"data": _b64(text)}}] + ([{"mimeType": "text/html", "body": {"data": _b64(html)}}] if html else [])
    m = {"account_id": aid, "kind": "message", "id": gid, "threadId": thread or f"t{gid}", "labelIds": labels, "snippet": text[:120],
         "internalDate": str(int((time.time() - days_ago * 86400) * 1000)), "payload": {"mimeType": "multipart/alternative", "headers": hs, "parts": parts}}
    await db.fake_gmail.insert_one({**m})
    await _event(aid, "messagesAdded", [gid])
    return m


async def call(acc: dict, method: str, path: str, **kw) -> dict:
    from messaging_core import GmailError
    aid, p, body = acc["id"], path.strip("/").split("/"), kw.get("json") or {}
    f = {"account_id": aid}
    if p == ["profile"]:
        return {"historyId": str(await _seq(aid, 0)), "emailAddress": acc["email"]}
    if p == ["watch"]:
        return {"expiration": str(int((time.time() + 7 * 86400) * 1000))}
    if p[0] == "labels":
        if len(p) == 1 and method == "GET":
            user = [{"id": d["id"], "name": d["name"], "type": "user", "color": d.get("color")} async for d in db.fake_gmail.find({**f, "kind": "label"}, {"_id": 0})]
            return {"labels": [{"id": s, "name": s, "type": "system"} for s in SYSTEM] + user}
        name = (body.get("name") or "").strip()
        if method in ("POST", "PATCH", "PUT") and name and await db.fake_gmail.find_one({**f, "kind": "label", "name": name, **({"id": {"$ne": p[1]}} if len(p) > 1 else {})}):
            raise GmailError(409, "aborted", "Label name exists or conflicts")
        if len(p) == 1:
            d = {"id": f"Label_{await _seq(aid)}", "name": name, "type": "user"}
            await db.fake_gmail.insert_one({**f, "kind": "label", **d})
            return d
        if method == "DELETE":
            r = await db.fake_gmail.delete_one({**f, "kind": "label", "id": p[1]})
            if not r.deleted_count:
                raise GmailError(404, "notFound", "Label not found")
            ids = [m["id"] async for m in db.fake_gmail.find({**f, "kind": "message", "labelIds": p[1]}, {"id": 1})]
            await db.fake_gmail.update_many({**f, "kind": "message"}, {"$pull": {"labelIds": p[1]}})
            await _event(aid, "labelsRemoved", ids)
            return {}
        d = await db.fake_gmail.find_one_and_update({**f, "kind": "label", "id": p[1]}, {"$set": {"name": name}}, return_document=ReturnDocument.AFTER)
        if not d:
            raise GmailError(404, "notFound", "Label not found")
        return {"id": d["id"], "name": d["name"], "type": "user"}
    if p == ["messages"]:
        return {"messages": [{"id": m["id"]} async for m in db.fake_gmail.find({**f, "kind": "message", "labelIds": {"$nin": ["SPAM", "TRASH"]}}, {"id": 1})]}
    if p == ["messages", "send"]:
        e = email.message_from_bytes(base64.urlsafe_b64decode(body["raw"] + "=" * (-len(body["raw"]) % 4)))
        part = e.get_body(("plain",)) if hasattr(e, "get_body") else None
        text = part.get_content() if part else next((x.get_payload(decode=True).decode() for x in e.walk() if x.get_content_type() == "text/plain"), "")
        m = await add(aid, e["From"], e["Subject"], text, ["SENT"], thread=body.get("threadId") or "", to=e["To"])
        return {"id": m["id"], "threadId": m["threadId"]}
    if p[0] == "messages" and len(p) == 2:
        m = await db.fake_gmail.find_one({**f, "kind": "message", "id": p[1]}, {"_id": 0, "account_id": 0, "kind": 0})
        if not m:
            raise GmailError(404, "notFound", "Requested entity was not found.")
        return m
    if p[0] == "threads" and len(p) == 3:
        q = {**f, "kind": "message", "threadId": p[1]}
        ids = [m["id"] async for m in db.fake_gmail.find(q, {"id": 1})]
        if not ids:
            raise GmailError(404, "notFound", "Requested entity was not found.")
        add_l, rem = {"modify": (body.get("addLabelIds") or [], body.get("removeLabelIds") or []), "trash": (["TRASH"], ["INBOX", "SPAM"]), "untrash": ([], ["TRASH"])}[p[2]]
        known = set(SYSTEM) | {d["id"] async for d in db.fake_gmail.find({**f, "kind": "label"}, {"id": 1})}
        if set(add_l) - known:
            raise GmailError(400, "invalidArgument", "Invalid label")
        if rem:
            await db.fake_gmail.update_many(q, {"$pull": {"labelIds": {"$in": rem}}})
        if add_l:
            await db.fake_gmail.update_many(q, {"$addToSet": {"labelIds": {"$each": add_l}}})
        await _event(aid, "labelsAdded", ids)
        return {"id": p[1]}
    if p == ["history"]:
        start = int((kw.get("params") or {}).get("startHistoryId") or 0)
        rows = await db.fake_gmail.find({**f, "kind": "history", "n": {"$gt": start}}).sort("n", 1).to_list(5000)
        return {"history": [{r["key"]: [{"message": {"id": r["gmail_id"]}}]} for r in rows], "historyId": str(await _seq(aid, 0))}
    raise GmailError(400, "invalidArgument", f"Chemin simulé inconnu : {method} {path}")
