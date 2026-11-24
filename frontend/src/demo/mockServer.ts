/**
 * Faux serveur du MODE DÉMO (VITE_DEMO=1) : reproduit en mémoire les routes du module
 * wedding_planner pour montrer les vrais écrans sans backend. Données fictives.
 * Jamais chargé en production.
 */
type Any = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const today = new Date("2026-11-24T12:00:00");
const days = (d: string | null) => (d ? Math.max(0, Math.round((new Date(`${d}T12:00:00`).getTime() - today.getTime()) / 864e5)) : null);
const uid = () => Math.random().toString(36).slice(2, 12);
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const emptyCer = { type: null, confession: "", place: "", time: "", officiant: "", language: "", people: null };
const partner = (first_name: string, last_name = "", email: string | null = null, extra: Any = {}) =>
  ({ first_name, last_name, email, phone: "", job: "", address: "", ...extra });
const events = (date: string | null, wd = true, br = true, est: [number | null, number | null, number | null] = [null, null, null]) => {
  const shift = (n: number) => (date ? new Date(new Date(`${date}T12:00:00`).getTime() + n * 864e5).toISOString().slice(0, 10) : null);
  return [
    { id: uid(), key: "wd", name: "Welcome dinner", enabled: wd, fixed: false, date: shift(-1), place: "", estimate: est[0] },
    { id: uid(), key: "dj", name: "Jour J", enabled: true, fixed: true, date, place: "", estimate: est[1] },
    { id: uid(), key: "br", name: "Brunch", enabled: br, fixed: false, date: shift(1), place: "", estimate: est[2] },
  ];
};
const RIGHTS = { budget: true, vendor_prices: true, dday_planning: false, documents: true, edit_info: true };

const W: Any[] = [
  { id: "annie-patrick", lang: "en", rights: { ...RIGHTS }, open_sections: ["home", "info", "quest", "food"], notes: "", status: "active",
    info: { partners: [partner("Annie", "Moreau", "annie@example.com", { phone: "+33 6 00 00 00 01", job: "Architecte", address: "12 rue des Lilas, 69003 Lyon, France" }),
      partner("Patrick", "Lemaire", "patrick@example.com", { phone: "+33 6 00 00 00 02", job: "Professeur", address: "12 rue des Lilas, 69003 Lyon, France" })],
      same_address: true, date: "2027-06-26", venue: "Domaine des Oliviers", venue_address: "Route de Saint-Rémy, 13210 Saint-Rémy-de-Provence",
      budget: 48000, guests: { adults: 92, kids: 20 },
      ceremony: { type: "Laïque", confession: "", place: "Allée des oliviers", time: "16:00", officiant: "Julien Moreau, +33 6 00 00 00 03", language: "Français et anglais", people: 112 } },
    events: events("2027-06-26", true, true, [60, 110, 50]), questionnaire: { status: "submitted", submitted_at: "2026-11-18T10:00:00Z" },
    discrepancies: [{ id: "i15:budget", field: "budget", question: "Budget", fiche_value: 48000, form_value: 52000, status: "open" }] },
  { id: "emma-lucas", lang: "fr", rights: { ...RIGHTS }, open_sections: ["home", "info", "quest"], notes: "", status: "active",
    info: { partners: [partner("Emma", "Roy", "emma@example.com"), partner("Lucas", "Gagnon", "lucas@example.com")], same_address: false,
      date: "2027-09-11", venue: "Château Saint-Antoine, Québec", venue_address: "", budget: 62000, guests: { adults: 120, kids: 20 }, ceremony: { ...emptyCer, type: "Religieuse", confession: "Catholique" } },
    events: events("2027-09-11", true, false, [70, 140, null]), questionnaire: { status: "pending" }, discrepancies: [] },
  { id: "sofia-james", lang: "en", rights: { ...RIGHTS }, open_sections: ["home", "info", "quest"], notes: "", status: "active",
    info: { partners: [partner("Sofia", "", "sofia@example.com"), partner("James", "", "james@example.com")], same_address: false,
      date: "2028-05-20", venue: "", venue_address: "", budget: 35000, guests: { adults: null, kids: null }, ceremony: { ...emptyCer } },
    events: events("2028-05-20", false, false, [null, 90, null]), questionnaire: { status: "pending" }, discrepancies: [] },
];
const INVITES: Record<string, string[]> = { "annie-patrick": ["accepted", "pending"], "emma-lucas": ["accepted", "accepted"], "sofia-james": ["pending", "pending"] };

