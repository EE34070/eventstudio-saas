"""Questionnaire : connexion au Google Form existant (aucune question recréée).

1. Structure : lue par l'API Google Forms. Chaque question est identifiée par son
   itemId Google, jamais par son numéro ni son texte. La section = dernier saut de page.
2. Correspondance (wp_questions) : question → rubrique du récapitulatif → champ de fiche
   éventuel → module alimenté. Au premier passage, rapprochement avec la table de départ
   (seed.SEED_QUESTIONS) par section + intitulé. Toute question nouvelle arrive « À classer »
   avec une rubrique suggérée. Question modifiée : même itemId, même rangement.
   Question supprimée : conservée, marquée « deleted », ses réponses restent visibles.
3. Réponses (wp_responses) : rattachées au couple par l'e-mail du répondant (le formulaire
   doit collecter les e-mails), sinon « à attribuer » manuellement. Jamais perdues.
4. Fiche : une réponse préremplit un champ de la fiche UNIQUEMENT s'il est vide ;
   sinon, si elle diffère, une « différence détectée » est proposée à l'organisatrice.
"""
import json
import re
import time
import unicodedata
from collections import Counter
from typing import Protocol
from urllib.parse import quote

import httpx
import jwt

from app.core.config import get_settings
from app.core.tenancy import TenantContext

from . import service as S
from .seed import KEYWORDS, SECTION_EVENTS, SEED_QUESTIONS

FORMS_API = "https://forms.googleapis.com/v1/forms"
SCOPES = "https://www.googleapis.com/auth/forms.body.readonly https://www.googleapis.com/auth/forms.responses.readonly"


class FormsClient(Protocol):
    async def get_form(self, form_id: str) -> dict: ...
    async def list_responses(self, form_id: str) -> list[dict]: ...


class GoogleFormsClient:
    """Client REST minimal, authentifié par compte de service (JWT signé, sans dépendance Google)."""

    def __init__(self, service_account_json: str):
        if not service_account_json:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON manquant")
        self.sa = json.loads(service_account_json)
        self._token: tuple[str, float] | None = None

    async def _access_token(self, c: httpx.AsyncClient) -> str:
        if self._token and self._token[1] > time.time() + 60:
            return self._token[0]
        now = int(time.time())
        assertion = jwt.encode(
            {"iss": self.sa["client_email"], "scope": SCOPES, "aud": self.sa["token_uri"], "iat": now, "exp": now + 3600},
            self.sa["private_key"], algorithm="RS256",
        )
        r = await c.post(self.sa["token_uri"], data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                                      "assertion": assertion})
        r.raise_for_status()
        tok = r.json()
        self._token = (tok["access_token"], now + tok.get("expires_in", 3600))
        return self._token[0]

    async def _get(self, path: str, params: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=20) as c:
            token = await self._access_token(c)
            r = await c.get(f"{FORMS_API}/{path}", params=params, headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            return r.json()

    async def get_form(self, form_id: str) -> dict:
        return await self._get(quote(form_id))

    async def list_responses(self, form_id: str) -> list[dict]:
        out, page = [], None
        while True:
            data = await self._get(f"{quote(form_id)}/responses", {"pageToken": page} if page else None)
            out.extend(data.get("responses", []))
            page = data.get("nextPageToken")
            if not page:
                return out


def default_client() -> FormsClient:
    return GoogleFormsClient(get_settings().GOOGLE_SERVICE_ACCOUNT_JSON)


# --- Structure du formulaire ----------------------------------------------------------

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("’", "'")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def parse_structure(form: dict) -> list[dict]:
    """Liste ordonnée des questions : itemId, section, titre, type, questionIds (plusieurs pour une grille)."""
    section = (form.get("info") or {}).get("title", "")
    first_section = True
    out, order = [], 0
    for item in form.get("items", []):
        if "pageBreakItem" in item:
            section = item.get("title", "")
            first_section = False
            continue
        if "questionItem" in item:
            q = item["questionItem"]["question"]
            kind = next((k for k in ("textQuestion", "choiceQuestion", "fileUploadQuestion", "scaleQuestion",
                                     "dateQuestion", "timeQuestion", "ratingQuestion") if k in q), "other")
            choice_type = (q.get("choiceQuestion") or {}).get("type")
            has_images = any("image" in o for o in (q.get("choiceQuestion") or {}).get("options", []))
            qids = [{"qid": q["questionId"], "row": None}]
        elif "questionGroupItem" in item:
            kind, choice_type, has_images = "grid", None, False
            qids = [{"qid": x["questionId"], "row": (x.get("rowQuestion") or {}).get("title")}
                    for x in item["questionGroupItem"].get("questions", [])]
        else:
            continue  # texte, image, vidéo : pas une question
        order += 1
        out.append({"item_id": item["itemId"], "title": item.get("title", ""), "section": section,
                    "first_section": first_section, "kind": kind, "choice_type": choice_type,
                    "image_choice": has_images, "question_ids": qids, "order": order})
    return out


def _seed_match(q: dict, used: set[int]) -> tuple | None:
    t, sec = norm(q["title"]), norm(q["section"])
    candidates = []
    for row in SEED_QUESTIONS:
        n, s_sec, s_title = row[0], norm(row[1]), norm(row[2])
        if n in used:
            continue
        same_section = bool(sec) and (s_sec == sec or s_sec in sec or sec in s_sec)
        same_title = t == s_title or (len(s_title) >= 12 and (t.startswith(s_title[:40]) or s_title.startswith(t[:40])))
        # Intitulé court de la table (« Budget ») : accepté seulement dans la même section
        same_title = same_title or (same_section and t.startswith(s_title + " "))
        if not same_title:
            continue
        candidates.append((0 if same_section else 1, abs(n - q["order"]), row))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1]))
    best = candidates[0]
    # Intitulé ambigu (« Nombre de personnes attendues ») : la section doit correspondre
    if best[0] == 1 and sum(1 for r in SEED_QUESTIONS if norm(r[2]) == norm(best[2][2])) > 1:
        return None
    return best[2]


