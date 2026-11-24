from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.repository import TenantRepository
from app.core.tenancy import TenantContext, guard

router = APIRouter(prefix="/inventory", tags=["inventory"])


class WarehouseIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = "main"  # main | onsite_depot (ex. chaises stockées sur un domaine)
    address: str | None = None


@router.get("/warehouses")
async def list_warehouses(ctx: TenantContext = Depends(guard("inventory"))):
    docs = await TenantRepository(ctx, "warehouses").find(sort=[("name", 1)])
    return [{"id": d["_id"], "name": d["name"], "kind": d["kind"]} for d in docs]


@router.post("/warehouses", status_code=201)
async def create_warehouse(body: WarehouseIn, ctx: TenantContext = Depends(guard("inventory", "write"))):
    d = await TenantRepository(ctx, "warehouses").insert(body.model_dump())
    return {"id": d["_id"], "name": d["name"], "kind": d["kind"]}