const RUBRICS = [["couple", "Les mariés et leurs proches"], ["vision", "Vision et ambiance"], ["budget", "Budget et invités"],
  ["vendors", "Prestataires, animations et moments clés"], ["ceremony", "Cérémonie"], ["wd", "Welcome dinner"],
  ["dday", "Jour J : ambiance, repas et boissons"], ["brunch", "Brunch"], ["music", "Musique"],
  ["photo", "Photo, vidéo, maquillage et coiffure"], ["transport", "Transport et baby-sitter"], ["constraints", "Contraintes et points importants"]]
  .map(([key, title]) => ({ key, title }));

// Questionnaire d'Annie & Patrick (extrait du Google Form) : [section, event_key, [[question, réponse, rubrique, n°]]]
const Q: [string, string | null, [string, string, string, number][]][] = [
  ["Quelques questions pour mieux vous connaître", null, [["Quelle est votre profession à chacun ?", "Annie : architecte. Patrick : professeur.", "couple", 3],
    ["Avez-vous des enfants ?", "Non", "couple", 4], ["Votre famille et les personnes importantes", "Parents de la mariée divorcés, chacun remarié. Parents du marié ensemble.", "couple", 5],
    ["Combien de témoins avez-vous chacun ?", "2 chacun", "couple", 6], ["Régime spécial, allergies, préférences alimentaires", "1 végétarien, 1 allergie aux fruits à coque", "constraints", 9]]],
  ["Votre mariage", null, [["Comment imaginez-vous votre mariage ?", "Simple, chaleureux, lumineux. Champêtre chic.", "vision", 11],
    ["Ce qui compte le plus pour vous ce jour-là", "Que nos proches se sentent bien.", "vision", 12], ["Ce que vous ne voulez surtout pas", "Trop de protocole, une soirée trop électro.", "vision", 13],
    ["Budget", "52 000 $, plafond souple", "budget", 15], ["Type de cérémonie", "Laïque", "ceremony", 17],
    ["Prestataires souhaités durant le week-end", "Traiteur jour J, photographe, DJ, fleuriste, coiffeuse, maquilleuse", "vendors", 19],
    ["Moments clés", "First look, première danse, vœux privés", "vendors", 21]]],
  ["Welcome dinner", "wd", [["Nombre de personnes attendues", "60", "wd", 22], ["Food : avez-vous une idée du style souhaité ?", "Food truck pizza, brasero", "wd", 25], ["Souhaitez-vous un bar à cocktail ?", "Peut-être", "wd", 26]]],
  ["Général, jour J", null, [["Nombre de personnes attendues", "112", "dday", 33], ["Avez-vous défini le lieu du dîner ?", "Terrasse et grange du domaine", "dday", 36]]],
  ["Cérémonie", null, [["Heure souhaitée pour la cérémonie", "16 h", "ceremony", 37], ["Lieu de la cérémonie", "Allée des oliviers", "ceremony", 38],
    ["Envies particulières pour la cérémonie", "Vœux personnels, un ami proche comme maître de cérémonie", "ceremony", 40]]],
  ["Traiteur, jour du mariage", null, [["Food : avez-vous une idée du style souhaité ?", "Repas assis", "dday", 41], ["Souhaitez-vous faire une fontaine de champagne ?", "Oui, au cocktail", "dday", 44],
    ["Style de dessert", "Wedding cake et mignardises", "dday", 50]]],
  ["Brunch", "br", [["Nombre de personnes attendues", "50", "brunch", 55], ["Heure du brunch", "11 h 30", "brunch", 56], ["Pool party après le brunch ?", "Non", "brunch", 59]]],
  ["Musique, jour du mariage", null, [["Musique de la cérémonie", "Violoniste", "music", 66], ["Ambiance du cocktail", "Groupe de jazz", "music", 67], ["Soirée", "DJ et saxophoniste", "music", 69], ["Heure de fin de soirée", "4 h", "music", 71]]],
  ["Photo / vidéo", null, [["Quel type de photographie préférez-vous ?", "Naturel", "photo", 73], ["Souhaitez-vous un vidéaste ?", "Oui", "photo", 75], ["Présence du photographe", "Les 3 jours", "photo", 77]]],
  ["Maquillage / coiffure", null, [["De quels services avez-vous besoin ?", "Maquillage, coiffure", "photo", 80], ["Invitées coiffées / maquillées", "4 / 4", "photo", 81]]],
  ["Transport", null, [["Transport vendredi soir, samedi, brunch", "Oui, non, oui", "transport", 88]]],
  ["Baby-sitter", null, [["Souhaitez-vous un service de garde ?", "Oui, le jour du mariage", "transport", 91], ["Enfants à garder", "6 enfants, de 2 à 10 ans", "transport", 92]]],
  ["Autres", null, [["Autres éléments ou questions", "Une question sur l'accès de plain-pied pour un invité en fauteuil roulant.", "constraints", 95]]],
];
const QUESTIONS: Any[] = Q.flatMap(([section, ev, qs]) => qs.map(([title, , rubric, number]) => ({
  id: `q${number}`, number, order: number, section, title, kind: "textQuestion", rubric, event_key: ev, status: "active", suggestion: null,
  fiche_field: ({ 3: "jobs", 15: "budget", 17: "ceremony.type", 37: "ceremony.time", 38: "ceremony.place" } as Record<number, string>)[number] ?? null,
  module: [25, 26, 41, 44, 50].includes(number) ? "food" : number === 19 ? "vendors" : null,
})));
QUESTIONS.push({ id: "qnew", number: null, order: 96, section: "Votre mariage", title: "Souhaitez-vous un feu d'artifice ou des lanternes ?", kind: "textQuestion",
  rubric: null, fiche_field: null, module: null, status: "to_classify", suggestion: "vendors", event_key: null });
