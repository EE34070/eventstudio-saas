import asyncio
import ipaddress
import logging
import os
import re
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

EMAIL_PROVIDER = (os.environ.get("EMAIL_PROVIDER") or "resend").strip().lower()  # resend | smtp
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME") or ""


def _cfg(name: str) -> str:
    v = (os.environ.get(name) or "").strip()
    if not v:
        raise HTTPException(503, f"Envoi d'e-mails non configuré : la variable {name} manque sur le serveur")
    return v

_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "reply with the code", "send your password", "cvv",
             "send us your password", "enter your password below", "confirm your card number",
             "your full card number", "seed phrase", "recovery phrase", "verify your card",
             "social security number", "confirm your bank details")
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan()
    scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} ≠ real link host {real!r} (G3)")


def mail_html(org_name: str, greeting: str, paragraphs: list, button: tuple | None = None, language: str = "fr-FR") -> str:
    from i18n import tr
    body = "".join(f'<p style="margin:0 0 14px">{escape(p)}</p>' for p in paragraphs)
    btn = (f'<p style="margin:22px 0"><a href="{escape(button[1], quote=True)}" style="background:#171717;color:#ffffff;padding:12px 22px;'
           f'border-radius:999px;text-decoration:none;font-weight:bold">{escape(button[0])}</a></p>') if button else ""
    return ('<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;font-size:15px;color:#171717;line-height:1.5">'
            f'<p style="margin:0 0 14px">{escape(greeting)}</p>{body}{btn}<p style="margin:0 0 14px">{escape(org_name)}</p>'
            f'<p style="font-size:12px;color:#888">{escape(tr("mail_footer", language, name=EMAIL_FROM_NAME))}</p></td></tr></table>')


def _send_smtp(to: str, subject: str, html: str, reply_to: str | None, attachments: list | None = None) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["To"], msg["From"] = subject, to, formataddr((EMAIL_FROM_NAME, _cfg("EMAIL_FROM")))
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content("Ce message est au format HTML.")
    msg.add_alternative(html, subtype="html")
    for name, data in attachments or []:
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    host, port = _cfg("SMTP_HOST"), int(os.environ.get("SMTP_PORT") or 587)
    with (smtplib.SMTP_SSL(host, port, timeout=30) if port == 465 else smtplib.SMTP(host, port, timeout=30)) as smtp:
        if port != 465:
            smtp.starttls()
        if os.environ.get("SMTP_USER"):
            smtp.login(os.environ["SMTP_USER"], _cfg("SMTP_PASSWORD"))
        smtp.send_message(msg)


async def _send_other(to: str, subject: str, html: str, reply_to: str | None, attachments: list | None = None) -> str | None:
    try:
        if EMAIL_PROVIDER == "smtp":
            await asyncio.to_thread(_send_smtp, to, subject, html, reply_to, attachments)
            return None
        payload = {"from": formataddr((EMAIL_FROM_NAME, _cfg("EMAIL_FROM"))), "to": [to], "subject": subject, "html": html}
        if reply_to:
            payload["reply_to"] = reply_to
        if attachments:
            import base64
            payload["attachments"] = [{"filename": n, "content": base64.b64encode(d).decode()} for n, d in attachments]
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post("https://api.resend.com/emails", headers={"Authorization": f"Bearer {_cfg('RESEND_API_KEY')}"}, json=payload)
        resp.raise_for_status()
        return resp.json().get("id")
    except HTTPException as e:
        logger.error(f"Email send failed ({EMAIL_PROVIDER}): {e.detail}")
        raise
    except smtplib.SMTPAuthenticationError:
        logger.error("Email send failed (smtp): authentication refused")
        raise HTTPException(502, "Envoi refusé par le serveur de messagerie : identifiant ou mot de passe d'application SMTP incorrect")
    except Exception as e:
        logger.error(f"Email send failed ({EMAIL_PROVIDER}): {e}")
        raise HTTPException(status_code=502, detail=f"L'e-mail n'a pas pu être envoyé ({type(e).__name__})")


async def send_email(*, to: str, subject: str, html: str, reply_to: str | None = None, attachments: list | None = None) -> str | None:
    _assert_safe_email(subject, html)
    if EMAIL_PROVIDER not in ("resend", "smtp"):
        raise HTTPException(503, "Envoi d'e-mails non configuré : EMAIL_PROVIDER doit valoir resend ou smtp")
    return await _send_other(to, subject, html, reply_to, attachments)
