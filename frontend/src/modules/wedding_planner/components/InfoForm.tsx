import { useEffect, useState } from "react";
import type { Info } from "../api";
import { Field, num, Section } from "../ui";

const T = {
  fr: { p1: "Partenaire 1", p2: "Partenaire 2", fn: "Prénom", ln: "Nom", em: "E-mail", ph: "Téléphone", job: "Profession",
    addr: "Adresse postale du couple", same: "Même adresse que mon partenaire", w: "Le mariage", date: "Date du mariage",
    venue: "Lieu de réception", vaddr: "Adresse du lieu", budget: "Budget global", guests: "Invités (calculés depuis la Guest List)",
    adults: "adultes", kids: "enfants", total: "total", c: "Cérémonie", cer: "Type de cérémonie", choose: "À préciser",
    lay: "Laïque", rel: "Religieuse", other: "Quelle confession ?", place: "Lieu de la cérémonie", time: "Horaire prévu",
    off: "Officiant ou célébrant (nom et coordonnées)", lang: "Langue de la cérémonie", ppl: "Nombre de personnes présentes",
    save: "Enregistrer", auto: "Calculé automatiquement depuis la Guest List dès qu'elle sera ouverte. En attendant, valeurs reprises du questionnaire.",
    manual: "Saisie manuelle en attendant la Guest List", none: "À venir", readonly: "La modification de cette fiche n'est pas ouverte pour le moment." },
  en: { p1: "Partner 1", p2: "Partner 2", fn: "First name", ln: "Last name", em: "Email", ph: "Phone", job: "Profession",
    addr: "Postal address", same: "Same address as my partner", w: "Your wedding", date: "Wedding date",
    venue: "Reception venue", vaddr: "Venue address", budget: "Overall budget", guests: "Guests (from your guest list)",
    adults: "adults", kids: "children", total: "total", c: "Ceremony", cer: "Type of ceremony", choose: "To be confirmed",
    lay: "Secular", rel: "Religious", other: "Which faith or denomination?", place: "Ceremony location", time: "Time",
    off: "Officiant name and contact", lang: "Ceremony language", ppl: "Number of people at the ceremony",
    save: "Save", auto: "Calculated from your guest list once it opens. Until then, taken from your questionnaire.",
    manual: "", none: "Coming soon", readonly: "Editing is not open for the moment." },
};

type Props = {
  info: Info;
  lang: "fr" | "en";
  onSave: (info: Info) => void;
  canEdit?: boolean;
  budgetVisible?: boolean;
  admin?: boolean;
  saving?: boolean;
};