const ANSWERS: Record<string, Record<string, string>> = {
  "annie-patrick": Object.fromEntries(Q.flatMap(([, , qs]) => qs.map(([, a, , n]) => [`q${n}`, a]))),
};

const plainRecap = (wid: string) => RUBRICS.map((r) => {
  const w = W.find((x) => x.id === wid)!;
  const on = new Set(w.events.filter((e: Any) => e.enabled).map((e: Any) => e.key));
  const lines = QUESTIONS.filter((q) => q.rubric === r.key && (!q.event_key || on.has(q.event_key)) && ANSWERS[wid]?.[q.id])
    .map((q) => `${q.title.replace(/[ ?:]+$/, "")} : ${ANSWERS[wid][q.id]}`);
  return { key: r.key, title: r.title, text: lines.join("\n"), generated: lines.join("\n"), edited: false, proposal: null, source: "plain" };
});
const AI: Record<string, string> = {
  couple: "Annie, architecte, et Patrick, professeur. Pas d'enfants. Parents de la mariée divorcés et remariés : prévoir les tables et les photos en conséquence. 2 témoins chacun.",
  vision: "Simple, chaleureux, lumineux. Champêtre chic. Priorité : le bien-être des proches. À éviter : trop de protocole, soirée trop électro.",
  budget: "Plafond souple. Le formulaire indique 52 000 $, la fiche 48 000 $ : à confirmer avec le couple. Postes prioritaires à préciser.",
  vendors: "Traiteur jour J, photographe, DJ, fleuriste, coiffeuse, maquilleuse. Moments clés : first look, première danse, vœux privés.",
  ceremony: "Vœux personnels, un ami proche comme maître de cérémonie.",
  wd: "60 personnes. Food truck pizza et brasero. Bar à cocktail : peut-être.",
  dday: "112 personnes, repas assis, wedding cake et mignardises, fontaine de champagne au cocktail. Dîner sur la terrasse et dans la grange.",
  brunch: "50 personnes à 11 h 30, sans pool party.",
  music: "Violoniste à la cérémonie, groupe de jazz au cocktail, DJ et saxophoniste en soirée. Fin à 4 h.",
  photo: "Photographie naturelle, vidéaste, photographe les 3 jours. Maquillage et coiffure : 4 personnes chacun.",
  transport: "Transport vendredi soir et brunch. Garde d'enfants le jour du mariage, 6 enfants de 2 à 10 ans.",
  constraints: "1 végétarien, 1 allergie aux fruits à coque. Accès de plain-pied pour un invité en fauteuil roulant.",
};
const RECAPS: Record<string, Any> = {
  "annie-patrick": { generated_at: "2026-11-18T11:00:00Z", rubrics: RUBRICS.map((r) => ({ key: r.key, title: r.title, text: AI[r.key], generated: AI[r.key], edited: false, proposal: null, source: "ai" })) },
};
const FOOD: Record<string, Any> = {
  "annie-patrick:wd": { vendor: "Pizza & Brasero (food truck)", formula: "Food truck, 2 heures de service", price: "2 400 $", notes: "",
    courses: [{ name: "Entrée", chosen: "Burrata et tomates", options: ["Burrata et tomates", "Planche de charcuterie"] }, { name: "Plat", chosen: "Pizzas au feu de bois, 3 saveurs", options: ["Margherita", "Truffe", "Légumes"] }, { name: "Dessert", chosen: "Glace maison", options: [] }],
    included: [{ name: "Softs et eau", detail: "À volonté" }, { name: "Bar à limonade", detail: "Inclus" }],
    external: [{ name: "Vin rosé", supplier: "Domaine Exemple", per_guest: 0.5, unit: "bottle" }, { name: "Bière artisanale", supplier: "Brasserie Exemple", per_guest: 0.05, unit: "keg" }] },
  "annie-patrick:dj": { vendor: "Maison Exemple Table", formula: "Dîner assis, trois services", price: "95 $ par personne", notes: "Confirmer avec le traiteur l'horaire d'arrivée de l'équipe. Acompte versé en janvier.",
    courses: [{ name: "Cocktail", chosen: "6 pièces par personne", options: ["Blini saumon", "Tartelette chèvre", "Croquette jambon"] }, { name: "Entrée", chosen: "Velouté de saison", options: ["Velouté", "Foie gras"] },
      { name: "Plat", chosen: "Poulet rôti, légumes de printemps", options: ["Poulet", "Poisson du jour", "Risotto végétarien"] }, { name: "Fromage", chosen: "Plateau après le plat", options: [] }, { name: "Dessert", chosen: "Wedding cake et mignardises", options: ["Framboise", "Citron"] }],
    included: [{ name: "Eau et softs", detail: "Pendant le repas" }, { name: "Café et thé", detail: "Avec le dessert" }],
    external: [{ name: "Vin rouge", supplier: "Domaine Exemple", per_guest: 0.4, unit: "bottle" }, { name: "Vin blanc", supplier: "Domaine Exemple", per_guest: 0.4, unit: "bottle" },
      { name: "Champagne", supplier: "Maison Exemple", per_guest: 0.5, unit: "bottle" }, { name: "Bière", supplier: "Brasserie Exemple", per_guest: 0.03, unit: "keg" }] },
};
const DIETS: Record<string, Any[]> = {
  "annie-patrick:dj": [{ label: "Végétarien", names: "Marie L., Tom R.", allergy: false }, { label: "Vegan", names: "Lucie P.", allergy: false },
    { label: "Sans gluten", names: "Paul D., Anne S.", allergy: false }, { label: "fruits à coque", names: "Julien M.", allergy: true }],
  "annie-patrick:wd": [{ label: "Végétarien", names: "Marie L., Tom R.", allergy: false }, { label: "fruits à coque", names: "Julien M.", allergy: true }],
  "annie-patrick:br": [{ label: "fruits à coque", names: "Julien M.", allergy: true }],
};
const CONFIRMED: Record<string, Record<string, number>> = { "annie-patrick": { wd: 56, dj: 112 } };
const now = Date.now();
const NOTIFS: Any[] = [
  ["Annie a modifié la fiche : adresse.", 12, "annie-patrick", false], ["Annie & Patrick ont rempli leur questionnaire.", 60 * 20, "annie-patrick", false],
  ["Annie & Patrick : 1 différence entre la fiche et le questionnaire.", 60 * 20, "annie-patrick", false],
  ["Nouvelle question à classer : « Souhaitez-vous un feu d'artifice ou des lanternes ? »", 60 * 26, null, true],
  ["Emma (Emma & Lucas) a rejoint son espace.", 60 * 50, "emma-lucas", true],
].map(([text, min, wid, read], i) => ({ id: `n${i}`, kind: "info_changed", text, wedding_id: wid, read, at: new Date(now - (min as number) * 60000).toISOString() }));
const SETTINGS: Any = {
  form_id: "1nG9CCTxUqPafON1n-8PmzNgN4j_cgfPMjysauNq0sLg", form_url: "https://docs.google.com/forms/d/1nG9CCTxUqPafON1n-8PmzNgN4j_cgfPMjysauNq0sLg/edit",
  form_title: "Questionnaire Organisation / recherche prestataires", notify_email: "contact@example.com", last_sync: new Date(now - 6 * 60000).toISOString(), sync_error: null,
  rubrics: RUBRICS, google_configured: true, service_account: "formulaires@eventstudio-demo.iam.gserviceaccount.com",
  notification_types: { questionnaire_submitted: "Questionnaire rempli ou modifié par les mariés", info_changed: "Information renseignée ou modifiée par les mariés",
    comment: "Nouveau commentaire", invitation_accepted: "Un partenaire a rejoint son espace", discrepancy: "Différence détectée entre la fiche et le questionnaire",
    question_to_classify: "Nouvelle question à classer dans le formulaire", vendor_validated: "Prestataire validé", document_added: "Document ajouté",
    contract_signed: "Contrat signé", payment_due: "Paiement à venir ou en retard", task_due: "Tâche échue", planning_changed: "Modification du planning" },
  notification_prefs: {} as Any,
};
for (const k of Object.keys(SETTINGS.notification_types)) SETTINGS.notification_prefs[k] = { app: true, email: ["questionnaire_submitted", "invitation_accepted"].includes(k) };
const UNASSIGNED: Any[] = [{ id: "r-x", email: "j.martin@example.com", submitted_at: "2026-11-21T09:00:00Z", answers: 41 }];

