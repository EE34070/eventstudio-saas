import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";
import { Loading } from "@/components/common";
import { PublicRows } from "@/components/billing/QuoteEditor";
import { PublicPages, SignBox } from "@/components/billing/QuoteDocs";

const BASE = process.env.REACT_APP_BACKEND_URL;
const T = {
  fr: { quote: "Devis", of: "du", valid: "valable jusqu'au", ht: "HT", vat: "TVA", totalHt: "Total HT", totalTtc: "Total TTC", deposit: "Acompte", products: "Fiches produits", pdf: "Télécharger le PDF", notFound: "Ce devis est introuvable ou le lien n'est plus valide." },
  en: { quote: "Quote", of: "dated", valid: "valid until", ht: "excl. VAT", vat: "VAT", totalHt: "Total excl. VAT", totalTtc: "Total incl. VAT", deposit: "Deposit", products: "Product sheets", pdf: "Download the PDF", notFound: "This quote cannot be found or the link is no longer valid." },
};

export default function PublicQuote({ view = false }) {
  const { token } = useParams();
  const [q, setQ] = useState(null);
  const [err, setErr] = useState(false);
  const [lang, setLang] = useState(navigator.language?.startsWith("fr") ? "fr" : "en");
  useEffect(() => { axios.get(`${BASE}/api/public/${view ? "quote-views" : "quotes"}/${token}`).then((r) => { if (!view && !window.location.search.includes("apercu")) axios.post(`${BASE}/api/public/quotes/${token}/viewed`).catch(() => {}); setQ(r.data); setLang(r.data.language.startsWith("fr") ? "fr" : "en"); }).catch((e) => setErr(e.response?.status === 410 ? "expired" : true)); }, [token, view]);
  const t = T[lang];
  if (err) return <p className="p-10 text-center text-sm" data-testid="public-quote-error">{err === "expired" ? (lang === "fr" ? "Ce lien a expiré. Contactez Exclusivity Events pour en recevoir un nouveau." : "This link has expired. Please contact Exclusivity Events for a new one.") : t.notFound}</p>;
  if (!q) return <Loading />;
  const locale = lang === "fr" ? "fr-FR" : q.language.startsWith("en") ? q.language : "en-US";
  const eur = (n) => new Intl.NumberFormat(locale, { style: "currency", currency: "EUR" }).format(n);
  const date = (s) => (s ? new Date(`${s.slice(0, 10)}T00:00`).toLocaleDateString(locale, { day: "numeric", month: "long", year: "numeric" }) : "—");
  const n = (x) => new Intl.NumberFormat(locale).format(x);
  const pct = (x) => (lang === "fr" ? `${n(x)} %` : `${n(x)}%`);
  return (
    <div className="mx-auto max-w-3xl px-4 py-10 sm:py-16" data-testid="public-quote" lang={lang}>
      <div className="mb-6 flex justify-end gap-1" data-testid="public-quote-lang">
        {["fr", "en"].map((l) => <button key={l} onClick={() => setLang(l)} aria-pressed={lang === l} data-testid={`public-quote-lang-${l}`} className={`rounded-full px-3 py-1 text-xs font-semibold uppercase ${lang === l ? "bg-foreground text-background" : "text-muted-foreground"}`}>{l}</button>)}
      </div>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-2.5"><span className="brand-mark">{(q.org.name || "E")[0]}</span><span className="font-brand text-xl">{q.org.name}</span></div>
        <div className="text-right"><div className="text-2xl font-extrabold tracking-tight" data-testid="public-quote-title">{t.quote} {q.number}</div><div className="text-sm text-muted-foreground">{t.of} {date(q.date)} · {t.valid} {date(q.valid_until)}</div></div>
      </div>
      <div className="card-soft mt-8 p-6">
        <div className="text-lg font-semibold">{q.event_title}</div>
        <div className="text-sm text-muted-foreground">{date(q.event_date)} · {q.client_name}</div>
      </div>
      {q.view && <p className="mt-4 text-sm font-semibold" data-testid="public-view-kind">{q.view.label || { organizer: lang === "fr" ? "Version organisateur" : "Planner version", venue: lang === "fr" ? "Version lieu / technique" : "Venue / technical version", provider: lang === "fr" ? "Version prestataire" : "Supplier version" }[q.view.kind]}</p>}
      <PublicPages pages={q.pages?.header} brand={q.brand} />
      {q.rows && <PublicRows q={q} eur={eur} n={n} lang={lang} onToggle={(section_id, selected) => axios.post(`${BASE}/api/public/quotes/${token}/options`, { section_id, selected }).then((r) => setQ(r.data)).catch(() => {})} />}
      <div className={`card-soft mt-4 divide-y divide-border px-6 ${q.rows ? "hidden" : ""}`} data-testid="public-quote-lines">
        {q.lines.map((l, i) => (
          <div key={i} className="flex gap-4 py-4">
            <div className="min-w-0 flex-1"><div className="font-semibold">{l.label}</div>{l.description && <div className="text-sm text-muted-foreground">{l.description}</div>}
              <div className="text-[13px] text-[#737373]">{n(l.qty)} × {eur(l.unit_price)} {t.ht} · {t.vat} {pct(l.vat)}</div></div>
            <div className="font-semibold">{eur(l.qty * l.unit_price)}</div>
          </div>
        ))}
      </div>
      {q.spaces?.length > 0 && <div className="card-soft mt-4 divide-y divide-border px-6 text-sm" data-testid="public-spaces">{q.spaces.map((s) => <div key={s.name} className="py-3"><b>{s.name}</b>{s.power && <div>{lang === "fr" ? "Électricité" : "Electricity"} : {s.power}</div>}{s.notes && <div className="text-muted-foreground">{s.notes}</div>}</div>)}</div>}
      {!q.no_prices && <div className="ml-auto mt-6 w-full max-w-xs text-sm" data-testid="public-quote-totals">
        <div className="flex justify-between py-1 text-muted-foreground"><span>{t.totalHt}</span><span>{eur(q.total_ht)}</span></div>
        {q.vat_breakdown.map((b) => <div key={b.rate} className="flex justify-between py-1 text-muted-foreground"><span>{t.vat} {pct(b.rate)}</span><span>{eur(b.vat)}</span></div>)}
        <div className="flex justify-between border-t border-border py-2 text-base font-bold"><span>{t.totalTtc}</span><span data-testid="public-quote-ttc">{eur(q.total_ttc)}</span></div>
        {q.deposit_percent > 0 && <div className="flex justify-between py-1"><span>{t.deposit} ({pct(q.deposit_percent)})</span><span>{eur((q.total_ttc * q.deposit_percent) / 100)}</span></div>}
      </div>}
      <PublicPages pages={q.pages?.closing} brand={q.brand} />
      {!view && <SignBox q={q} token={token} setQ={setQ} lang={lang} />}
      {q.products.length > 0 && (
        <div className="mt-12" data-testid="public-quote-products">
          <h2 className="text-lg font-semibold">{t.products}</h2>
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            {q.products.map((p) => (
              <div key={p.equipment_id} className="card-soft overflow-hidden" data-testid={`public-product-${p.ref}`}>
                {p.photo && <img src={p.photo.startsWith("/") ? BASE + p.photo : p.photo} alt={p.name} className="h-48 w-full object-cover" />}
                <div className="p-5"><div className="font-semibold">{p.name}</div><div className="text-[13px] text-[#737373]">{p.ref}</div><p className="mt-2 whitespace-pre-line text-sm text-muted-foreground">{p.description}</p></div>
              </div>
            ))}
          </div>
        </div>
      )}
      {!view && q.documents?.length > 0 && <div className="mt-8" data-testid="public-quote-documents"><h2 className="text-lg font-semibold">{lang === "fr" ? "Fiches techniques et notices" : "Data sheets and manuals"}</h2>
        <ul className="mt-2 space-y-1 text-sm">{q.documents.map((d) => <li key={d.id}><a className="underline" href={BASE + d.url} target="_blank" rel="noreferrer" data-testid={`public-quote-doc-${d.id}`}>{d.title} (PDF)</a></li>)}</ul></div>}
      <a href={`${BASE}/api/public/${view ? "quote-views" : "quotes"}/${token}/pdf`} className="mt-8 inline-flex h-10 items-center rounded-full border border-border px-5 text-sm font-semibold shadow-soft" data-testid="public-quote-pdf">{t.pdf}</a>
      {q.terms?.url && <p className="mt-4 text-sm" data-testid="public-quote-terms"><a className="underline" href={BASE + q.terms.url} target="_blank" rel="noreferrer">{lang === "en" ? "General terms and conditions of sale (PDF)" : "Conditions générales de vente applicables (PDF)"}</a></p>}
      {q.terms?.text && <details className="mt-4 text-sm" data-testid="public-quote-terms"><summary className="cursor-pointer underline">{lang === "en" ? "General terms and conditions of sale" : "Conditions générales de vente applicables"}</summary><p className="mt-2 whitespace-pre-line text-xs text-muted-foreground">{q.terms.text}</p></details>}
      {q.notes && <p className="mt-8 whitespace-pre-line text-sm">{q.notes}</p>}
      <p className="mt-10 text-xs text-muted-foreground">{(lang === "en" && q.org.payment_terms_en) || q.org.payment_terms}<br />{[q.org.name, q.org.address, q.org.zip, q.org.city, q.org.phone, q.org.email].filter(Boolean).join(" · ")}</p>
    </div>
  );
}
