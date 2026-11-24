from datetime import datetime, timezone

from core import DEMO_SLUG, new_id
from routes_ops import normalize

U = "https://images.unsplash.com/"
PHOTOS = [
    U + "photo-1565006070318-4bebbdc281c4?crop=entropy&cs=srgb&fm=jpg&q=80&w=1200",
    U + "photo-1680375999828-8e85eef77a0b?crop=entropy&cs=srgb&fm=jpg&q=80&w=1200",
    U + "photo-1698933485983-8ec889b747b8?crop=entropy&cs=srgb&fm=jpg&q=80&w=1200",
    U + "photo-1588571088301-67a44e3d7ab7?crop=entropy&cs=srgb&fm=jpg&q=80&w=1200",
    U + "photo-1707333514312-39cf7658479c?crop=entropy&cs=srgb&fm=jpg&q=80&w=1200",
    U + "photo-1574482211311-45a2169db57c?crop=entropy&cs=srgb&fm=jpg&q=80&w=1200",
]

TEAM = [
    ("Direction Exclusivity", "contact@exclusivity-events.com", "Direction", "admin", ["Commercial", "Direction artistique"], "#B4643C", 0),
    ("Clara Rossi", "", "Gérante", "gerant", ["Gestion", "Wedding planning"], "#8E5A9B", 0),
    ("Julien Ferrand", "", "Chef de projet", "chef_projet", ["Régie générale", "Son"], "#2F7D6D", 350),
    ("Sarah Benali", "", "Commerciale", "commercial", ["Vente", "Mariages"], "#C2843A", 0),
    ("Maxime Garcia", "", "Ingénieur son", "technicien", ["Son", "Console Yamaha", "Permis C"], "#3B6EA8", 280),
    ("Lucas Martin", "", "Éclairagiste", "technicien", ["Lumière", "GrandMA3", "Structure"], "#A8463B", 260),
    ("Inès Moreau", "", "DJ / Animatrice", "technicien", ["DJ", "MC", "Photobooth"], "#6B8E3B", 400),
    ("Nathalie Roux", "", "Comptable", "comptable", ["Comptabilité"], "#5E6A75", 0),
]

VENUES = [
    ("Domaine des Oliviers", "Domaine", "Chemin de la Pinette", "13100", "Aix-en-Provence", 43.5450, 5.4050, 220,
     "Accès semi-remorque par l'allée nord, aire de déchargement à 30 m", "Tri 63A + 2× mono 32A en régie", "Limiteur 95 dB(A) après 1h",
     "Montage dès 8h la veille", "Démontage avant 11h le lendemain", 0),
    ("Mas des Alpilles", "Mas provençal", "Route de Saint-Rémy", "13810", "Eygalières", 43.7610, 4.9500, 160,
     "Porteur 12 t max, chemin étroit (2,8 m)", "Tri 32A uniquement — groupe conseillé", "Pas de limiteur, coupure musique 2h",
     "Montage à partir de 10h", "Démontage jusqu'à 14h J+1", 1),
    ("Bastide Saint-Clair", "Bastide", "Les Imberts", "84220", "Gordes", 43.9110, 5.2000, 140,
     "Accès 19 t, parking gravillonné", "Tri 63A", "Limiteur 90 dB(A)", "Montage J-1 après 14h", "Démontage J+1 avant 12h", 2),
    ("Château de Valbelle", "Château", "Route du Castellet", "83330", "Le Castellet", 43.2030, 5.7750, 300,
     "Quai de chargement, monte-charge 1,5 t", "2× Tri 63A + 125A sur demande", "Limiteur 100 dB(A)", "Montage dès 7h", "Démontage nuit autorisé", 3),
    ("Le Grand Pavillon", "Salle de réception", "Quai de la Joliette", "13002", "Marseille", 43.3110, 5.3650, 600,
     "Livraison par quai, créneaux 7h–10h", "Tri 125A en fond de scène", "Limiteur 102 dB(A)", "Montage 7h–17h", "Démontage 1h–6h", 4),
    ("Les Terrasses de l'Estaque", "Rooftop", "Plage de l'Estaque", "13016", "Marseille", 43.3600, 5.3150, 250,
     "Ascenseur de charge 1 t, hauteur 2,1 m", "Tri 32A ×2", "Limiteur 92 dB(A) — voisinage", "Montage dès 9h", "Démontage avant 3h", 5),
    ("Villa Azuréa", "Villa", "Boulevard du Cap", "06160", "Antibes", 43.5530, 7.1270, 180,
     "Véhicules ≤ 3,5 t uniquement", "Tri 63A", "Limiteur 95 dB(A)", "Montage J-1", "Démontage J+1 matin", 0),
]