// --- calculs (mêmes règles que le serveur) ---
const names = (w: Any) => w.info.partners.map((p: Any) => p.first_name).filter(Boolean).join(" & ") || "Nouveau mariage";
const progress = (w: Any) => {
  const i = w.info, c = i.ceremony;
  const checks = [i.partners.every((p: Any) => p.first_name && p.last_name && p.email), !!i.date, !!i.venue, i.budget != null,
    i.guests.adults != null || i.guests.kids != null, !!c.type, !!(c.place && c.time)];
  return Math.round((60 * checks.filter(Boolean).length) / checks.length + (w.questionnaire.submitted_at ? 40 : 0));
};
const evOut = (w: Any) => w.events.map((e: Any) => {
  const confirmed = CONFIRMED[w.id]?.[e.key] ?? null;
  return { ...e, confirmed, guests: confirmed ?? e.estimate, guests_source: confirmed ? "guest_list" : "estimate" };
});
const out = (w: Any) => ({ ...clone(w), names: names(w), days_left: days(w.info.date), progress: progress(w), events: evOut(w),
  discrepancies: w.discrepancies.filter((d: Any) => d.status === "open") });
const card = (w: Any) => {
  const dj = evOut(w).find((e: Any) => e.key === "dj");
  const total = w.info.guests.adults == null && w.info.guests.kids == null ? null : (w.info.guests.adults ?? 0) + (w.info.guests.kids ?? 0);
  return { id: w.id, names: names(w), date: w.info.date, days_left: days(w.info.date), venue: w.info.venue, guests: dj?.confirmed ?? total ?? dj?.estimate,
    budget: w.info.budget, progress: progress(w), questionnaire: w.questionnaire.status, open_discrepancies: w.discrepancies.filter((d: Any) => d.status === "open").length,
    vendors: null, documents: null, next_payment: null, next_task: null };
};
const foodView = (w: Any, key: string, couple = false) => {
  const ev = evOut(w).find((e: Any) => e.key === key);
  if (!ev) throw new Error("Événement introuvable");
  const g = ev.guests;
  const f = FOOD[`${w.id}:${key}`] ? clone(FOOD[`${w.id}:${key}`]) : null;
  if (f) {
    f.external = f.external.map((x: Any) => ({ ...x, quantity: g == null ? null : Math.ceil(g * x.per_guest) }));
    if (couple) { delete f.notes; if (!w.rights.vendor_prices) f.price = null; }
  }
  return { event: ev, enabled: ev.enabled, guests: g, guests_source: ev.guests_source, food: f, diets: DIETS[`${w.id}:${key}`] ?? [], kids: null };
};
const questionnaire = (w: Any) => {
  const on = new Set(w.events.filter((e: Any) => e.enabled).map((e: Any) => e.key));
  const sections: Any[] = [];
  for (const q of [...QUESTIONS].sort((a, b) => a.order - b.order)) {
    if (q.event_key && !on.has(q.event_key)) continue;
    if (!sections.length || sections[sections.length - 1].title !== q.section) sections.push({ title: q.section, questions: [], answered: 0 });
    const answer = ANSWERS[w.id]?.[q.id] ?? "";
    const s = sections[sections.length - 1];
    s.questions.push({ id: q.id, title: q.title, kind: q.kind, answer, files: [], rows: {}, deleted: q.status === "deleted", to_classify: q.status === "to_classify",
      rubric: RUBRICS.find((r) => r.key === q.rubric)?.title ?? null, modified_in_fiche: false });
    if (answer) s.answered++;
  }
  return { status: w.questionnaire.status, submitted_at: w.questionnaire.submitted_at ?? null, connected: true, last_sync: SETTINGS.last_sync,
    sections, discrepancies: w.discrepancies.filter((d: Any) => d.status === "open") };
};
const setPath = (o: Any, path: string, v: unknown) => { const ps = path.split("."); let c = o; ps.slice(0, -1).forEach((p) => (c = c[p])); c[ps[ps.length - 1]] = v; };
const notify = (text: string, wid: string | null) => NOTIFS.unshift({ id: uid(), kind: "info_changed", text, wedding_id: wid, read: false, at: new Date().toISOString() });