export function InfoForm({ info, lang, onSave, canEdit = true, budgetVisible = true, admin = false, saving }: Props) {
  const t = T[lang];
  const [f, setF] = useState<Info>(info);
  useEffect(() => setF(info), [info]);
  const ro = !canEdit;

  const setP = (i: number, k: keyof Info["partners"][number], v: string) =>
    setF((x) => {
      const partners = x.partners.map((p, j) => (j === i ? { ...p, [k]: v } : p));
      if (x.same_address && i === 0 && k === "address") partners[1] = { ...partners[1], address: v };
      return { ...x, partners };
    });
  const setC = (k: keyof Info["ceremony"], v: string | number | null) => setF((x) => ({ ...x, ceremony: { ...x.ceremony, [k]: v } }));
  const g = f.guests;
  const total = g.adults == null && g.kids == null ? null : (g.adults ?? 0) + (g.kids ?? 0);

  const partner = (i: number) => (
    <Section title={i === 0 ? t.p1 : t.p2}>
      <div className="two">
        <Field label={t.fn} value={f.partners[i].first_name} disabled={ro} onChange={(v) => setP(i, "first_name", v)} />
        <Field label={t.ln} value={f.partners[i].last_name} disabled={ro} onChange={(v) => setP(i, "last_name", v)} />
      </div>
      <div className="two">
        <Field label={t.em} type="email" value={f.partners[i].email} disabled={ro} onChange={(v) => setP(i, "email", v)} />
        <Field label={t.ph} type="tel" value={f.partners[i].phone} disabled={ro} onChange={(v) => setP(i, "phone", v)} />
      </div>
      <Field label={t.job} value={f.partners[i].job} disabled={ro} onChange={(v) => setP(i, "job", v)} />
      <Field label={t.addr} value={f.partners[i].address} disabled={ro || (i === 1 && f.same_address)} onChange={(v) => setP(i, "address", v)} />
      {i === 1 && (
        <label className="row" style={{ marginTop: 8, fontSize: 13 }}>
          <input type="checkbox" checked={f.same_address} disabled={ro}
                 onChange={(e) => setF((x) => ({ ...x, same_address: e.target.checked,
                   partners: e.target.checked ? [x.partners[0], { ...x.partners[1], address: x.partners[0].address }] : x.partners }))} />
          {t.same}
        </label>
      )}
    </Section>
  );

  return (
    <form onSubmit={(e) => { e.preventDefault(); onSave(f); }}>
      {ro && <div className="note">{t.readonly}</div>}
      {partner(0)}
      {partner(1)}
      <Section title={t.w}>
        <div className="two">
          <Field label={t.date} type="date" value={f.date} disabled={ro} onChange={(v) => setF({ ...f, date: v || null })} />
          {budgetVisible ? (
            <Field label={t.budget} value={f.budget} disabled={ro} onChange={(v) => setF({ ...f, budget: num(v) })} />
          ) : <div />}
        </div>
        <div className="two">
          <Field label={t.venue} value={f.venue} disabled={ro} onChange={(v) => setF({ ...f, venue: v })} />
          <Field label={t.vaddr} value={f.venue_address} disabled={ro} onChange={(v) => setF({ ...f, venue_address: v })} />
        </div>
        <label className="l">{t.guests}</label>
        {admin ? (
          <div className="two">
            <Field label={t.adults} value={g.adults} onChange={(v) => setF({ ...f, guests: { ...g, adults: num(v) } })} />
            <Field label={t.kids} value={g.kids} onChange={(v) => setF({ ...f, guests: { ...g, kids: num(v) } })} />
          </div>
        ) : (
          <div className="row">
            <span className="pill">{total ?? t.none} {total != null && t.total}</span>
            {g.adults != null && <span className="pill">{g.adults} {t.adults}</span>}
            {g.kids != null && <span className="pill">{g.kids} {t.kids}</span>}
          </div>
        )}
        <div className="note">{t.auto}{admin && t.manual ? ` ${t.manual}.` : ""}</div>
      </Section>
      <Section title={t.c}>
        <label className="l">{t.cer}
          <select value={f.ceremony.type ?? ""} disabled={ro} style={{ marginTop: 4, textTransform: "none", letterSpacing: 0 }}
                  onChange={(e) => setC("type", e.target.value || null)}>
            <option value="">{t.choose}</option>
            <option value="Laïque">{t.lay}</option>
            <option value="Religieuse">{t.rel}</option>
          </select>
        </label>
        {f.ceremony.type === "Religieuse" && (
          <Field label={t.other} value={f.ceremony.confession} disabled={ro} onChange={(v) => setC("confession", v)} />
        )}
        <div className="two">
          <Field label={t.place} value={f.ceremony.place} disabled={ro} onChange={(v) => setC("place", v)} />
          <Field label={t.time} type="time" value={f.ceremony.time} disabled={ro} onChange={(v) => setC("time", v)} />
        </div>
        <Field label={t.off} value={f.ceremony.officiant} disabled={ro} onChange={(v) => setC("officiant", v)} />
        <div className="two">
          <Field label={t.lang} value={f.ceremony.language} disabled={ro} onChange={(v) => setC("language", v)} />
          <Field label={t.ppl} value={f.ceremony.people} disabled={ro} onChange={(v) => setC("people", num(v))} />
        </div>
      </Section>
      {!ro && (
        <div className="row" style={{ marginTop: 18 }}>
          <button className="btn" type="submit" disabled={saving}>{t.save}</button>
        </div>
      )}
    </form>
  );
}