CONTACTS = [
    ("particulier", "client", "Camille", "Durand", "", "camille.durand@exemple.fr", "06 12 34 56 78", "Aix-en-Provence", "Salon du mariage"),
    ("particulier", "client", "Léa", "Martin", "", "lea.martin@exemple.fr", "06 22 45 67 89", "Avignon", "Instagram"),
    ("entreprise", "client", "Marc", "Lefèvre", "Calanques Digital", "events@calanques-digital.exemple", "04 91 00 11 22", "Marseille", "Recommandation"),
    ("entreprise", "client", "Sophie", "Garnier", "Groupe Azur Immobilier", "s.garnier@azur-immo.exemple", "04 94 10 20 30", "Toulon", "Site web"),
    ("particulier", "client", "Inès", "Haddad", "", "ines.haddad@exemple.fr", "07 61 23 45 67", "Arles", "Wedding planner partenaire"),
    ("entreprise", "client", "Antoine", "Morel", "Inovatech Méditerranée", "a.morel@inovatech.exemple", "04 93 55 66 77", "Sophia-Antipolis", "LinkedIn"),
    ("entreprise", "client", "Hélène", "Blanc", "Banque Provençale", "h.blanc@banque-provencale.exemple", "04 91 77 88 99", "Marseille", "Appel d'offres"),
    ("entreprise", "prospect", "Paul", "Vidal", "Clinique du Littoral", "p.vidal@clinique-littoral.exemple", "04 91 12 13 14", "Marseille", "Site web"),
    ("particulier", "client", "Martine", "Bernard", "", "martine.bernard@exemple.fr", "06 45 98 76 54", "Cavaillon", "Bouche-à-oreille"),
    ("particulier", "prospect", "Juliette", "Roche", "", "juliette.roche@exemple.fr", "06 70 80 90 10", "Toulon", "Salon du mariage"),
    ("particulier", "prospect", "Sofia", "Lopez", "", "sofia.lopez@exemple.fr", "06 33 21 43 65", "Nîmes", "Instagram"),
    ("particulier", "prospect", "Emma", "Faure", "", "emma.faure@exemple.fr", "06 54 32 10 98", "Aix-en-Provence", "Mariages.net"),
]

