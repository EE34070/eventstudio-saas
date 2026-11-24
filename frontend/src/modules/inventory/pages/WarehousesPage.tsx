import { useQuery } from "@tanstack/react-query";
import { api } from "@/core/api/client";

export default function WarehousesPage() {
  const { data = [] } = useQuery({
    queryKey: ["warehouses"],
    queryFn: () => api<{ id: string; name: string; kind: string }[]>("/inventory/warehouses"),
  });
  return (
    <section className="page">
      <h1>Entrepôts & dépôts</h1>
      <ul className="list">{data.map((w) => <li key={w.id}>{w.name} <small>({w.kind})</small></li>)}</ul>
    </section>
  );
}
