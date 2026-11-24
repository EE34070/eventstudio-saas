from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.core.repository import TenantRepository
from app.core.tenancy import TenantContext, guard

router = APIRouter(prefix="/events", tags=["events"])

EventStatus = Literal["lead", "option", "confirmed", "done", "canceled"]


class Phase(BaseModel):
    kind: Literal["delivery", "setup", "operation", "teardown", "pickup"]
    starts_at: datetime
    ends_at: datetime | None = None


class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    title_i18n: dict[str, str] = {}  # titres traduits selon la langue du client
    status: EventStatus = "lead"
    starts_at: datetime
    ends_at: datetime | None = None
    phases: list[Phase] = []  # livraison / exploitation / retrait
    client_id: str | None = None
    organizer_id: str | None = None  # wedding planner / agence, distinct du client
    venue_ids: list[str] = []
    enabled_modules: list[str] = []  # modules visibles dans l'espace client pour CET événement
    brand_id: str | None = None

    @model_validator(mode="after")
    def _dates(self):
        if self.ends_at and self.ends_at < self.starts_at:
            raise ValueError("La fin doit être après le début")
        return self


class EventOut(EventIn):
    id: str


def _out(d: dict) -> EventOut:
    return EventOut(id=d["_id"], **{k: d[k] for k in EventIn.model_fields if k in d})


def repo(ctx: TenantContext = Depends(guard("events"))) -> TenantRepository:
    return TenantRepository(ctx, "events")


async def _check_refs(ctx: TenantContext, body: EventIn) -> None:
    """Les contacts référencés doivent appartenir à la même organisation."""
    contacts = TenantRepository(ctx, "contacts")
    for ref in filter(None, [body.client_id, body.organizer_id, *body.venue_ids]):
        if not await contacts.get(ref):
            raise HTTPException(422, f"Contact {ref} introuvable")
    unknown = set(body.enabled_modules) - ctx.entitlements.modules
    if unknown:
        raise HTTPException(422, f"Modules non disponibles : {sorted(unknown)}")


@router.get("", response_model=list[EventOut])
async def list_events(status: EventStatus | None = None, r: TenantRepository = Depends(repo)):
    return [_out(d) for d in await r.find({"status": status} if status else {}, sort=[("starts_at", 1)])]


@router.get("/{event_id}", response_model=EventOut)
async def get_event(event_id: str, r: TenantRepository = Depends(repo)):
    d = await r.get(event_id)
    if not d:
        raise HTTPException(404, "Événement introuvable")
    return _out(d)


@router.post("", response_model=EventOut, status_code=201)
async def create_event(body: EventIn, ctx: TenantContext = Depends(guard("events", "write"))):
    await _check_refs(ctx, body)
    return _out(await TenantRepository(ctx, "events").insert(body.model_dump(mode="python")))