EQUIPMENT = [
    ("SON-001", "Enceinte active L-Acoustics X12", "Sonorisation", 8, 85, 3200, 20),
    ("SON-002", "Caisson de basses SB18", "Sonorisation", 4, 110, 4500, 60),
    ("SON-003", "Enceinte compacte RCF ART 712", "Sonorisation", 12, 35, 900, 18),
    ("SON-004", "Console numérique Yamaha QL1", "Sonorisation", 2, 180, 9000, 25),
    ("SON-005", "Micro HF Shure ULXD (kit)", "Sonorisation", 10, 30, 1100, 2),
    ("SON-006", "Micro filaire Shure SM58", "Sonorisation", 16, 8, 120, 0.3),
    ("LUM-001", "Lyre Beam 230 7R", "Éclairage", 12, 45, 1800, 16),
    ("LUM-002", "Projecteur PAR LED sur batterie", "Éclairage", 40, 12, 350, 3),
    ("LUM-003", "Barre LED Wash", "Éclairage", 16, 18, 450, 5),
    ("LUM-004", "Machine à brouillard lourd", "Éclairage", 3, 60, 1500, 12),
    ("LUM-005", "Console lumière GrandMA3 compact", "Éclairage", 1, 150, 12000, 15),
    ("STR-001", "Pont alu 290 Trio 3 m", "Structure", 20, 15, 400, 12),
    ("STR-002", "Pied de levage 6 m (240 kg)", "Structure", 6, 35, 1200, 45),
    ("STR-003", "Praticable de scène 2×1 m", "Structure", 24, 20, 450, 30),
    ("VID-001", "Borne photobooth Miroir", "Vidéo & Bornes", 3, 250, 6000, 40),
    ("VID-002", "Écran LED 3×2 m", "Vidéo & Bornes", 2, 450, 25000, 300),
    ("VID-003", "Vidéoprojecteur 10 000 lumens", "Vidéo & Bornes", 3, 120, 5500, 15),
    ("DJ-001", "Platine Pioneer CDJ-3000", "DJ", 4, 70, 2500, 5),
    ("DJ-002", "Table de mixage Pioneer DJM-900NXS2", "DJ", 2, 60, 2000, 7),
    ("DJ-003", "Booth DJ lumineux", "DJ", 3, 50, 900, 25),
    ("ENR-001", "Groupe électrogène 60 kVA", "Énergie", 2, 280, 18000, 1200),
    ("ENR-002", "Kit câblage P17 32A", "Énergie", 10, 15, 300, 10),
    ("MOB-001", "Piste de danse LED (dalle 1 m²)", "Mobilier", 60, 9, 250, 8),
    ("MOB-002", "Mange-debout lumineux", "Mobilier", 20, 12, 180, 6),
]

PACKS = [
    ("Pack Mariage Prestige", "dj", "DJ + sonorisation cocktail & soirée + lumières d'ambiance", 2490,
     [("SON-001", 4), ("SON-002", 2), ("DJ-001", 2), ("DJ-002", 1), ("DJ-003", 1), ("LUM-002", 12), ("LUM-001", 4)],
     ["DJ 8h", "Micro HF cérémonie", "Rendez-vous de préparation"], ["Saxophoniste", "Feu froid ouverture de bal"]),
    ("Pack Sono Conférence", "son_lumiere", "Diffusion plénière jusqu'à 300 pers. avec technicien", 1450,
     [("SON-003", 4), ("SON-004", 1), ("SON-005", 4), ("VID-003", 1)], ["Technicien son 10h"], ["Captation vidéo"]),
    ("Pack Lumière Gala", "son_lumiere", "Show lumière asservi + mise en valeur architecturale", 1980,
     [("LUM-001", 8), ("LUM-003", 8), ("LUM-004", 1), ("LUM-005", 1), ("STR-001", 8)], ["Éclairagiste 10h"], ["Gobo logo"]),
    ("Borne Photobooth 400 tirages", "photobooth", "Borne miroir + impression illimitée 400 tirages", 690,
     [("VID-001", 1)], ["Installation", "Galerie en ligne"], ["Livre d'or", "Accessoires premium"]),
    ("Location Piste LED 25 m²", "loueur_materiel", "Piste de danse LED blanche, livrée posée", 420,
     [("MOB-001", 25)], ["Livraison & pose"], []),
]


def _e(code, title, typ, client, venue, start, end, setup, ret, status, guests, chef, prest, equip, team, **kw):
    return dict(code=code, title=title, type=typ, client=client, venue=venue, start=start, end=end, setup=setup, ret=ret,
                status=status, guests=guests, chef=chef, prest=prest, equip=equip, team=team, **kw)


