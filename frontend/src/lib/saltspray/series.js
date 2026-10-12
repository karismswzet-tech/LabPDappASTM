import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API } from "@/lib/api";

export const SALT_SERIES = `${API}/salt-spray/observation-series`;

async function getJSON(url) {
  const res = await fetch(url, { credentials: "include" });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
  return res.json();
}
async function send(url, method, body) {
  const res = await fetch(url, { method, credentials: "include", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `HTTP ${res.status}`);
  return res.json();
}

const refreshAll = (qc) => {
  qc.invalidateQueries({ queryKey: ["salt-obs"] });
  qc.invalidateQueries({ queryKey: ["salt-obs-header"] });
  qc.invalidateQueries({ queryKey: ["salt-series"] });
};

export const useSeriesList = () => useQuery({ queryKey: ["salt-series"], queryFn: () => getJSON(SALT_SERIES) });
export const useSeries = (id) => useQuery({ queryKey: ["salt-series", id], queryFn: () => getJSON(`${SALT_SERIES}/${id}`), enabled: !!id });

export function useCompleteSeries() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (body) => send(`${SALT_SERIES}/complete`, "POST", body), onSuccess: () => refreshAll(qc) });
}
export function useDeleteSeries() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id) => send(`${SALT_SERIES}/${id}`, "DELETE"), onSuccess: () => refreshAll(qc) });
}
export function useReopenSeries() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id) => send(`${SALT_SERIES}/${id}/reopen`, "POST"), onSuccess: () => refreshAll(qc) });
}

export const SAMPLE_COLORS = ["#F59E0B", "#22D3EE", "#A78BFA", "#34D399", "#F472B6", "#60A5FA", "#FB923C", "#A3E635"];

export function fmtStart(h) {
  if (!h?.start_date && !h?.start_time) return "-";
  const d = h.start_date ? new Date(`${h.start_date}T00:00:00`).toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" }) : "";
  return [d, h.start_time].filter(Boolean).join(" · ");
}
