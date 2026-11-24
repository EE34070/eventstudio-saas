export const STATUSES = [
  { id: "demande", label: "Demande" },
  { id: "devis_envoye", label: "Devis envoyé" },
  { id: "confirme", label: "Confirmé" },
  { id: "en_preparation", label: "En préparation" },
  { id: "realise", label: "Réalisé" },
  { id: "facture", label: "Facturé" },
  { id: "cloture", label: "Clôturé" },
];
export const statusLabel = (s) => STATUSES.find((x) => x.id === s)?.label || s;

const t = (key, label, type = "text") => ({ key, label, type });
export const MODULES = [
  { id: "dj", label: "DJ / Animateur", short: "DJ", fields: [t("style", "Style musical"), t("playlist_wanted", "Playlist souhaitée", "textarea"), t("playlist_banned", "Playlist interdite", "textarea"), t("rundown", "Déroulé de soirée (cérémonie, cocktail, entrée des mariés, ouverture de bal)", "textarea"), t("hours", "Horaires"), t("options", "Options (sax, MC…)")] },
  { id: "son_lumiere", label: "Son & Lumière", short: "Son & Lumière", fields: [t("tech_sheet", "Fiche technique", "textarea"), t("power", "Puissance électrique requise"), t("sockets", "Prises nécessaires"), t("layout_plan", "Plan d'implantation (lien)"), t("light_plan", "Plan de feu (lien)"), t("equipment_list", "Liste du matériel requis", "textarea")] },
  { id: "photobooth", label: "Photobooth", short: "Photobooth", fields: [t("booth_type", "Type de borne"), t("template", "Template d'impression"), t("prints", "Nombre de tirages"), t("online_gallery", "Galerie en ligne (lien)"), t("accessories", "Accessoires", "textarea")] },
  { id: "photographe", label: "Photographe", short: "Photo", fields: [t("shot_list", "Shot list", "textarea"), t("key_moments", "Moments clés", "textarea"), t("delivery_delay", "Délai de livraison"), t("gallery_link", "Lien de galerie"), t("photos_count", "Nombre de photos livrées")] },
  { id: "wedding_planner", label: "Wedding planner", short: "Wedding planner", fields: [t("milestones", "Rétroplanning & jalons", "textarea"), t("budget_planned", "Budget prévisionnel par poste", "textarea"), t("budget_actual", "Budget réel par poste", "textarea"), t("vendors", "Prestataires sélectionnés & suivi", "textarea"), t("checklist", "Check-list mariés", "textarea")] },
  { id: "agence", label: "Agence événementielle", short: "Agence", fields: [t("vendors", "Prestataires mobilisés", "textarea"), t("client_budget", "Budget client"), t("subcontracting", "Sous-traitance", "textarea"), t("margin_target", "Marge visée")] },
  { id: "loueur_materiel", label: "Loueur de matériel", short: "Location", fields: [t("notes", "Consignes de location", "textarea")] },
];
export const moduleLabel = (m) => MODULES.find((x) => x.id === m)?.short || m;

export const EVENT_TYPES = ["Mariage", "Soirée d'entreprise", "Séminaire", "Gala", "Anniversaire", "Soirée privée", "Festival", "Autre"];
export const CATEGORIES = ["Sonorisation", "Éclairage", "Structure", "Vidéo & Bornes", "DJ", "Énergie", "Mobilier"];
export const ITEM_STATES = ["OK", "Abîmé", "Manquant", "À nettoyer"];
export const DEPOSIT_STATUSES = [
  { id: "non_demandee", label: "Non demandée" },
  { id: "encaissee", label: "Encaissée" },
  { id: "restituee", label: "Restituée" },
  { id: "retenue", label: "Retenue (partielle/totale)" },
];

const eur0 = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const eur2 = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });
export const fmtEur = (n) => (n == null ? "—" : eur0.format(n));
export const fmtEur2 = (n) => (n == null ? "—" : eur2.format(n));
export const fmtDate = (s, opts) => (s ? new Date(s.length === 10 ? s + "T00:00" : s).toLocaleDateString("fr-FR", opts || { day: "2-digit", month: "short", year: "numeric" }) : "—");
export const fmtDT = (s) => (s ? `${fmtDate(s, { weekday: "short", day: "numeric", month: "short" })} · ${s.slice(11, 16)}` : "—");
export const pad = (n) => String(n).padStart(2, "0");
export const dayKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const toLocalInput = (d) => `${dayKey(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
export const daysBetween = (a, b) => Math.round((new Date(b + "T00:00") - new Date(a + "T00:00")) / 86400000);