def suggest_rubric(q: dict, known: list[dict]) -> str:
    sec = norm(q["section"])
    same = [k["rubric"] for k in known if norm(k.get("section", "")) == sec and k.get("rubric")]
    if same:
        return Counter(same).most_common(1)[0][0]
    text = norm(q["title"] + " " + q["section"])
    for word, rubric in KEYWORDS:
        if norm(word) in text.split() or norm(word) in text:
            return rubric
    return "constraints"


def section_event(section: str) -> str | None:
    s = norm(section)
    for name, key in SECTION_EVENTS.items():
        if s.startswith(norm(name)):
            return key
    return None


# --- Synchronisation -------------------------------------------------------------------

async def sync(ctx: TenantContext, client: FormsClient | None = None) -> dict:
    settings = await S.get_settings(ctx)
    form_id = settings.get("form_id")
    if not form_id:
        return {"status": "not_configured"}
    client = client or default_client()
    try:
        form = await client.get_form(form_id)
        responses = await client.list_responses(form_id)
    except Exception as e:  # réseau, droits Google : on garde tout ce qui est déjà là
        await S.update_settings(ctx, {"sync_error": str(e)[:300]})
        return {"status": "error", "error": str(e)[:300]}

    stats = await _sync_questions(ctx, form_id, parse_structure(form), first_time=not settings.get("seed_applied"))
    stats.update(await _sync_responses(ctx, responses))
    await S.update_settings(ctx, {"last_sync": S.now(), "sync_error": None, "seed_applied": True,
                                  "responder_uri": form.get("responderUri"),
                                  "form_title": (form.get("info") or {}).get("title")})
    return {"status": "ok", **stats}


