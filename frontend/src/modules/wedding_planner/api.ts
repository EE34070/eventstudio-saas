import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/core/api/client";

export type Partner = { first_name: string; last_name: string; email: string | null; phone: string; job: string; address: string };
export type Info = {
  partners: Partner[];
  same_address: boolean;
  date: string | null;
  venue: string;
  venue_address: string;
  budget: number | null;
  guests: { adults: number | null; kids: number | null };
  ceremony: { type: "Laïque" | "Religieuse" | null; confession: string; place: string; time: string; officiant: string; language: string; people: number | null };
};
export type WEvent = {
  id: string; key: string; name: string; enabled: boolean; fixed: boolean; date: string | null; place: string;
  estimate: number | null; confirmed?: number | null; guests?: number | null; guests_source?: string; event_id?: string | null;
};
export type Rights = { budget: boolean; vendor_prices: boolean; dday_planning: boolean; documents: boolean; edit_info: boolean };
export type Discrepancy = { id: string; field: string; question: string; fiche_value: unknown; form_value: unknown; status: string };
export type Wedding = {
  id: string; names: string; info: Info; events: WEvent[]; lang: "fr" | "en"; rights: Rights; open_sections: string[];
  notes: string; status: string; days_left: number | null; progress: number;
  questionnaire: { status: string; submitted_at?: string | null }; discrepancies: Discrepancy[];
};
export type Card = {
  id: string; names: string; date: string | null; days_left: number | null; venue: string; guests: number | null;
  budget: number | null; progress: number; questionnaire: string; open_discrepancies: number;
  vendors: string | null; documents: string | null; next_payment: string | null; next_task: string | null;
};
export type QView = {
  status: string; submitted_at: string | null; connected: boolean; last_sync: string | null; discrepancies: Discrepancy[];
  sections: { title: string; answered: number; questions: { id: string; title: string; answer: string; deleted: boolean; to_classify: boolean;
    rubric: string | null; modified_in_fiche: boolean; files: { name: string; url: string }[] }[] }[];
};
export type RecapRubric = { key: string; title: string; text: string; generated: string; edited: boolean; proposal: string | null; source: string };
export type Recap = { rubrics: RecapRubric[]; generated_at: string | null };
export type Course = { name: string; chosen: string; options: string[] };
export type Food = {
  vendor: string; formula: string; price: string | null; notes?: string;
  courses: Course[]; included: { name: string; detail: string }[];
  external: { name: string; supplier: string; per_guest: number; unit: "bottle" | "keg" | "l"; quantity?: number | null }[];
};
export type FoodView = { event: WEvent; enabled?: boolean; guests: number | null; guests_source: string; food: Food | null;
  diets: { label: string; names: string; allergy: boolean }[]; kids: number | null };
export type Account = { partners: { index: number; first_name: string; email: string | null; status: string; sent_count: number }[];
  lang: "fr" | "en"; rights: Rights; open_sections: string[]; available_sections: string[] };
export type Notifs = { unread: number; items: { id: string; kind: string; text: string; wedding_id: string | null; read: boolean; at: string }[] };
export type Question = { id: string; number: number | null; order: number; section: string; title: string; kind: string; rubric: string | null;
  fiche_field: string | null; module: string | null; status: string; suggestion: string | null };
export type QuestionsView = { questions: Question[]; rubrics: { key: string; title: string }[]; fiche_fields: Record<string, string>; modules: Record<string, string> };
export type ModSettings = { form_id: string | null; form_url: string | null; notify_email: string | null; last_sync: string | null; sync_error: string | null;
  form_title?: string | null; notification_prefs: Record<string, { app: boolean; email: boolean }>; notification_types: Record<string, string>;
  rubrics: { key: string; title: string }[]; google_configured: boolean; service_account: string | null };

