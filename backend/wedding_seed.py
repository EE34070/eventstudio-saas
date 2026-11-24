"""Wedding planner : configuration de départ (modifiable ensuite par chaque société).

- RUBRICS : rubriques du récapitulatif (ajout, suppression, renommage possibles).
- SEED_QUESTIONS : table de correspondance initiale des 95 questions du Google Form
  « Questionnaire Organisation / recherche prestataires ». Elle ne sert qu'à la
  PREMIÈRE association : au premier passage, chaque question du formulaire est
  rapprochée d'une ligne ci-dessous par section + intitulé, puis identifiée pour
  toujours par son itemId Google (jamais par son numéro ni son texte).
- FICHE_FIELDS : champs de la fiche qu'une réponse peut préremplir (si vides).
"""

RUBRICS: list[tuple[str, str]] = [
    ("couple", "Les mariés et leurs proches"),
    ("vision", "Vision et ambiance"),
    ("budget", "Budget et invités"),
    ("vendors", "Prestataires, animations et moments clés"),
    ("ceremony", "Cérémonie"),
    ("wd", "Welcome dinner"),
    ("dday", "Jour J : ambiance, repas et boissons"),
    ("brunch", "Brunch"),
    ("music", "Musique"),
    ("photo", "Photo, vidéo, maquillage et coiffure"),
    ("transport", "Transport et baby-sitter"),
    ("constraints", "Contraintes et points importants"),
]

FICHE_FIELDS: dict[str, str] = {
    "jobs": "Profession des partenaires",
    "budget": "Budget global",
    "guests": "Nombre d'invités et d'enfants",
    "ceremony.type": "Type de cérémonie",
    "ceremony.confession": "Confession",
    "ceremony.time": "Horaire de la cérémonie",
    "ceremony.place": "Lieu de la cérémonie",
}

MODULE_LINKS: dict[str, str] = {
    "food": "Repas et boissons",
    "vendors": "Prestataires (catégories à ouvrir)",
}

# Sections du formulaire liées à un événement : masquées si l'événement est désactivé
SECTION_EVENTS: dict[str, str] = {"welcome dinner": "wd", "brunch": "br"}

S1 = "Quelques questions pour mieux vous connaître"
S2 = "Votre mariage"
S3 = "Welcome dinner"
S4 = "Général, jour J"
S5 = "Cérémonie"
S6 = "Traiteur, jour du mariage"
S7 = "Brunch"
S8 = "Musique, jour du mariage"
S9 = "Photo / vidéo"
S10 = "Maquillage / coiffure"
S11 = "Transport"
S12 = "Baby-sitter"
S13 = "Autres"

