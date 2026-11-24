import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSession } from "@/core/session/SessionProvider";
import { brandingVars, loadBrandFonts } from "@/core/layout/theme";
import { fmtDate, portal, useWpMutation, type Info, type PortalHome } from "../api";
import { InfoForm } from "../components/InfoForm";
import { Loading, Toaster, toast } from "../ui";
import { C, FD, MENU } from "./i18n";
import "../wp.css";

type L = "en" | "fr";
const ml = (k: string, l: L) => (l === "en" ? MENU[k][0] : MENU[k][1]);

function Home({ h, go }: { h: PortalHome; go: (t: string) => void }) {
  const c = C[h.lang];
  const card = (tab: string, kicker: string, title: string, desc: string, done: boolean, doneLabel: string, todoLabel: string) => (
    <button className="card click" onClick={() => go(tab)}>
      <div className="kicker">{kicker}</div><h3>{title}</h3><div>{desc}</div>
      <span className={`pill${done ? " ok" : ""}`} style={{ alignSelf: "flex-start" }}>{done ? doneLabel : todoLabel}</span>
    </button>
  );
  return (
    <div>
      <div className="hero">
        <div className="kicker">{c.welcome}</div>
        <h1>{h.names}</h1>
        <p style={{ margin: "8px 0 18px" }}>{h.date ? fmtDate(h.date, h.lang) : c.dateTbc}{h.venue ? `, ${h.venue}` : ""}</p>
        {h.days_left != null && <><div className="big">{h.days_left}</div><div className="kicker">{c.togo}</div></>}
      </div>
      <div className="grid">
        {card("info", c.s1, c.i, c.id, h.steps.info === "complete", c.complete, c.todo)}
        {card("quest", c.s2, c.q, c.qd, h.steps.quest === "submitted", c.qdone, c.qtodo)}
      </div>
      <h2 style={{ margin: "34px 0 4px" }}>{c.next}</h2>
      <p>{c.nextd}</p>
      <div className="grid">
        {h.sections.filter((s) => !["home", "info", "quest"].includes(s)).map((s) => {
          const open = h.open_sections.includes(s);
          return open
            ? <button key={s} className="card click" onClick={() => go(s)}><h3>{ml(s, h.lang)}</h3></button>
            : <div key={s} className="card lock"><h3>{ml(s, h.lang)}</h3><span className="pill" style={{ alignSelf: "flex-start" }}>{c.soon}</span></div>;
        })}
      </div>
    </div>
  );
}

function OurInfo({ lang }: { lang: L }) {
  const c = C[lang];
  const { data } = useQuery({ queryKey: ["wp", "portal", "info"], queryFn: portal.info });
  const save = useWpMutation((i: Info) => portal.saveInfo(i), () => toast(c.saved));
  if (!data) return <Loading />;
  return (
    <div>
      <div className="kicker">{c.s1}</div><h1>{c.it}</h1><p>{c.ip}</p>
      <InfoForm info={data.info} lang={lang} canEdit={data.can_edit} budgetVisible={data.budget_visible} saving={save.isPending}
                onSave={(i) => save.mutate(i, { onError: (e) => toast(e.message) })} />
    </div>
  );
}

function OurQuestionnaire({ lang }: { lang: L }) {
  const c = C[lang];
  const { data } = useQuery({ queryKey: ["wp", "portal", "quest"], queryFn: portal.questionnaire });
  if (!data) return <Loading />;
  return (
    <div>
      <div className="kicker">{c.s2}</div><h1>{c.qt}</h1><p>{c.qp}</p>
      <div className="row" style={{ margin: "10px 0" }}>
        {data.status === "submitted" && <span className="pill ok">{c.qdone}{data.submitted_at ? ` · ${new Date(data.submitted_at).toLocaleDateString(lang === "en" ? "en-GB" : "fr-FR", { day: "numeric", month: "long" })}` : ""}</span>}
        {data.open_url && <a className="btn ghost" href={data.open_url} target="_blank" rel="noreferrer">{c.edit}</a>}
      </div>
      {data.known_fields.length > 0 && <div className="note">{c.known} {data.known_fields.map((k) => c.knownLabels[k] ?? k).join(", ")}.</div>}
      {data.embed_url
        ? <iframe className="formframe" src={data.embed_url} title={c.qh} />
        : <div className="empty"><h3>{c.qh}</h3><p>{c.qnone}</p></div>}
      <div className="note">{c.qn}</div>
    </div>
  );
}