const B = "/wedding-planner";
const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export const wp = {
  weddings: () => api<Card[]>(`${B}/weddings`),
  wedding: (id: string) => api<Wedding>(`${B}/weddings/${id}`),
  create: (b: unknown) => api<Wedding>(`${B}/weddings`, json("POST", b)),
  info: (id: string, info: Info) => api<Wedding>(`${B}/weddings/${id}/info`, json("PUT", info)),
  events: (id: string, events: WEvent[]) => api<Wedding>(`${B}/weddings/${id}/events`, json("PUT", { events })),
  rights: (id: string, r: Rights) => api<Rights>(`${B}/weddings/${id}/rights`, json("PUT", r)),
  lang: (id: string, lang: string) => api(`${B}/weddings/${id}/lang`, json("PUT", { lang })),
  openSections: (id: string, open_sections: string[]) => api(`${B}/weddings/${id}/open-sections`, json("PUT", { open_sections })),
  notes: (id: string, notes: string) => api(`${B}/weddings/${id}/notes`, json("PUT", { notes })),
  account: (id: string) => api<Account>(`${B}/weddings/${id}/account`),
  invite: (id: string, i: number) => api(`${B}/weddings/${id}/invite/${i}`, json("POST")),
  questionnaire: (id: string) => api<QView>(`${B}/weddings/${id}/questionnaire`),
  resolve: (id: string, did: string, keep: "fiche" | "form") => api<Wedding>(`${B}/weddings/${id}/discrepancies/${encodeURIComponent(did)}/resolve`, json("POST", { keep })),
  recap: (id: string) => api<Recap>(`${B}/weddings/${id}/recap`),
  generate: (id: string) => api<Recap>(`${B}/weddings/${id}/recap/generate`, json("POST")),
  editRecap: (id: string, key: string, text: string) => api<Recap>(`${B}/weddings/${id}/recap/${key}`, json("PATCH", { text })),
  proposal: (id: string, key: string, accept: boolean) => api<Recap>(`${B}/weddings/${id}/recap/${key}/proposal?accept=${accept}`, json("POST")),
  food: (id: string, key: string) => api<FoodView>(`${B}/weddings/${id}/food/${key}`),
  saveFood: (id: string, key: string, f: Food) => api<FoodView>(`${B}/weddings/${id}/food/${key}`, json("PUT", f)),
  notifications: () => api<Notifs>(`${B}/notifications`),
  readAll: () => api(`${B}/notifications/read-all`, json("POST")),
  settings: () => api<ModSettings>(`${B}/settings`),
  saveSettings: (s: Partial<ModSettings>) => api<ModSettings>(`${B}/settings`, json("PUT", s)),
  sync: () => api<Record<string, unknown>>(`${B}/questionnaire/sync`, json("POST")),
  questions: () => api<QuestionsView>(`${B}/questions`),
  patchQuestion: (id: string, b: Partial<Question>) => api(`${B}/questions/${id}`, json("PATCH", b)),
  unassigned: () => api<{ id: string; email: string | null; submitted_at: string; answers: number }[]>(`${B}/responses/unassigned`),
  assign: (rid: string, wedding_id: string | null) => api(`${B}/responses/${rid}/assign`, json("PUT", { wedding_id })),
};

export type PortalHome = {
  id: string; names: string; lang: "fr" | "en"; date: string | null; venue: string; days_left: number | null;
  sections: string[]; open_sections: string[]; steps: { info: string; quest: string; quest_submitted_at: string | null };
  events: { key: string; name: string; date: string | null }[]; can_edit_info: boolean; organizer: { name: string; logo_url?: string };
};
export const portal = {
  home: () => api<PortalHome>("/portal/wedding"),
  info: () => api<{ info: Info; can_edit: boolean; budget_visible: boolean }>("/portal/wedding/info"),
  saveInfo: (info: Info) => api<{ info: Info }>("/portal/wedding/info", json("PUT", info)),
  questionnaire: () => api<{ status: string; submitted_at: string | null; embed_url: string | null; open_url: string | null; known_fields: string[] }>("/portal/wedding/questionnaire"),
  food: (key: string) => api<FoodView>(`/portal/wedding/food/${key}`),
};

export function useWedding(id: string) {
  return useQuery({ queryKey: ["wp", "wedding", id], queryFn: () => wp.wedding(id) });
}

/** Mutation qui rafraîchit tout le module (une seule saisie, visible partout). */
export function useWpMutation<A, R>(fn: (a: A) => Promise<R>, onDone?: (r: R) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["wp"] });
      onDone?.(r);
    },
  });
}

export const fmtDate = (d: string | null | undefined, lang: "fr" | "en" = "fr") =>
  d ? new Date(`${d}T12:00:00`).toLocaleDateString(lang === "en" ? "en-GB" : "fr-FR", { day: "numeric", month: "long", year: "numeric" }) : "";
export const money = (n: number | null | undefined) => (n == null ? "" : `${Number(n).toLocaleString("fr-FR")} $`);