# (n°, section, intitulé, rubrique, champ de fiche, module alimenté)
SEED_QUESTIONS: list[tuple[int, str, str, str, str | None, str | None]] = [
    (1, S1, "Pourriez-vous joindre une photo de vous deux ?", "couple", None, None),
    (2, S1, "Quelle est votre date de naissance à chacun ?", "couple", None, None),
    (3, S1, "Quelle est votre profession à chacun ?", "couple", "jobs", None),
    (4, S1, "Avez-vous des enfants? Si oui, pourriez-vous me communiquer leurs prénoms et âges ?", "couple", None, None),
    (5, S1, "Pourriez-vous m'en dire un peu plus sur votre famille et les personnes importantes qui vous entourent ?", "couple", None, None),
    (6, S1, "Combien de témoins avez-vous chacun ?", "couple", None, None),
    (7, S1, "Avez-vous des passions ?", "couple", None, None),
    (8, S1, "Si vous deviez choisir 3 mots qui vous décrivent, un souvenir qui compte pour vous, un détail qui vous caractérise ou encore une petite anecdote", "couple", None, None),
    (9, S1, "Avez-vous (vous-même) un régime spécial, une ou des allergies, des préférences alimentaires ?", "constraints", None, None),
    (10, S1, "Y a-t-il d'autres éléments importants à prendre en compte dans l'organisation de votre mariage que vous souhaiteriez me partager ?", "constraints", None, None),
    (11, S2, "Comment imaginez-vous votre mariage ?", "vision", None, None),
    (12, S2, "Ce qui compte le plus pour vous ce jour-là", "vision", None, None),
    (13, S2, "Ce que vous ne voulez surtout pas", "vision", None, None),
    (14, S2, "Avez-vous un tableau Pinterest à me partager afin que je puisse mieux comprendre votre vision et vos envies ?", "vision", None, None),
    (15, S2, "Budget", "budget", "budget", None),
    (16, S2, "Nombre de personnes attendues", "budget", "guests", None),
    (17, S2, "Type de cérémonie", "ceremony", "ceremony.type", None),
    (18, S2, "Si religieuse, pouvez-vous préciser de quelle confession ?", "ceremony", "ceremony.confession", None),
    (19, S2, "Pouvez-vous cocher les prestataires que vous souhaitez voir intervenir durant le week-end ?", "vendors", None, "vendors"),
    (20, S2, "Souhaitez-vous organiser des animations durant le week-end ?", "vendors", None, None),
    (21, S2, "Moments clés : souhaitez-vous prévoir l'un de ces moments ?", "vendors", None, None),
    (22, S3, "Nombre de personnes attendues", "wd", None, None),
    (23, S3, "Comment imaginez-vous cette soirée ? Avez-vous un thème ? Dress-code ?", "wd", None, None),
    (24, S3, "Avez-vous défini le lieu du welcome dinner ?", "wd", None, None),
    (25, S3, "Food : avez-vous une idée du style souhaité ?", "wd", None, "food"),
    (26, S3, "Souhaitez-vous un bar à cocktail ?", "wd", None, "food"),
    (27, S3, "Mobilier", "wd", None, "food"),
    (28, S3, "Ambiance musicale", "wd", None, None),
    (29, S3, "Si vous souhaitez de la musique live, quel style de musique aimeriez-vous ?", "wd", None, None),
    (30, S3, "Imaginez-vous une décoration particulière pour cet événement ?", "wd", None, None),
    (31, S3, "Y a-t-il d'autres éléments ou souhaits importants à prendre en compte dans l'organisation du welcome dinner ?", "wd", None, None),
    (32, S4, "Comment imaginez-vous cette journée ? Avez-vous un thème ? Dress-code ?", "dday", None, None),
    (33, S4, "Nombre de personnes attendues", "dday", None, None),
    (34, S4, "Souhaitez-vous prévoir un petit-déjeuner et/ou un déjeuner pour les invités résidant sur place ?", "dday", None, "food"),
    (35, S4, "Avez-vous défini le lieu du cocktail ?", "dday", None, "food"),
    (36, S4, "Avez-vous défini le lieu du dîner ?", "dday", None, "food"),
    (37, S5, "Avez-vous une idée de l'heure à laquelle vous souhaitez organiser la cérémonie ?", "ceremony", "ceremony.time", None),
    (38, S5, "Avez-vous défini le lieu de la cérémonie ?", "ceremony", "ceremony.place", None),
    (39, S5, "Officiant de cérémonie", "ceremony", None, None),
    (40, S5, "Avez-vous des envies ou des éléments particuliers à me partager concernant la cérémonie ?", "ceremony", None, None),
    (41, S6, "Food : avez-vous une idée du style souhaité ?", "dday", None, "food"),
    (42, S6, "Avez-vous à première vue des envies particulières pour le vin d'honneur/repas ?", "dday", None, "food"),
    (43, S6, "Souhaitez-vous prévoir des animations ou des stands particuliers pour le cocktail ou la soirée ?", "dday", None, "food"),
    (44, S6, "Souhaitez-vous faire une fontaine de champagne ?", "dday", None, "food"),
    (45, S6, "Souhaitez-vous un bar à cocktail (en + de celui du traiteur) ?", "dday", None, "food"),
    (46, S6, "Voulez-vous avoir une entrée / mise en bouche ou passer directement au plat en passant à table ?", "dday", None, "food"),
    (47, S6, "Préférez-vous des plats à partager sur table ou des plats individuels ?", "dday", None, "food"),
    (48, S6, "Souhaitez-vous du fromage ?", "dday", None, "food"),
    (49, S6, "Préférez-vous un buffet de desserts ou un dessert à l'assiette ?", "dday", None, "food"),
    (50, S6, "Avez-vous une idée du style de dessert ?", "dday", None, "food"),
    (51, S6, "Avez-vous une première liste des boissons souhaitées au cocktail ?", "dday", None, "food"),
    (52, S6, "Avez-vous une première liste des boissons souhaitées au repas ?", "dday", None, "food"),
    (53, S6, "Avez-vous une première liste des boissons souhaitées durant la soirée ?", "dday", None, "food"),
    (54, S6, "Y a-t-il d'autres éléments ou souhaits importants à prendre en compte dans la partie traiteur du jour J ?", "dday", None, "food"),
    (55, S7, "Nombre de personnes attendues", "brunch", None, None),
    (56, S7, "Avez-vous une idée de l'heure à laquelle vous souhaitez commencer le brunch ?", "brunch", None, None),
    (57, S7, "Comment imaginez-vous cette journée? Avez-vous un thème ? Dress-code ?", "brunch", None, None),
    (58, S7, "Avez-vous défini le lieu du brunch ?", "brunch", None, None),
    (59, S7, "Souhaitez-vous faire une \"pool party\" à la suite du brunch ?", "brunch", None, None),
    (60, S7, "Food : avez-vous une idée du style souhaité ?", "brunch", None, "food"),
    (61, S7, "Souhaitez-vous un bar à cocktail ?", "brunch", None, "food"),
    (62, S7, "Mobilier", "brunch", None, None),
    (63, S7, "Ambiance musicale", "brunch", None, None),
    (64, S7, "Imaginez-vous une décoration particulière pour cet événement ?", "brunch", None, None),
    (65, S7, "Y a-t-il d'autres éléments ou souhaits importants à prendre en compte dans l'organisation du brunch ?", "brunch", None, None),
    (66, S8, "Pour la cérémonie, quel type de musique souhaitez-vous ?", "music", None, None),
    (67, S8, "Pour le cocktail, quelle ambiance musicale imaginez-vous ?", "music", None, None),
    (68, S8, "Pour le dîner quelle ambiance musicale imaginez-vous ?", "music", None, None),
    (69, S8, "Pour la soirée quelle ambiance musicale imaginez-vous ?", "music", None, None),
    (70, S8, "Ambiance de la piste de danse", "music", None, None),
    (71, S8, "Heure de fin de soirée souhaitée", "music", None, None),
    (72, S8, "Y a-t-il d'autres éléments ou souhaits importants à prendre en compte dans la partie musique ?", "music", None, None),
    (73, S9, "Quel type de photographie préférez-vous ?", "photo", None, None),
    (74, S9, "Si vous avez déjà repéré un ou plusieurs comptes Instagram dont vous aimez le style, n'hésitez pas à me les partager.", "photo", None, None),
    (75, S9, "Souhaitez-vous un vidéaste ?", "photo", None, None),
    (76, S9, "Souhaitez-vous un photobooth ?", "photo", None, None),
    (77, S9, "Souhaitez-vous que le photographe soit présent", "photo", None, None),
    (78, S9, "Souhaitez-vous que le vidéaste soit présent", "photo", None, None),
    (79, S9, "Y a-t-il d'autres éléments ou souhaits importants à prendre en compte dans la partie photo/vidéo ?", "photo", None, None),
    (80, S10, "De quels services avez-vous besoin ?", "photo", None, None),
    (81, S10, "Combien d'invités / demoiselles d'honneur auront besoin de la coiffure ?", "photo", None, None),
    (82, S10, "Combien d'invités / demoiselles d'honneur auront besoin du maquillage ?", "photo", None, None),
    (83, S10, "Avez-vous des inspirations ou des idées concernant vos attentes en matière de coiffure ?", "photo", None, None),
    (84, S10, "Avez-vous des inspirations ou des idées concernant vos attentes en matière de maquillage ?", "photo", None, None),
    (85, S10, "Allergies, peau sensible ou produits à éviter ?", "photo", None, None),
    (86, S10, "Accessoires de coiffure prévus", "photo", None, None),
    (87, S10, "Y a-t-il d'autres éléments ou souhaits importants à prendre en compte dans la partie maquillage/coiffure ?", "photo", None, None),
    (88, S11, "Souhaitez-vous un service de transport pour le vendredi soir ?", "transport", None, None),
    (89, S11, "Souhaitez-vous un service de transport le samedi ?", "transport", None, None),
    (90, S11, "Souhaitez-vous un service de transport pour le brunch ?", "transport", None, None),
    (91, S12, "Souhaitez-vous un service de garde ?", "transport", None, None),
    (92, S12, "Combien d'enfants sont à prendre en charge ? Quel âge auront-ils ?", "transport", None, None),
    (93, S12, "Souhaitez-vous que les baby-sitters arrivent avant ou après la cérémonie ?", "transport", None, None),
    (94, S12, "Pour ce service, avez-vous des besoins ou des envies particulières ?", "transport", None, None),
    (95, S13, "Si vous avez d'autres éléments à me partager, des idées ou des envies qui vous sont venus au cours de ce questionnaire", "constraints", None, None),
]

