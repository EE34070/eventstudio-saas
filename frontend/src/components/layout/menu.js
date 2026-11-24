import { LayoutGrid, Calendar, ClipboardList, Package, Truck, Users, MapPin, Receipt, Wallet, UserCog, TrendingUp, Navigation, Mail, Inbox, Zap, Music, ListTodo, Warehouse, FileText, FileInput, Repeat, LineChart, HeartHandshake, IdCard } from "lucide-react";
import { Heart, Megaphone, Settings, Hammer } from "lucide-react";

export const PARAMS = { key: "parametres", to: "/parametres", label: "Paramètres", icon: Settings, perm: "users:manage|org:write" };

export const DASH = { key: "dashboard", to: "/dashboard", label: "Tableau de bord", icon: LayoutGrid };

export const TOP = [
  { key: "crm", to: "/crm", label: "CRM", icon: TrendingUp, perm: "crm:manage", badge: "crm" },
  { key: "messagerie", to: "/messagerie", label: "Messagerie", icon: Mail, perm: "messages:read", badge: "messages" },
  { key: "demandes", to: "/demandes", label: "Demandes", icon: Inbox, perm: "events:read" },
  { key: "saisie", to: "/demande/nouvelle", label: "Saisie rapide", icon: Zap, perm: "events:write" },
  { key: "musique", to: "/musique-plans", label: "Ma musique", icon: Music, perm: "events:read", module: "dj" },
];

export const SECTIONS = [
  { key: "operation", cat: "Opération", items: [
    { key: "evenements", to: "/evenements", label: "Événements", icon: Calendar, perm: "events:read" },
    { key: "mariages", to: "/mariages", label: "Mariages", icon: Heart, perm: "events:read", module: "wedding_planner" },
    { key: "planning", to: "/planning", label: "Planning", icon: ClipboardList, perm: "events:read" },
    { key: "chargement", to: "/chargement", label: "Chargement du jour", icon: Truck, perm: "events:read", badge: "loadings" },
    { key: "livraison", to: "/livraison", label: "Livraison du jour", icon: Navigation, perm: "events:read", badge: "deliveries" },
    { key: "logistique", to: "/logistique", label: "Logistique", icon: Truck, perm: "events:read" },
    { key: "travaux", to: "/travaux", label: "Travaux internes", icon: Hammer, perm: "events:read" },
    { key: "todo", to: "/todo", label: "To do list", icon: ListTodo, perm: "events:read", badge: "tasks_overdue", red: true },
  ] },
  { key: "parc", cat: "Parc matériel", items: [
    { key: "catalogue", to: "/catalogue", label: "Catalogue produits", icon: Package, perm: "catalog:read" },
    { key: "dj", to: "/dj", label: "DJ partenaires", icon: Music, perm: "providers:manage" },
    { key: "entrepots", to: "/entrepots", label: "Entrepôts & stocks", icon: Warehouse, perm: "catalog:read" },
    { key: "vehicules", to: "/vehicules", label: "Véhicules", icon: Truck, perm: "events:read" },
  ] },
  { key: "admin", cat: "Administratif", items: [
    { key: "devis", to: "/devis-factures?tab=devis", label: "Devis", icon: FileText, perm: "finance:read" },
    { key: "factures", to: "/devis-factures?tab=factures", label: "Factures", icon: Receipt, perm: "finance:read" },
    { key: "contacts", to: "/contacts", label: "Contacts", icon: Users, perm: "contacts:read" },
    { key: "lieux", to: "/lieux", label: "Lieux", icon: MapPin, perm: "venues:read" },
    { key: "equipe", to: "/equipe", label: "Équipe", icon: UserCog, perm: "team:read" },
    { key: "mon-espace", to: "/mon-espace", label: "Mon espace salarié", icon: IdCard, perm: "events:read" },
    { key: "notes-de-frais", to: "/notes-de-frais", label: "Notes de frais", icon: Wallet, perm: "events:read" },
    { key: "factures-achat", to: "/factures-achat", label: "Factures d'achat", icon: FileInput, perm: "finance:read" },
    { key: "a-acheter", to: "/a-acheter", label: "À acheter", icon: FileInput, perm: "finance:read" },
    { key: "abonnements", to: "/abonnements", label: "Abonnements", icon: Repeat, perm: "finance:read" },
  ] },
  { key: "communication", cat: "Communication", items: [
    { key: "communication", to: "/communication", label: "Communication", icon: Megaphone, perm: "comms:view" },
  ] },
  { key: "finance", cat: "Finance", items: [
    { key: "finance", to: "/finance", label: "Finance & pilotage", icon: LineChart, perm: "pilot:view" },
  ] },
  { key: "social", cat: "Social", items: [
    { key: "social", to: "/social", label: "Pôle Social", icon: HeartHandshake, perm: "social:view", badge: "social", red: true },
  ] },
];

export const ALL_ITEMS = [...TOP, ...SECTIONS.flatMap((s) => s.items)];

export const GRID = { travaux: "works", communication: "communication", finance: "finance", social: "social", crm: "crm", messagerie: "messages", demandes: "inbound", saisie: "inbound", musique: "music", evenements: "events", mariages: "events", planning: "events", chargement: "logistics", livraison: "logistics", logistique: "logistics", todo: "tasks", catalogue: "catalog", entrepots: "stock", vehicules: "vehicles", devis: "quotes", factures: "invoices", contacts: "contacts", lieux: "venues", equipe: "team", "notes-de-frais": "expenses", "factures-achat": "purchases", "a-acheter": "purchases", abonnements: "purchases" };
