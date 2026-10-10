import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API } from "@/lib/api";

export const SALT_OBS = `${API}/salt-spray/observations`;

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}

async function send(url, method, body) {
  const res = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.text()) || `Request failed: ${res.status}`);
  return res.json();
}

export const useObservations = () => useQuery({ queryKey: ["salt-obs"], queryFn: () => getJSON(SALT_OBS) });

const invalidate = (qc) => qc.invalidateQueries({ queryKey: ["salt-obs"] });

export function useCreateObservation() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (body) => send(SALT_OBS, "POST", body), onSuccess: () => invalidate(qc) });
}

export function useUpdateObservation() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: ({ id, body }) => send(`${SALT_OBS}/${id}`, "PUT", body), onSuccess: () => invalidate(qc) });
}

export function useDeleteObservation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id) => {
      const res = await fetch(`${SALT_OBS}/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error((await res.text()) || "Delete failed");
      return res.json();
    },
    onSuccess: () => invalidate(qc),
  });
}

export function obsGroupLabel(prefix, samples) {
  if (!samples || !samples.length) return "";
  return `${prefix || ""}{${samples.map((s) => `${s.code} (${s.type})`).join(",  ")}}`;
}
