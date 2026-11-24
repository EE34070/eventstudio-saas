"""Wedding planner : mariages, événements du week-end, fiche du couple, questionnaire Google Form,
récapitulatif IA, repas et boissons, espace privé des mariés (FR/EN)."""
from fastapi import APIRouter

from app.core.modules import ModuleManifest
from app.platform.invitations import register_accept_hook

from . import portal
from . import router as admin
from .service import AI_USAGE, FOOD, NOTIFS, QUESTIONS, RECAPS, RESPONSES, SETTINGS, WEDDINGS

router = APIRouter()
router.include_router(admin.router)
router.include_router(portal.router)
register_accept_hook("wedding_planner", portal.on_invitation_accepted)

MANIFEST = ModuleManifest(
    key="wedding_planner",
    name="Wedding planner",
    category="metiers",
    description="Mariages et événements du week-end, fiche du couple, questionnaire, récapitulatif, "
                "repas et boissons, espace privé des mariés",
    depends_on=["events", "planning"],
    permissions=["read", "write"],
    collections=[WEDDINGS, SETTINGS, QUESTIONS, RESPONSES, RECAPS, FOOD, NOTIFS, AI_USAGE],
    indexes={
        WEDDINGS: [[("org_id", 1), ("status", 1), ("info.date", 1)], [("org_id", 1), ("info.partners.email", 1)]],
        QUESTIONS: [[("org_id", 1), ("order", 1)], [("org_id", 1), ("status", 1)]],
        RESPONSES: [[("org_id", 1), ("wedding_id", 1), ("submitted_at", -1)]],
        FOOD: [[("org_id", 1), ("wedding_id", 1)]],
        NOTIFS: [[("org_id", 1), ("read", 1), ("created_at", -1)]],
    },
    router=router,
    status="beta",
)