DJ_FIELDS = {"style": "Pop, Disco, Électro 2000", "playlist_wanted": "Daft Punk, Dalida, Beyoncé", "playlist_banned": "Macarena",
             "rundown": "Cérémonie 16h · Cocktail 17h30 · Entrée des mariés 20h · Ouverture de bal 23h", "options": "Saxophoniste"}

EVENTS = [
    _e("EVT-2026-001", "Mariage Camille & Thomas", "Mariage", 0, 0, "2026-09-12T15:00", "2026-09-13T04:00", "2026-09-11T14:00",
       "2026-09-13T13:00", "cloture", 160, 2, [("dj", "Pack Mariage Prestige", 2490, 900, DJ_FIELDS)],
       [("SON-001", 4), ("SON-002", 2), ("DJ-001", 2), ("LUM-002", 16)], [(6, "DJ"), (4, "Technicien son")],
       returned=True, paid=True, deposit=1100),
    _e("EVT-2026-002", "Séminaire annuel Calanques Digital", "Séminaire", 2, 5, "2026-10-08T09:00", "2026-10-09T18:00",
       "2026-10-07T15:00", "2026-10-09T23:00", "facture", 120, 2, [("son_lumiere", "Pack Sono Conférence", 1450, 450, {})],
       [("SON-003", 4), ("SON-004", 1), ("SON-005", 4), ("VID-003", 2)], [(4, "Ingénieur son")], returned=True, paid=False, deposit=900),
    _e("EVT-2026-003", "Mariage Léa & Hugo", "Mariage", 1, 2, "2026-10-17T16:00", "2026-10-18T03:00", "2026-10-16T14:00",
       "2026-10-18T12:00", "facture", 130, 2, [("dj", "Pack Mariage Prestige", 2490, 900, DJ_FIELDS), ("photobooth", "Borne Photobooth 400 tirages", 690, 120, {})],
       [("SON-001", 4), ("DJ-001", 2), ("VID-001", 1), ("LUM-002", 12)], [(6, "DJ"), (5, "Éclairagiste")], returned=True, paid=True, deposit=1300),
    _e("EVT-2026-004", "Soirée 20 ans Groupe Azur Immobilier", "Soirée d'entreprise", 3, 3, "2026-11-13T19:00", "2026-11-14T02:00",
       "2026-11-13T08:00", "2026-11-14T10:00", "realise", 280, 2, [("son_lumiere", "Pack Lumière Gala", 1980, 700, {}), ("dj", "DJ soirée corporate", 1200, 400, {"style": "Funk, House"})],
       [("LUM-001", 8), ("LUM-003", 8), ("STR-001", 8), ("SON-001", 6), ("SON-002", 2)], [(5, "Éclairagiste"), (4, "Ingénieur son"), (6, "DJ")],
       returned=False, paid=False, deposit=2000),
    _e("EVT-2026-005", "Mariage Inès & Karim", "Mariage", 4, 1, "2026-11-21T16:00", "2026-11-22T03:00", "2026-11-20T13:00",
       "2026-11-22T14:00", "en_preparation", 150, 2, [("dj", "Pack Mariage Prestige", 2490, 900, DJ_FIELDS), ("loueur_materiel", "Location Piste LED 25 m²", 420, 60, {})],
       [("SON-001", 4), ("SON-002", 2), ("DJ-001", 2), ("DJ-003", 1), ("MOB-001", 25), ("ENR-001", 1)], [(6, "DJ"), (4, "Technicien son"), (2, "Régisseur")],
       returned=False, paid=False, deposit=1200, rental={"deposit_amount": 1500, "deposit_status": "encaissee", "out_at": "2026-11-20T09:00", "return_at": "2026-11-22T16:00"}),
    _e("EVT-2026-006", "Séminaire Inovatech Méditerranée", "Séminaire", 5, 6, "2026-11-26T09:00", "2026-11-27T18:00", "2026-11-25T14:00",
       "2026-11-27T22:00", "confirme", 90, 2, [("son_lumiere", "Pack Sono Conférence", 1450, 450, {})],
       [("SON-003", 4), ("SON-004", 1), ("SON-005", 6), ("VID-003", 1)], [], returned=False, paid=False, deposit=600),
    _e("EVT-2026-007", "Gala de fin d'année Banque Provençale", "Gala", 6, 4, "2026-12-04T19:00", "2026-12-05T02:00", "2026-12-04T07:00",
       "2026-12-05T12:00", "confirme", 450, 2, [("son_lumiere", "Pack Lumière Gala", 1980, 700, {}), ("son_lumiere", "Diffusion plénière & discours", 1600, 500, {})],
       [("LUM-001", 10), ("LUM-003", 10), ("LUM-005", 1), ("STR-001", 12), ("SON-001", 8), ("SON-002", 4), ("VID-002", 2)],
       [(5, "Éclairagiste"), (4, "Ingénieur son"), (2, "Régisseur général")], returned=False, paid=False, deposit=3500),
    _e("EVT-2026-008", "Soirée de Noël Clinique du Littoral", "Soirée d'entreprise", 7, 5, "2026-12-05T19:30", "2026-12-06T01:00",
       "2026-12-05T10:00", "2026-12-06T09:00", "demande", 180, 3, [("dj", "DJ & animation", 1100, 350, {"style": "Variété, Années 80"})],
       [("LUM-001", 6), ("SON-001", 2), ("DJ-001", 2)], [], returned=False, paid=False, deposit=0),
    _e("EVT-2026-009", "Arbre de Noël Calanques Digital", "Soirée d'entreprise", 2, 5, "2026-12-12T14:00", "2026-12-12T19:00",
       "2026-12-12T09:00", "2026-12-12T22:00", "devis_envoye", 150, 3, [("photobooth", "Borne Photobooth 400 tirages", 690, 120, {}), ("dj", "Animation enfants", 650, 200, {})],
       [("VID-001", 1), ("SON-003", 2)], [], returned=False, paid=False, deposit=0),
    _e("EVT-2026-010", "Anniversaire 50 ans Martine Bernard", "Anniversaire", 8, 2, "2026-12-19T20:00", "2026-12-20T03:00", "2026-12-19T12:00",
       "2026-12-20T12:00", "confirme", 90, 3, [("dj", "DJ soirée", 950, 350, {"style": "Disco, Funk"})],
       [("SON-003", 2), ("DJ-001", 2), ("LUM-002", 10), ("MOB-001", 16)], [(6, "DJ")], returned=False, paid=False, deposit=400),
    _e("EVT-2026-011", "Réveillon de la Saint-Sylvestre", "Soirée privée", 5, 6, "2026-12-31T20:00", "2027-01-01T05:00", "2026-12-31T09:00",
       "2027-01-01T13:00", "confirme", 160, 2, [("dj", "DJ & MC Réveillon", 1800, 600, {"options": "MC, Feu froid minuit"}), ("son_lumiere", "Ambiance lumière", 900, 300, {})],
       [("SON-001", 4), ("SON-002", 2), ("LUM-001", 6), ("DJ-001", 2), ("DJ-003", 1)], [(6, "DJ"), (5, "Éclairagiste")], returned=False, paid=False, deposit=1500),
    _e("EVT-2027-001", "Convention commerciale Groupe Azur", "Séminaire", 3, 4, "2027-03-18T09:00", "2027-03-19T17:00", "2027-03-17T13:00",
       "2027-03-19T22:00", "demande", 400, 3, [], [], [], returned=False, paid=False, deposit=0),
    _e("EVT-2027-002", "Mariage Juliette & Antoine", "Mariage", 9, 3, "2027-05-22T16:00", "2027-05-23T04:00", "2027-05-21T14:00",
       "2027-05-23T13:00", "devis_envoye", 200, 2, [("dj", "Pack Mariage Prestige", 2490, 900, DJ_FIELDS), ("photobooth", "Borne Photobooth 400 tirages", 690, 120, {})],
       [("SON-001", 4), ("SON-002", 2), ("DJ-001", 2), ("VID-001", 1), ("MOB-001", 25)], [], returned=False, paid=False, deposit=0),
    _e("EVT-2027-003", "Mariage Sofia & Raphaël", "Mariage", 10, 0, "2027-06-12T15:30", "2027-06-13T03:00", "2027-06-11T14:00",
       "2027-06-13T12:00", "demande", 180, 3, [("dj", "Pack Mariage Prestige", 2490, 900, {})], [], [], returned=False, paid=False, deposit=0),
    _e("EVT-2027-004", "Mariage Emma & Lucas", "Mariage", 11, 1, "2027-07-03T16:00", "2027-07-04T03:00", "2027-07-02T14:00",
       "2027-07-04T14:00", "devis_envoye", 140, 2, [("dj", "Pack Mariage Prestige", 2490, 900, DJ_FIELDS)],
       [("SON-001", 4), ("DJ-001", 2), ("LUM-002", 12), ("ENR-001", 1)], [], returned=False, paid=False, deposit=0),
]


