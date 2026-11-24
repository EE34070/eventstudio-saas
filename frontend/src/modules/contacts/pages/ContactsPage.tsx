import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/core/api/client";
import { useSession } from "@/core/session/SessionProvider";

type Contact = { id: string; display_name: string; email?: string; roles: string[]; language: string };

/** Page de référence : liste + création, droits d'écriture issus de /api/me. */
export default function ContactsPage() {
  const { canWrite } = useSession();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const { data = [], isLoading } = useQuery({ queryKey: ["contacts"], queryFn: () => api<Contact[]>("/contacts") });

  const create = useMutation({
    mutationFn: (display_name: string) => api<Contact>("/contacts", { method: "POST", body: JSON.stringify({ display_name }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["contacts"] }),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) create.mutate(name.trim(), { onSuccess: () => setName("") });
  };

  return (
    <section className="page">
      <h1>Contacts</h1>
      {canWrite("contacts") && (
        <form onSubmit={submit} className="inline-form">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Nom du contact ou de la structure" />
          <button disabled={create.isPending}>Ajouter</button>
        </form>
      )}
      {isLoading ? <p>Chargement…</p> : (
        <table>
          <thead><tr><th>Nom</th><th>E-mail</th><th>Rôles</th><th>Langue</th></tr></thead>
          <tbody>
            {data.map((c) => (
              <tr key={c.id}><td>{c.display_name}</td><td>{c.email ?? "—"}</td><td>{c.roles.join(", ")}</td><td>{c.language}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
