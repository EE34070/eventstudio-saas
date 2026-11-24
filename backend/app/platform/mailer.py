"""E-mails transactionnels (invitations, notifications).

Fournisseur : Resend (API HTTP). Sans RESEND_API_KEY (développement, tests, QA),
rien n'est envoyé : l'e-mail est seulement journalisé. Aucun e-mail réel en test.
"""
import logging

import httpx

from app.core.config import get_settings

log = logging.getLogger("mailer")
SENT_IN_DEV: list[dict] = []  # consultable dans les tests


async def send_email(to: str | list[str], subject: str, html: str, *, reply_to: str | None = None) -> bool:
    s = get_settings()
    recipients = [to] if isinstance(to, str) else list(to)
    payload = {"from": s.MAIL_FROM, "to": recipients, "subject": subject, "html": html}
    if reply_to:
        payload["reply_to"] = reply_to
    if not s.RESEND_API_KEY:
        SENT_IN_DEV.append(payload)
        log.info("E-mail non envoyé (pas de RESEND_API_KEY) : %s → %s", subject, recipients)
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post("https://api.resend.com/emails", json=payload,
                             headers={"Authorization": f"Bearer {s.RESEND_API_KEY}"})
            r.raise_for_status()
        return True
    except httpx.HTTPError:
        log.exception("Échec d'envoi d'e-mail : %s", subject)
        return False
