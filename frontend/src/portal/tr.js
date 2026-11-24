import L from "@/portal/locales.json";

export function makeT(lang) {
  const d = L[lang.startsWith("fr") ? "fr" : "en"];
  const t = (k, v = {}) => Object.entries(v).reduce((s, [a, b]) => s.replace(`{${a}}`, b), d[k] ?? k);
  const date = (s, o) => (s ? new Date(s.length === 10 ? `${s}T00:00` : s).toLocaleDateString(lang, o || { weekday: "long", day: "numeric", month: "long", year: "numeric" }) : "—");
  const money = (n) => new Intl.NumberFormat(lang, { style: "currency", currency: "EUR" }).format(n || 0);
  return { t, date, money, en: !lang.startsWith("fr") };
}
