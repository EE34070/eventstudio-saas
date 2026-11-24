import { useQuery } from "@tanstack/react-query";
import { api } from "@/core/api/client";

type EventItem = { id: string; title: string; status: string; starts_at: string };

export default function EventsPage() {
  const { data = [], isLoading } = useQuery({ queryKey: ["events"], queryFn: () => api<EventItem[]>("/events") });
  return (
    <section className="page">
      <h1>Événements</h1>
      {isLoading ? <p>Chargement…</p> : (
        <ul className="list">
          {data.map((e) => (
            <li key={e.id}>
              <strong>{e.title}</strong> — {new Date(e.starts_at).toLocaleDateString("fr-FR")} · {e.status}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
