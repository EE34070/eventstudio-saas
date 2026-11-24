"""Facturation SaaS via Stripe Billing.

Stripe porte les prix, les essais, la TVA (Stripe Tax) et les factures d'abonnement.
Notre base ne garde que l'état utile aux droits : plan, statut, add-ons, modules métier.
Webhooks idempotents (billing_events) : un événement Stripe n'est jamais appliqué deux fois.
"""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.core.config import Settings, get_settings
from app.core.db import get_control_db

router = APIRouter(prefix="/billing", tags=["billing"])

# price_id Stripe → plan interne (à renseigner après création des prix dans Stripe)
PRICE_TO_PLAN: dict[str, str] = {
    # "price_essentiel_monthly": "essentiel",
    # "price_pro_monthly": "pro",
    # "price_agence_monthly": "agence",
}

HANDLED = {"customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(alias="Stripe-Signature"),
    settings: Settings = Depends(get_settings),
    db=Depends(get_control_db),
):
    import stripe

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(400, "Signature invalide")

    if await db.billing_events.find_one({"_id": event["id"]}):
        return {"status": "duplicate"}
    await db.billing_events.insert_one({"_id": event["id"], "type": event["type"], "at": datetime.now(UTC)})

    if event["type"] in HANDLED:
        sub = event["data"]["object"]
        org_id = sub["metadata"].get("org_id")
        price = sub["items"]["data"][0]["price"]["id"]
        status = "canceled" if event["type"].endswith("deleted") else sub["status"]
        await db.orgs.update_one(
            {"_id": org_id},
            {"$set": {
                "subscription.plan": PRICE_TO_PLAN.get(price, "essentiel"),
                "subscription.status": status,
                "subscription.stripe_subscription_id": sub["id"],
                "subscription.updated_at": datetime.now(UTC),
            }},
        )
    return {"status": "ok"}