async def _sync_questions(ctx: TenantContext, form_id: str, items: list[dict], first_time: bool) -> dict:
    r = S.repo(ctx, S.QUESTIONS)
    existing = {d["_id"]: d for d in await r.find({}, limit=500)}
    present, used, new, renamed = set(), set(), 0, 0
    for q in items:
        present.add(q["item_id"])
        base = {"form_id": form_id, "title": q["title"], "section": q["section"], "kind": q["kind"],
                "choice_type": q["choice_type"], "image_choice": q["image_choice"],
                "question_ids": q["question_ids"], "order": q["order"], "event_key": section_event(q["section"])}
        if q["item_id"] in existing:
            old = existing[q["item_id"]]
            if old.get("title") != q["title"]:
                renamed += 1
            changes = {**base}
            if old.get("status") == "deleted":
                changes["status"] = "active" if old.get("rubric") else "to_classify"
            await r.update(q["item_id"], changes)
            continue
        seed = _seed_match(q, used) if first_time else None
        if seed:
            used.add(seed[0])
            await r.insert({"_id": q["item_id"], **base, "number": seed[0], "rubric": seed[3],
                            "fiche_field": seed[4], "module": seed[5], "status": "active", "suggestion": None})
        else:
            known = list(existing.values())
            suggestion = suggest_rubric(q, known)
            await r.insert({"_id": q["item_id"], **base, "number": None, "rubric": None, "fiche_field": None,
                            "module": None, "status": "to_classify", "suggestion": suggestion})
            new += 1
            if not first_time:
                await S.notify(ctx, "question_to_classify", f"Nouvelle question à classer : « {q['title']} »")
    deleted = 0
    for item_id, old in existing.items():
        if item_id not in present and old.get("status") != "deleted":
            await r.update(item_id, {"status": "deleted"})
            deleted += 1
    return {"questions": len(items), "new_questions": new, "renamed": renamed, "deleted": deleted}


def _answer_value(ans: dict) -> dict:
    out: dict = {"values": [], "files": []}
    for a in (ans.get("textAnswers") or {}).get("answers", []):
        out["values"].append(a.get("value", ""))
    for f in (ans.get("fileUploadAnswers") or {}).get("answers", []):
        out["files"].append({"id": f.get("fileId"), "name": f.get("fileName"), "mime": f.get("mimeType"),
                             "url": f"https://drive.google.com/open?id={f.get('fileId')}"})
    return out


async def _sync_responses(ctx: TenantContext, responses: list[dict]) -> dict:
    qmap, deleted_items = {}, set()
    for q in await S.repo(ctx, S.QUESTIONS).find({}, limit=500):
        if q.get("status") == "deleted":
            deleted_items.add(q["_id"])
        for x in q.get("question_ids", []):
            qmap[x["qid"]] = (q["_id"], x.get("row"))
    weddings = await S.repo(ctx, S.WEDDINGS).find({"status": {"$ne": "archived"}}, limit=500)
    by_email = {}
    for w in weddings:
        for p in w["info"]["partners"]:
            if p.get("email"):
                by_email[p["email"].lower()] = w

    r = S.repo(ctx, S.RESPONSES)
    created = updated = unassigned = 0
    for resp in responses:
        answers: dict[str, dict] = {}
        for qid, ans in (resp.get("answers") or {}).items():
            item_id, row = qmap.get(qid, (f"unknown:{qid}", None))
            val = _answer_value(ans)
            cur = answers.setdefault(item_id, {"values": [], "files": [], "rows": {}})
            if row:
                cur["rows"][row] = val["values"]
            else:
                cur["values"] += val["values"]
                cur["files"] += val["files"]
        email = (resp.get("respondentEmail") or "").lower() or None
        submitted = resp.get("lastSubmittedTime") or resp.get("createTime")
        old = await r.get(resp["responseId"])
        # Google efface les réponses d'une question supprimée : on garde celles déjà reçues
        for item_id, a in ((old or {}).get("answers") or {}).items():
            if item_id in deleted_items and item_id not in answers:
                answers[item_id] = a
        wedding_id = (old or {}).get("wedding_id") or (by_email.get(email) or {}).get("_id")
        data = {"respondent_email": email, "answers": answers, "submitted_at": submitted, "wedding_id": wedding_id}
        if not old:
            await r.insert({"_id": resp["responseId"], **data})
            created += 1
        elif old.get("submitted_at") != submitted:
            await r.update(resp["responseId"], data)
            updated += 1
        else:
            continue
        if wedding_id:
            await on_response(ctx, wedding_id, is_update=bool(old))
        else:
            unassigned += 1
    return {"responses_created": created, "responses_updated": updated, "unassigned": unassigned}


