import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API } from "@/lib/api";
import { fileUrl, imageToDataUri, uploadImage } from "@/lib/kht/api";

export { fileUrl, imageToDataUri, uploadImage };

export const HUMIDITY = `${API}/humidity`;

// Skala & label Grade A-E identik dengan Rust Preventing ASTM D1748.
export const HUM_GRADES = {
  A: { min: 0, max: 0, label: "Bersih tanpa karat", color: "#10B981", status: "EXCELLENT PASS" },
  B: { min: 1, max: 10, label: "Karat ringan", color: "#34D399", status: "GOOD / MINOR" },
  C: { min: 11, max: 25, label: "Karat sedang", color: "#FBBF24", status: "FAIR / MODERATE" },
  D: { min: 26, max: 50, label: "Karat luas", color: "#F97316", status: "POOR / EXTENSIVE" },
  E: { min: 51, max: 100, label: "Karat berat", color: "#EF4444", status: "REJECT / SEVERE" },
};

export function gradeForCount(count) {
  const n = Math.max(0, Math.min(100, Number(count) || 0));
  return Object.entries(HUM_GRADES).find(([, g]) => n >= g.min && n <= g.max)?.[0] || "E";
}

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function postJson(url, body) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.text()) || `Request failed: ${res.status}`);
  return res.json();
}

export const useHumidityDashboard = () => useQuery({ queryKey: ["humidity", "dashboard"], queryFn: () => getJSON(`${HUMIDITY}/dashboard`) });
export const useHumidityTests = (q) => useQuery({ queryKey: ["humidity", "tests", q ?? ""], queryFn: () => getJSON(`${HUMIDITY}/tests${q ? `?q=${encodeURIComponent(q)}` : ""}`) });
export const useHumidityTest = (id) => useQuery({ queryKey: ["humidity", "test", id], queryFn: () => getJSON(`${HUMIDITY}/tests/${id}`), enabled: !!id, retry: false });
export const useHumidityTrend = () => useQuery({ queryKey: ["humidity", "trend"], queryFn: () => getJSON(`${HUMIDITY}/trend`) });
export const useHumidityScale = () => useQuery({ queryKey: ["humidity", "reference-scale"], queryFn: () => getJSON(`${HUMIDITY}/reference-scale`) });

export async function analyzeHumidityWithPolling(payload, onTick) {
  const job = await postJson(`${HUMIDITY}/analyze/start`, payload);
  const started = Date.now();
  const deadline = started + 6 * 60 * 1000;
  while (Date.now() < deadline) {
    await sleep(2500);
    onTick?.(Math.round((Date.now() - started) / 1000));
    let status;
    try { status = await getJSON(`${HUMIDITY}/analyze/jobs/${job.id}`); } catch { continue; }
    if (status.status === "done" && status.record_id) return getJSON(`${HUMIDITY}/tests/${status.record_id}`);
    if (status.status === "error") throw new Error(status.error || "AI Vision analysis failed.");
  }
  throw new Error("Analisa AI terlalu lama. Coba foto spesimen yang lebih jelas.");
}

const invalidate = (qc) => qc.invalidateQueries({ queryKey: ["humidity"] });

export function useAnalyzeHumidity(onTick) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (payload) => analyzeHumidityWithPolling(payload, onTick), onSuccess: () => invalidate(qc) });
}

export function useUpdateHumidity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, changes }) => {
      const res = await fetch(`${HUMIDITY}/tests/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes) });
      if (!res.ok) throw new Error((await res.text()) || `Update failed: ${res.status}`);
      return res.json();
    },
    onSuccess: (data) => { qc.setQueryData(["humidity", "test", data.id], data); invalidate(qc); },
  });
}

export function useDeleteHumidity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id) => {
      const res = await fetch(`${HUMIDITY}/tests/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error((await res.text()) || "Delete failed");
      return res.json();
    },
    onSuccess: () => invalidate(qc),
  });
}

export function defaultHumiditySampleId() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `HC-${d.getFullYear()}-${p(d.getMonth() + 1)}${p(d.getDate())}-${Math.floor(Math.random() * 900) + 100}`;
}