const COUPLE_ID = "annie-patrick";
const SECTIONS = ["home", "info", "quest", "vendors", "guests", "seating", "food", "budget", "group_photos", "music", "design", "planning", "documents"];

export async function mockApi(path: string, init: RequestInit): Promise<unknown> {
  await new Promise((r) => setTimeout(r, 120));
  const method = (init.method ?? "GET").toUpperCase();
  const body = init.body ? JSON.parse(String(init.body)) : undefined;
  const [p, qs] = path.split("?");
  const seg = p.split("/").filter(Boolean);
  const get = (id: string) => { const w = W.find((x) => x.id === id && x.status !== "deleted"); if (!w) throw new Error("Mariage introuvable"); return w; };

  if (seg[0] === "portal") {
    const w = get(COUPLE_ID);
    const r = seg[2];
    if (!r) return { id: w.id, names: names(w), lang: w.lang, date: w.info.date, venue: w.info.venue, days_left: days(w.info.date), sections: SECTIONS,
      open_sections: w.open_sections, steps: { info: "complete", quest: w.questionnaire.status, quest_submitted_at: w.questionnaire.submitted_at },
      events: w.events.filter((e: Any) => e.enabled).map((e: Any) => ({ key: e.key, name: e.name, date: e.date })), can_edit_info: w.rights.edit_info,
      organizer: { name: "Manon Jeanjean" } };
    if (r === "info" && method === "GET") return { info: { ...clone(w.info), budget: w.rights.budget ? w.info.budget : null }, can_edit: w.rights.edit_info, budget_visible: w.rights.budget };
    if (r === "info") {
      if (!w.rights.edit_info) throw new Error("La modification de la fiche n'est pas ouverte pour le moment");
      const guests = w.info.guests; const budget = w.info.budget;
      w.info = { ...body, guests, budget: w.rights.budget ? body.budget : budget };
      if (w.info.same_address) w.info.partners[1].address = w.info.partners[0].address;
      notify(`${names(w)} ont modifié leur fiche.`, w.id);
      return { info: w.info };
    }
    if (r === "questionnaire") return { status: w.questionnaire.status, submitted_at: w.questionnaire.submitted_at, embed_url: null,
      open_url: "https://docs.google.com/forms/d/1nG9CCTxUqPafON1n-8PmzNgN4j_cgfPMjysauNq0sLg/viewform", known_fields: ["budget", "guests", "ceremony.type", "ceremony.place", "ceremony.time", "jobs"] };
    if (r === "food") { if (!w.open_sections.includes("food")) throw new Error("Rubrique pas encore ouverte"); return foodView(w, seg[3], true); }
  }

  if (seg[0] !== "wedding-planner") throw new Error(`Démo : route non simulée ${path}`);
  const r = seg[1];
  if (r === "weddings" && seg.length === 2) {
    if (method === "POST") {
      const id = uid();
      W.push({ id, lang: body.lang, rights: { ...RIGHTS }, open_sections: ["home", "info", "quest"], notes: "", status: "active",
        info: { partners: [partner(body.partner1_first_name, "", body.partner1_email), partner(body.partner2_first_name, "", body.partner2_email)],
          same_address: false, date: body.date, venue: "", venue_address: "", budget: null, guests: { adults: null, kids: null }, ceremony: { ...emptyCer } },
        events: events(body.date, body.welcome_dinner, body.brunch), questionnaire: { status: "pending" }, discrepancies: [] });
      INVITES[id] = [body.send_invitations ? "pending" : "not_invited", body.partner2_email && body.send_invitations ? "pending" : "not_invited"];
      return out(get(id));
    }
    return W.filter((w) => w.status === "active").map(card).sort((a, b) => String(a.date ?? "9").localeCompare(String(b.date ?? "9")));
  }
  if (r === "weddings") {
    const w = get(seg[2]);
    const sub = seg[3];
    if (!sub) return out(w);
    if (sub === "info") { w.info = body; if (body.same_address) w.info.partners[1].address = w.info.partners[0].address; w.events.find((e: Any) => e.key === "dj").date = body.date; return out(w); }
    if (sub === "events") { w.events = body.events; w.info.date = body.events.find((e: Any) => e.key === "dj").date; return out(w); }
    if (sub === "rights") { w.rights = body; return body; }
    if (sub === "lang") { w.lang = body.lang; return body; }
    if (sub === "open-sections") { w.open_sections = SECTIONS.filter((s) => ["home", "info", "quest", ...body.open_sections].includes(s)); return { open_sections: w.open_sections }; }
    if (sub === "notes") { w.notes = body.notes; return body; }
    if (sub === "account") return { lang: w.lang, rights: w.rights, open_sections: w.open_sections, available_sections: ["food", "home", "info", "quest"],
      partners: w.info.partners.map((p: Any, i: number) => ({ index: i, first_name: p.first_name, email: p.email, status: INVITES[w.id]?.[i] ?? "not_invited", sent_count: 1 })) };
    if (sub === "invite") { INVITES[w.id][Number(seg[4])] = "pending"; return { status: "pending" }; }
    if (sub === "questionnaire") return questionnaire(w);
    if (sub === "discrepancies") {
      const d = w.discrepancies.find((x: Any) => x.id === decodeURIComponent(seg[4]));
      if (body.keep === "form") setPath(w.info, d.field, d.form_value);
      d.status = `kept_${body.keep}`;
      return out(w);
    }
    if (sub === "recap.pdf" || seg[5] === "pdf") return null;
    if (sub === "recap") {
      const rec = RECAPS[w.id] ?? { rubrics: [], generated_at: null };
      if (seg[4] === "generate") {
        const fresh = plainRecap(w.id).map((x) => ({ ...x, text: AI[x.key] && ANSWERS[w.id] ? AI[x.key] : x.text, generated: AI[x.key] && ANSWERS[w.id] ? AI[x.key] : x.text, source: "ai" }));
        const prev = Object.fromEntries(rec.rubrics.map((x: Any) => [x.key, x]));
        RECAPS[w.id] = { generated_at: new Date().toISOString(), rubrics: fresh.map((x) => prev[x.key]?.edited ? { ...prev[x.key], proposal: prev[x.key].generated === x.generated ? null : x.generated } : x) };
        return RECAPS[w.id];
      }
      if (seg[4] && seg[5] === "proposal") {
        const accept = new URLSearchParams(qs).get("accept") === "true";
        rec.rubrics = rec.rubrics.map((x: Any) => x.key === seg[4] && x.proposal ? (accept ? { ...x, text: x.proposal, generated: x.proposal, edited: false, proposal: null } : { ...x, generated: x.proposal, proposal: null }) : x);
        return rec;
      }
      if (seg[4] && method === "PATCH") { rec.rubrics = rec.rubrics.map((x: Any) => x.key === seg[4] ? { ...x, text: body.text, edited: body.text !== x.generated } : x); return rec; }
      return rec;
    }
    if (sub === "food") {
      const key = seg[4];
      if (method === "PUT") { if (body.vendor) FOOD[`${w.id}:${key}`] = body; else delete FOOD[`${w.id}:${key}`]; }
      return foodView(w, key);
    }
  }
  if (r === "notifications") {
    if (seg[2] === "read-all") { NOTIFS.forEach((n) => (n.read = true)); return { ok: true }; }
    return { unread: NOTIFS.filter((n) => !n.read).length, items: NOTIFS };
  }
  if (r === "settings") { if (method === "PUT") Object.assign(SETTINGS, body); return SETTINGS; }
  if (r === "questionnaire") { SETTINGS.last_sync = new Date().toISOString(); return { status: "ok", responses_created: 0, new_questions: 0 }; }
  if (r === "questions") {
    if (method === "PATCH") { const q = QUESTIONS.find((x) => x.id === seg[2])!; Object.assign(q, body); if (body.rubric && q.status === "to_classify") q.status = "active"; return q; }
    return { questions: [...QUESTIONS].sort((a, b) => a.order - b.order), rubrics: SETTINGS.rubrics,
      fiche_fields: { jobs: "Profession des partenaires", budget: "Budget global", guests: "Nombre d'invités et d'enfants", "ceremony.type": "Type de cérémonie",
        "ceremony.confession": "Confession", "ceremony.time": "Horaire de la cérémonie", "ceremony.place": "Lieu de la cérémonie" },
      modules: { food: "Repas et boissons", vendors: "Prestataires (catégories à ouvrir)" } };
  }
  if (r === "responses") {
    if (seg[1] === "responses" && seg[2] === "unassigned") return UNASSIGNED;
    UNASSIGNED.splice(UNASSIGNED.findIndex((x) => x.id === seg[2]), 1);
    return { ok: true };
  }
  throw new Error(`Démo : route non simulée ${path}`);
}
