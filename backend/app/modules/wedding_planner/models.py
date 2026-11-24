"""Schémas du module wedding_planner.

Un mariage (collection wp_weddings) porte une seule fiche d'informations, réutilisée
partout (récapitulatif, planning, repas…). Il est composé d'événements (Welcome dinner,
Jour J, Brunch, « Autre »), chacun avec date, lieu et nombre d'invités (estimation
saisie + nombre confirmé calculé depuis la Guest List quand elle existera).
"""
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

Lang = Literal["fr", "en"]
CeremonyType = Literal["Laïque", "Religieuse"]


class Partner(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: EmailStr | None = None
    phone: str = ""
    job: str = ""
    address: str = ""


class Guests(BaseModel):
    adults: int | None = Field(None, ge=0)
    kids: int | None = Field(None, ge=0)

    @property
    def total(self) -> int | None:
        if self.adults is None and self.kids is None:
            return None
        return (self.adults or 0) + (self.kids or 0)


class Ceremony(BaseModel):
    type: CeremonyType | None = None
    confession: str = ""
    place: str = ""
    time: str = ""  # HH:MM
    officiant: str = ""
    language: str = ""
    people: int | None = Field(None, ge=0)


class WeddingInfo(BaseModel):
    """La fiche : référence unique pour toutes les autres rubriques."""
    partners: list[Partner] = Field(default_factory=lambda: [Partner(), Partner()], min_length=2, max_length=2)
    same_address: bool = False
    date: str | None = None  # AAAA-MM-JJ
    venue: str = ""
    venue_address: str = ""
    budget: float | None = Field(None, ge=0)
    guests: Guests = Guests()
    ceremony: Ceremony = Ceremony()

    @field_validator("date")
    @classmethod
    def _date(cls, v):
        if v in (None, ""):
            return None
        from datetime import date
        date.fromisoformat(v)
        return v

    def normalized(self) -> "WeddingInfo":
        """« Même adresse que mon partenaire » : l'adresse du partenaire 2 suit celle du partenaire 1."""
        if self.same_address:
            self.partners[1].address = self.partners[0].address
        if self.ceremony.type != "Religieuse":
            self.ceremony.confession = ""
        return self


class WeddingEvent(BaseModel):
    id: str
    key: str  # wd | dj | br | x<...> (« Autre »)
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    fixed: bool = False  # Jour J : toujours actif
    date: str | None = None
    place: str = ""
    estimate: int | None = Field(None, ge=0)


class Rights(BaseModel):
    budget: bool = True
    vendor_prices: bool = True
    dday_planning: bool = False
    documents: bool = True
    edit_info: bool = True


class WeddingCreate(BaseModel):
    partner1_email: EmailStr
    partner2_email: EmailStr | None = None
    partner1_first_name: str = ""
    partner2_first_name: str = ""
    lang: Lang = "fr"
    welcome_dinner: bool = True
    brunch: bool = True
    date: str | None = None
    send_invitations: bool = True


class EventsIn(BaseModel):
    events: list[WeddingEvent]


class OpenSectionsIn(BaseModel):
    open_sections: list[str]


class NotesIn(BaseModel):
    notes: str = Field("", max_length=20000)


class SettingsIn(BaseModel):
    form_id: str | None = None
    form_url: str | None = None
    notify_email: EmailStr | None = None
    notification_prefs: dict[str, dict[str, bool]] | None = None
    rubrics: list[dict] | None = None


class QuestionPatch(BaseModel):
    rubric: str | None = None
    fiche_field: str | None = None
    module: str | None = None
    status: Literal["active", "to_classify"] | None = None


class ResolveDiscrepancy(BaseModel):
    keep: Literal["fiche", "form"]


class AssignResponse(BaseModel):
    wedding_id: str | None


class RecapPatch(BaseModel):
    text: str = Field(max_length=20000)


# --- Repas et boissons ----------------------------------------------------------

class Course(BaseModel):
    name: str = ""
    chosen: str = ""
    options: list[str] = []


class IncludedDrink(BaseModel):
    name: str = ""
    detail: str = ""


class ExternalDrink(BaseModel):
    name: str = ""
    supplier: str = ""
    per_guest: float = Field(0, ge=0, le=20)
    unit: Literal["bottle", "keg", "l"] = "bottle"


class FoodIn(BaseModel):
    vendor: str = ""
    formula: str = ""
    price: str = ""
    courses: list[Course] = []
    included: list[IncludedDrink] = []
    external: list[ExternalDrink] = []
    notes: str = ""  # notes internes : jamais visibles des mariés