VEHICLES = [("Master L3H2", "GH-412-KT", 1300, 13), ("Porteur 12 t", "FB-208-RM", 5500, 38), ("Kangoo utilitaire", "GZ-731-LP", 650, 3.3)]


async def seed_vehicles(db) -> None:
    org = await db.orgs.find_one({"slug": DEMO_SLUG}, {"_id": 0, "id": 1})
    if not org or await db.vehicles.find_one({"org_id": org["id"]}):
        return
    now = datetime.now(timezone.utc).isoformat()
    await db.vehicles.insert_many([{"id": new_id(), "org_id": org["id"], "created_at": now, "name": n, "plate": p,
                                    "capacity_kg": c, "volume_m3": v, "active": True} for n, p, c, v in VEHICLES])


async def seed_demo(db) -> None:
    if await db.orgs.find_one({"slug": DEMO_SLUG}):
        return
    now = datetime.now(timezone.utc).isoformat()
    org_id = new_id()
    await db.orgs.insert_one({
        "id": org_id, "slug": DEMO_SLUG, "name": "Exclusivity Events", "legal_name": "Exclusivity Events SAS",
        "siret": "[SIRET]", "vat_number": "[N° TVA]", "address": "[Adresse]", "zip": "", "city": "Aix-en-Provence",
        "phone": "", "email": "contact@exclusivity-events.com", "website": "", "logo_url": "",
        "legal_mentions": "[Mentions légales à compléter]", "iban": "", "payment_terms": "Acompte de 30 % à la signature, solde à J+7.",
        "quote_prefix": "DEV", "invoice_prefix": "FAC", "default_vat": 20, "deposit_percent": 30,
        "modules": ["loueur_materiel", "son_lumiere", "dj", "photobooth"], "created_at": now})

    def base(**d):
        return {"id": new_id(), "org_id": org_id, "created_at": now, **d}

    team = [base(name=n, email=e, phone="", job=j, access_role=r, skills=s, color=c, day_rate=dr, active=True,
                 unavailabilities=[], user_id=None) for n, e, j, r, s, c, dr in TEAM]
    team[4]["unavailabilities"] = [{"start": "2026-12-24", "end": "2026-12-27", "reason": "Congés"}]
    venues = [base(name=n, type=t, address=a, zip=z, city=c, lat=la, lng=lo, capacity=cap, contact_name="Régisseur du lieu",
                   contact_phone="", contact_email="", truck_access=tr, electricity=el, sound_limiter=sl, setup_hours=su,
                   teardown_hours=td, photos=[PHOTOS[p]], notes="") for n, t, a, z, c, la, lo, cap, tr, el, sl, su, td, p in VENUES]
    contacts = [base(kind=k, status=s, first_name=f, last_name=l, company=co, email=em, phone=ph, address="", city=ci,
                     source=so, tags=[], notes="", interactions=[{"id": new_id(), "type": "appel", "note": "Premier contact, besoin qualifié.",
                                                                  "at": now, "by": "Sarah Benali"}])
                for k, s, f, l, co, em, ph, ci, so in CONTACTS]
    equipment = [base(ref=r, name=n, category=c, photo="", qty_total=q, price_day=p, replacement_value=rv, weight_kg=w, volume_m3=0,
                      state="bon", notes="", qty_maintenance=0, maintenance_log=[]) for r, n, c, q, p, rv, w in EQUIPMENT]
    by_ref = {e["ref"]: e for e in equipment}
    gen = by_ref["ENR-001"]
    gen.update(qty_maintenance=1, state="maintenance",
               maintenance_log=[{"id": new_id(), "at": now, "action": "start", "qty": 1, "note": "Révision 500 h + remplacement filtre", "by": "Julien Ferrand"}])
    by_ref["LUM-001"]["maintenance_log"] = [{"id": new_id(), "at": now, "action": "end", "qty": 1, "note": "Lampe remplacée", "by": "Lucas Martin"}]
    packs = [base(name=n, module=m, description=d, price=p, items=[{"equipment_id": by_ref[r]["id"], "qty": q} for r, q in it],
                  services=sv, options=op, active=True) for n, m, d, p, it, sv, op in PACKS]
    eqs = {e["id"]: e for e in equipment}
    events = []
    for ev in EVENTS:
        d = base(code=ev["code"], title=ev["title"], type=ev["type"], status=ev["status"], client_id=contacts[ev["client"]]["id"],
                 venue_id=venues[ev["venue"]]["id"], start=ev["start"], end=ev["end"], setup_start=ev["setup"], return_end=ev["ret"],
                 guests=ev["guests"], budget=0, chef_projet_id=team[ev["chef"]]["id"], notes="",
                 prestations=[{"id": new_id(), "module": m, "title": t, "price": p, "cost": c, "fields": f} for m, t, p, c, f in ev["prest"]],
                 equipment=[{"equipment_id": by_ref[r]["id"], "qty": q, "price_day": None, "state_out": "", "state_in": "", "qty_returned": 0}
                            for r, q in ev["equip"]],
                 team=[{"member_id": team[i]["id"], "role": role, "start": ev["setup"], "end": ev["ret"], "confirmed": True} for i, role in ev["team"]],
                 planning=[{"date": ev["setup"][:10], "time": ev["setup"][11:16], "label": "Chargement & départ dépôt"},
                           {"date": ev["start"][:10], "time": ev["start"][11:16], "label": "Début de la prestation"},
                           {"date": ev["ret"][:10], "time": ev["ret"][11:16], "label": "Retour dépôt"}],
                 rental={"deposit_amount": 0, "deposit_status": "non_demandee", "out_at": "", "return_at": "", "out_checked_by": "",
                         "return_checked_by": "", "notes": "", **ev.get("rental", {})},
                 material_returned=ev["returned"], invoice_paid=ev["paid"], deposit_paid=ev["deposit"], extra_costs=0,
                 history=[{"at": now, "by": "Données de démonstration", "action": "Création", "detail": f"Événement créé ({ev['code']})"}])
        if ev["returned"]:
            for l in d["equipment"]:
                l.update(state_out="OK", state_in="OK", qty_returned=l["qty"])
        events.append(normalize(d, eqs))
    await db.team.insert_many(team)
    await db.venues.insert_many(venues)
    await db.contacts.insert_many(contacts)
    await db.equipment.insert_many(equipment)
    await db.packs.insert_many(packs)
    await db.events.insert_many(events)
    await db.counters.insert_many([{"org_id": org_id, "key": "event-2026", "seq": 11}, {"org_id": org_id, "key": "event-2027", "seq": 4}])