# Mots-clés pour suggérer une rubrique à une question nouvelle hors section connue
KEYWORDS: list[tuple[str, str]] = [
    ("musique", "music"), ("dj", "music"), ("danse", "music"),
    ("photo", "photo"), ("vidéo", "photo"), ("video", "photo"), ("coiffure", "photo"), ("maquillage", "photo"),
    ("transport", "transport"), ("navette", "transport"), ("baby", "transport"), ("enfant", "transport"),
    ("cérémonie", "ceremony"), ("ceremonie", "ceremony"), ("officiant", "ceremony"),
    ("budget", "budget"), ("invités", "budget"), ("invites", "budget"),
    ("traiteur", "dday"), ("repas", "dday"), ("boisson", "dday"), ("dessert", "dday"),
    ("prestataire", "vendors"), ("animation", "vendors"),
    ("ambiance", "vision"), ("style", "vision"),
    ("allergie", "constraints"), ("régime", "constraints"),
]

DEFAULT_RIGHTS = {"budget": True, "vendor_prices": True, "dday_planning": False, "documents": True, "edit_info": True}

# Rubriques de l'espace des mariés ouvertes par défaut (les autres : « Bientôt »)
DEFAULT_OPEN_SECTIONS = ["home", "info", "quest"]
COUPLE_SECTIONS = ["home", "info", "quest", "vendors", "guests", "seating", "food", "budget",
                   "group_photos", "music", "design", "planning", "documents"]
# Rubriques effectivement disponibles dans le produit (les autres ne peuvent pas encore être ouvertes)
AVAILABLE_SECTIONS = {"home", "info", "quest", "food"}

NOTIFICATION_TYPES: dict[str, str] = {
    "questionnaire_submitted": "Questionnaire rempli ou modifié par les mariés",
    "info_changed": "Information renseignée ou modifiée par les mariés",
    "comment": "Nouveau commentaire",
    "invitation_accepted": "Un partenaire a rejoint son espace",
    "discrepancy": "Différence détectée entre la fiche et le questionnaire",
    "question_to_classify": "Nouvelle question à classer dans le formulaire",
    # Phases suivantes (déjà déclarés, activables quand les modules existent)
    "vendor_validated": "Prestataire validé",
    "document_added": "Document ajouté",
    "contract_signed": "Contrat signé",
    "payment_due": "Paiement à venir ou en retard",
    "task_due": "Tâche échue",
    "planning_changed": "Modification du planning",
}
DEFAULT_NOTIFICATION_PREFS = {k: {"app": True, "email": k in {"questionnaire_submitted", "invitation_accepted"}}
                              for k in NOTIFICATION_TYPES}