function Food({ h }: { h: PortalHome }) {
  const f = FD[h.lang];
  const [key, setKey] = useState(h.events.find((e) => e.key === "dj")?.key ?? h.events[0]?.key);
  const { data } = useQuery({ queryKey: ["wp", "portal", "food", key], queryFn: () => portal.food(key!), enabled: !!key });
  const [ratios, setRatios] = useState<Record<string, number>>({});
  return (
    <div>
      <h1>{f.t}</h1><p>{f.p}</p>
      <div className="row" style={{ margin: "14px 0" }}>
        {h.events.map((e) => <button key={e.key} className={`btn${key === e.key ? "" : " ghost"}`} onClick={() => setKey(e.key)}>{e.key === "dj" && h.lang === "en" ? "Wedding day" : e.name}</button>)}
      </div>
      {!data ? <Loading /> : data.enabled === false ? <div className="note">{f.off}</div> : (
        <>
          <div className="kicker">{data.event.name} · {data.guests ?? "?"} {f.guests}</div>
          {!data.food ? (
            <div className="empty"><h3>{f.pick}</h3><p>{f.pickd}</p></div>
          ) : (
            <>
              <div className="sec"><div className="kicker">{f.vendor}</div><h3>{data.food.vendor}</h3>
                <div className="row"><span className="pill ok">{f.valid}</span>
                  {data.food.formula && <span className="pill">{f.formula} : {data.food.formula}</span>}
                  {data.food.price && <span className="pill">{f.price} : {data.food.price}</span>}</div></div>
              <div className="sec"><h3>{f.menu}</h3>{data.food.courses.map((c, i) => (
                <div key={i} className="qa"><div className="q">{c.name}</div><div><span className="strong">{f.chosen} : </span>{c.chosen}</div>
                  {c.options.length > 0 && <div className="row" style={{ marginTop: 6 }}><span className="kicker">{f.options} :</span>{c.options.map((o) => <span key={o} className="pill">{o}</span>)}</div>}</div>
              ))}</div>
              {data.food.included.length > 0 && <div className="sec"><h3>{f.inc}</h3>{data.food.included.map((d, i) => <div key={i} className="qa"><div>{d.name}</div><div className="q">{d.detail}</div></div>)}</div>}
              {data.food.external.length > 0 && (
                <div className="sec"><h3>{f.ext}</h3><div className="tablewrap"><table>
                  <thead><tr><th>{f.item}</th><th>{f.sup}</th><th>{f.ratio}</th><th>{f.qty}</th></tr></thead>
                  <tbody>{data.food.external.map((d, i) => {
                    const k = `${key}${i}`, r = ratios[k] ?? d.per_guest;
                    return <tr key={k}><td>{d.name}</td><td>{d.supplier}</td>
                      <td><input type="number" step="0.1" min="0" value={r} style={{ width: 80 }} aria-label={`${f.ratio} ${d.name}`}
                                 onChange={(e) => setRatios({ ...ratios, [k]: parseFloat(e.target.value) || 0 })} /></td>
                      <td className="num">{data.guests == null ? "?" : `${Math.ceil(data.guests * r)} ${f.unit[d.unit]}`}</td></tr>;
                  })}</tbody></table></div></div>
              )}
            </>
          )}
          <div className="sec"><h3>{f.diet}</h3><div className="kicker">{f.from}</div>
            {data.diets.length ? data.diets.map((d, i) => <div key={i} className="qa"><div className="row"><span className={`pill${d.allergy ? " warn" : ""}`}>{d.allergy ? `${f.allergy} : ${d.label}` : d.label}</span><span>{d.names}</span></div></div>)
              : <p className="muted">{f.none}</p>}</div>
        </>
      )}
    </div>
  );
}

/** Espace privé des mariés : menu complet visible, rubriques à venir grisées. */
export default function CoupleApp() {
  const { session } = useSession();
  const [tab, setTab] = useState("home");
  const { data: h, error } = useQuery({ queryKey: ["wp", "portal", "home"], queryFn: portal.home });
  loadBrandFonts(session.branding);
  const name = session.branding.app_name ?? session.org.name;
  return (
    <div className="wp wp-couple" style={brandingVars(session.branding)}>
      <header>
        <div className="mark">{session.branding.logo_url ? <img src={session.branding.logo_url} alt={name} style={{ maxHeight: 34 }} /> : name}</div>
        <div className="sub">{h?.names ?? ""}</div>
        {h && (
          <nav role="tablist">
            {h.sections.map((s) => {
              const open = h.open_sections.includes(s);
              return <button key={s} role="tab" aria-selected={tab === s} disabled={!open} onClick={() => setTab(s)}
                             title={open ? undefined : C[h.lang].soon}>{ml(s, h.lang)}</button>;
            })}
          </nav>
        )}
      </header>
      <main>
        {error && <p>{C.fr.missing}</p>}
        {!h && !error && <Loading />}
        {h && tab === "home" && <Home h={h} go={setTab} />}
        {h && tab === "info" && <OurInfo lang={h.lang} />}
        {h && tab === "quest" && <OurQuestionnaire lang={h.lang} />}
        {h && tab === "food" && <Food h={h} />}
      </main>
      <Toaster />
    </div>
  );
}