async def on_response(ctx: TenantContext, wedding_id: str, *, is_update: bool) -> None:
    wr = S.repo(ctx, S.WEDDINGS)
    w = await wr.get(wedding_id)
    if not w:
        return
    answers = await merged_answers(ctx, wedding_id)
    info, discrepancies = await apply_prefill(ctx, w, answers)
    sub = await latest_submission(ctx, wedding_id)
    await wr.update(wedding_id, {"info": info, "discrepancies": discrepancies,
                                 "questionnaire": {"submitted_at": sub, "status": "submitted"}})
    names = S.couple_names(info)
    await S.notify(ctx, "questionnaire_submitted",
                   f"{names} ont {'modifié' if is_update else 'rempli'} leur questionnaire.", wedding_id=wedding_id)
    opened = [d for d in discrepancies if d["status"] == "open" and d["id"] not in
              {x["id"] for x in w.get("discrepancies", [])}]
    if opened:
        await S.notify(ctx, "discrepancy", f"{names} : {len(opened)} différence(s) entre la fiche et le questionnaire.",
                       wedding_id=wedding_id)


async def latest_submission(ctx: TenantContext, wedding_id: str):
    docs = await S.repo(ctx, S.RESPONSES).find({"wedding_id": wedding_id}, sort=[("submitted_at", -1)], limit=1)
    return docs[0]["submitted_at"] if docs else None


async def merged_answers(ctx: TenantContext, wedding_id: str) -> dict[str, dict]:
    """Réponses d'un couple, toutes réponses confondues (les deux partenaires peuvent répondre) :
    la plus récente l'emporte question par question."""
    out: dict[str, dict] = {}
    for d in await S.repo(ctx, S.RESPONSES).find({"wedding_id": wedding_id}, sort=[("submitted_at", 1)], limit=50):
        for item_id, a in d.get("answers", {}).items():
            if a.get("values") or a.get("files") or a.get("rows"):
                out[item_id] = a
    return out


def answer_text(a: dict | None) -> str:
    if not a:
        return ""
    parts = [v for v in a.get("values", []) if v]
    parts += [f"{k} : {', '.join(v)}" for k, v in (a.get("rows") or {}).items()]
    parts += [f"Fichier : {f['name']}" for f in a.get("files", [])]
    return " ; ".join(parts)


# --- Préremplissage de la fiche --------------------------------------------------------

_NUM = re.compile(r"\d[\d\s.,]*")


def _ints(text: str) -> list[int]:
    out = []
    for m in _NUM.findall(text):
        digits = re.sub(r"[\s.,]", "", m)
        if digits:
            out.append(int(digits))
    return out


def _parse_budget(text: str) -> float | None:
    t = text.lower().replace("k€", "000").replace("k $", "000").replace("k$", "000")
    nums = [n for n in _ints(t) if n >= 100]
    return float(nums[0]) if nums else None


def _parse_time(text: str) -> str | None:
    m = re.search(r"(\d{1,2})\s*(?:h|:)\s*(\d{2})?", text.lower())
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2) or 0)
    return f"{hh:02d}:{mm:02d}" if hh < 24 and mm < 60 else None


def _parse_ceremony(text: str) -> str | None:
    t = norm(text)
    if "relig" in t:
        return "Religieuse"
    if "laiq" in t or "civil" in t or "secular" in t:
        return "Laïque"
    return None


def _parse_jobs(text: str, info: dict) -> list[str | None]:
    """« Annie : architecte. Patrick : professeur. » → professions par partenaire, si les prénoms sont reconnus."""
    jobs: list[str | None] = [None, None]
    for i, p in enumerate(info["partners"]):
        fn = p.get("first_name")
        if not fn:
            continue
        m = re.search(rf"{re.escape(fn)}\s*[:\-–]\s*([^.;\n,]+)", text, re.IGNORECASE)
        if m:
            jobs[i] = m.group(1).strip().capitalize()
    return jobs


def _get(info: dict, path: str):
    cur = info
    for part in path.split("."):
        cur = (cur or {}).get(part)
    return cur


