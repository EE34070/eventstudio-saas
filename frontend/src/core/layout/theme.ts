import type { Branding } from "@/core/session/SessionProvider";

/** Traduit l'image de marque de l'organisation en variables CSS (--b-*) et charge ses polices. */
export function brandingVars(b: Branding): Record<string, string> {
  const v: Record<string, string> = {};
  const map: [keyof Branding, string][] = [
    ["primary_color", "--b-primary"], ["background", "--b-bg"], ["surface", "--b-surface"], ["ink", "--b-ink"],
    ["muted", "--b-muted"], ["line", "--b-line"], ["soft", "--b-soft"], ["alert", "--b-alert"],
  ];
  for (const [k, css] of map) if (b[k]) v[css] = String(b[k]);
  if (b.font_display) v["--b-display"] = `'${b.font_display}', Georgia, serif`;
  if (b.font_body) v["--b-body"] = `'${b.font_body}', system-ui, sans-serif`;
  return v;
}

const loaded = new Set<string>();

export function loadBrandFonts(b: Branding) {
  const families = [b.font_display, b.font_body].filter(Boolean) as string[];
  const key = families.join("|");
  if (!families.length || loaded.has(key)) return;
  loaded.add(key);
  const spec = families
    .map((f) => `family=${encodeURIComponent(f)}:ital,wght@0,300;0,400;0,500;1,400;1,500`)
    .join("&");
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = `https://fonts.googleapis.com/css2?${spec}&display=swap`;
  document.head.appendChild(link);
}
