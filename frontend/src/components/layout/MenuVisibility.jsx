import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, errMsg } from "@/lib/api";
import { useMe } from "@/context/MeContext";
import { ALL_ITEMS } from "@/components/layout/menu";

export function MenuVisibility() {
  const { me } = useMe();
  const [hidden, setHidden] = useState(null);
  useEffect(() => { api.get("/menu").then((r) => setHidden(r.data.hidden_all || {})); }, []);
  if (!hidden) return null;
  const roles = me.roles.filter((r) => r.id !== "admin");
  const toggle = (role, key) => {
    const cur = hidden[role] || [];
    const next = { ...hidden, [role]: cur.includes(key) ? cur.filter((k) => k !== key) : [...cur, key] };
    setHidden(next);
    api.put("/org/menu-visibility", { hidden: next }).catch((e) => toast.error(errMsg(e)));
  };
  return (
    <div className="card-soft overflow-x-auto p-5" data-testid="menu-visibility">
      <p className="mb-4 text-sm text-muted-foreground">Décochez une page pour la retirer du menu d'un rôle. L'admin voit toujours tout ; les droits d'accès aux données restent ceux du rôle.</p>
      <table className="w-full min-w-[720px] text-sm">
        <thead><tr><th className="py-2 text-left text-xs font-semibold text-muted-foreground">Page</th>{roles.map((r) => <th key={r.id} className="px-2 py-2 text-xs font-semibold text-muted-foreground">{r.label}</th>)}</tr></thead>
        <tbody>{ALL_ITEMS.map((i) => (
          <tr key={i.key} className="border-t border-border"><td className="py-2">{i.label}</td>
            {roles.map((r) => <td key={r.id} className="px-2 text-center"><input type="checkbox" className="h-4 w-4" checked={!(hidden[r.id] || []).includes(i.key)} onChange={() => toggle(r.id, i.key)} aria-label={`${i.label} — ${r.label}`} data-testid={`menu-vis-${r.id}-${i.key}`} /></td>)}
          </tr>))}</tbody>
      </table>
    </div>
  );
}