def _set(info: dict, path: str, value) -> None:
    parts = path.split(".")
    cur = info
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def _candidates(field: str, text: str, info: dict) -> list[tuple[str, object]]:
    """(chemin dans la fiche, valeur proposée) pour une réponse liée à un champ de fiche."""
    if field == "budget":
        v = _parse_budget(text)
        return [("budget", v)] if v is not None else []
    if field == "guests":
        nums = _ints(text)
        if not nums:
            return []
        total, kids = nums[0], (nums[1] if len(nums) > 1 else None)
        out = [("guests.adults", total - (kids or 0))]
        if kids is not None:
            out.append(("guests.kids", kids))
        return out
    if field == "ceremony.type":
        v = _parse_ceremony(text)
        return [("ceremony.type", v)] if v else []
    if field == "ceremony.time":
        v = _parse_time(text)
        return [("ceremony.time", v)] if v else []
    if field in ("ceremony.place", "ceremony.confession"):
        return [(field, text.strip()[:200])] if text.strip() else []
    if field == "jobs":
        return [(f"partners.{i}.job", j) for i, j in enumerate(_parse_jobs(text, info)) if j]
    return []


def _get_path(info: dict, path: str):
    if path.startswith("partners."):
        _, i, key = path.split(".")
        return info["partners"][int(i)].get(key)
    return _get(info, path)


def _set_path(info: dict, path: str, value) -> None:
    if path.startswith("partners."):
        _, i, key = path.split(".")
        info["partners"][int(i)][key] = value
    else:
        _set(info, path, value)


async def apply_prefill(ctx: TenantContext, wedding: dict, answers: dict[str, dict]) -> tuple[dict, list[dict]]:
    info = json.loads(json.dumps(wedding["info"], default=str))
    discrepancies = {d["id"]: d for d in wedding.get("discrepancies", [])}
    questions = await S.repo(ctx, S.QUESTIONS).find({"fiche_field": {"$ne": None}}, limit=500)
    for q in questions:
        text = answer_text(answers.get(q["_id"]))
        if not text:
            continue
        for path, value in _candidates(q["fiche_field"], text, info):
            current = _get_path(info, path)
            did = f"{q['_id']}:{path}"
            if current in (None, ""):
                _set_path(info, path, value)
                discrepancies.pop(did, None)
            elif str(current).strip().lower() != str(value).strip().lower():
                prev = discrepancies.get(did)
                if prev and prev["status"] != "open" and prev["form_value"] == value:
                    continue  # déjà tranché par l'organisatrice pour cette même valeur
                discrepancies[did] = {"id": did, "field": path, "question_id": q["_id"], "question": q["title"],
                                      "fiche_value": current, "form_value": value, "status": "open"}
            else:
                discrepancies.pop(did, None)
    return info, list(discrepancies.values())


def resolve_discrepancy(wedding: dict, did: str, keep: str) -> tuple[dict, list[dict]]:
    info = wedding["info"]
    out = []
    found = False
    for d in wedding.get("discrepancies", []):
        if d["id"] == did and d["status"] == "open":
            found = True
            if keep == "form":
                _set_path(info, d["field"], d["form_value"])
            d = {**d, "status": f"kept_{keep}"}
        out.append(d)
    if not found:
        raise KeyError(did)
    return info, out


# --- Lien du formulaire pour les mariés ------------------------------------------------

def prefilled_url(responder_uri: str | None, questions: list[dict], info: dict) -> str | None:
    """Lien du formulaire intégré, prérempli avec ce que la fiche contient déjà (entry.<id décimal>)."""
    if not responder_uri:
        return None
    params = ["embedded=true"]
    values = {"ceremony.type": (info.get("ceremony") or {}).get("type"),
              "ceremony.place": (info.get("ceremony") or {}).get("place"),
              "ceremony.confession": (info.get("ceremony") or {}).get("confession")}
    for q in questions:
        v = values.get(q.get("fiche_field") or "")
        if not v or q.get("kind") == "grid":
            continue
        try:
            entry = int(q["question_ids"][0]["qid"], 16)
        except (ValueError, KeyError, IndexError):
            continue
        params.append(f"entry.{entry}={quote(str(v))}")
    sep = "&" if "?" in responder_uri else "?"
    return responder_uri + sep + "&".join(params)


def known_fields(info: dict) -> list[str]:
    """Informations déjà dans la fiche : présentées comme « déjà renseignées » aux mariés."""
    out = []
    if info.get("budget") is not None:
        out.append("budget")
    if (info.get("guests") or {}).get("adults") is not None:
        out.append("guests")
    c = info.get("ceremony") or {}
    for k in ("type", "place", "time"):
        if c.get(k):
            out.append(f"ceremony.{k}")
    if all(p.get("job") for p in info.get("partners", [])):
        out.append("jobs")
    return out
