import { useEffect, useState, type ReactNode } from "react";

/* Confirmations : petit message en bas de page, jamais de boîte d'alerte du navigateur. */
let push: ((m: string) => void) | null = null;
export const toast = (m: string) => push?.(m);

export function Toaster() {
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    let t: ReturnType<typeof setTimeout>;
    push = (m) => {
      setMsg(m);
      clearTimeout(t);
      t = setTimeout(() => setMsg(null), 2400);
    };
    return () => { push = null; clearTimeout(t); };
  }, []);
  return msg ? <div className="wp-toast" role="status">{msg}</div> : null;
}

export function Modal({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="wp-modal" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true">{children}</div>
    </div>
  );
}

type FieldProps = {
  label: string;
  value: string | number | null | undefined;
  onChange: (v: string) => void;
  type?: string;
  disabled?: boolean;
  placeholder?: string;
};

export function Field({ label, value, onChange, type = "text", disabled, placeholder }: FieldProps) {
  return (
    <div>
      <label className="l">
        {label}
        <input type={type} value={value ?? ""} disabled={disabled} placeholder={placeholder}
               onChange={(e) => onChange(e.target.value)} style={{ marginTop: 4, textTransform: "none", letterSpacing: 0 }} />
      </label>
    </div>
  );
}

export function Section({ title, children, kicker }: { title?: string; kicker?: string; children: ReactNode }) {
  return (
    <div className="sec">
      {kicker && <div className="kicker">{kicker}</div>}
      {title && <h3>{title}</h3>}
      {children}
    </div>
  );
}

export function Loading() {
  return <p className="muted">Chargement…</p>;
}

export const num = (v: string): number | null => (v.trim() === "" ? null : Number(v.replace(/\s/g, "").replace(",", ".")));
