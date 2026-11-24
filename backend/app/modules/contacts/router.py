"""Routes de référence : c'est le modèle à reproduire pour chaque module.

1. Chaque route dépend de guard(<module>, <permission>).
2. Les données passent par TenantRepository (org_id imposé).
3. Schémas Pydantic distincts en entrée (Create/Update) et en sortie (Out) :
   on ne renvoie jamais un document brut (pas de fuite de champs internes).
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field

from app.core.repository import TenantRepository
from app.core.tenancy import TenantContext, guard

router = APIRouter(prefix="/contacts", tags=["contacts"])

ContactKind = Literal["person", "organization"]
ContactRole = Literal["client", "organizer", "venue", "supplier", "partner", "other"]


class ContactIn(BaseModel):
    kind: ContactKind = "person"
    display_name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = None
    roles: list[ContactRole] = []
    language: str = "fr"  # langue de communication (devis, e-mails, CGV)
    parent_id: str | None = None  # personne rattachée à une structure
    notes: str | None = None


class ContactPatch(BaseModel):
    display_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    roles: list[ContactRole] | None = None
    language: str | None = None
    notes: str | None = None


class ContactOut(ContactIn):
    id: str


def _out(doc: dict) -> ContactOut:
    return ContactOut(id=doc["_id"], **{k: doc.get(k) for k in ContactIn.model_fields if k in doc})


def repo(ctx: TenantContext = Depends(guard("contacts"))) -> TenantRepository:
    return TenantRepository(ctx, "contacts")


@router.get("", response_model=list[ContactOut])
async def list_contacts(
    role: ContactRole | None = None,
    q: str | None = Query(None, max_length=100),
    r: TenantRepository = Depends(repo),
):
    flt: dict = {}
    if role:
        flt["roles"] = role
    if q:
        import re
        flt["display_name"] = {"$regex": re.escape(q), "$options": "i"}
    return [_out(d) for d in await r.find(flt, sort=[("display_name", 1)])]


@router.get("/{contact_id}", response_model=ContactOut)
async def get_contact(contact_id: str, r: TenantRepository = Depends(repo)):
    doc = await r.get(contact_id)
    if not doc:
        raise HTTPException(404, "Contact introuvable")  # 404 aussi si le contact appartient à une autre org
    return _out(doc)


@router.post("", response_model=ContactOut, status_code=201,
             dependencies=[Depends(guard("contacts", "write"))])
async def create_contact(body: ContactIn, r: TenantRepository = Depends(repo)):
    return _out(await r.insert(body.model_dump()))


@router.patch("/{contact_id}", response_model=ContactOut,
              dependencies=[Depends(guard("contacts", "write"))])
async def update_contact(contact_id: str, body: ContactPatch, r: TenantRepository = Depends(repo)):
    doc = await r.update(contact_id, body.model_dump(exclude_unset=True))
    if not doc:
        raise HTTPException(404, "Contact introuvable")
    return _out(doc)


@router.delete("/{contact_id}", status_code=204,
               dependencies=[Depends(guard("contacts", "write"))])
async def delete_contact(contact_id: str, r: TenantRepository = Depends(repo)):
    if not await r.soft_delete(contact_id):
        raise HTTPException(404, "Contact introuvable")
