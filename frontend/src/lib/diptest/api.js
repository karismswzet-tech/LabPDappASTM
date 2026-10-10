import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API } from "@/lib/api";
import { fileUrl, imageToDataUri, uploadImage } from "@/lib/kht/api";

export { fileUrl, imageToDataUri, uploadImage };

export const DIP = `${API}/diptest`;

// Skala & label Grade A-E identik dengan Rust Preventing ASTM D1748.
export const DIP_GRADES = {
  A: { min: 0, max: 0, label: "Bersih tanpa karat", color: "#10B981", status: "EXCELLENT PASS" },
  B: { min: 1, max: 10, label: "Karat ringan", color: "#34D399", status: "GOOD / MINOR" },
  C: { min: 11, max: 25, label: "Karat sedang", color: "#FBBF24", status: "FAIR / MODERATE" },
  D: { min: 26, max: 50, label: "Karat luas", color: "#F97316", status: "POOR / EXTENSIVE" },
  E: { min: 51, max: 100, label: "Karat berat", color: "#EF4444", status: "REJECT / SEVERE" },
};

export function gradeForCount(count) {
  const n = Math.max(0, Math.min(100, Number(count) || 0));
  return Object.entries(DIP_GRADES).find(([, g]) => n >= g.min && n <= g.max)?.[0] || "E";
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

export const useDipDashboard = () => useQuery({ queryKey: ["diptest", "dashboard"], queryFn: () => getJSON(`${DIP}/dashboard`) });
export const useDipTests = (q) => useQuery({ queryKey: ["diptest", "tests", q ?? ""], queryFn: () => getJSON(`${DIP}/tests${q ? `?q=${encodeURIComponent(q)}` : ""}`) });
export const useDipTest = (id) => useQuery({ queryKey: ["diptest", "test", id], queryFn: () => getJSON(`${DIP}/tests/${id}`), enabled: !!id, retry: false });
export const useDipTrend = () => useQuery({ queryKey: ["diptest", "trend"], queryFn: () => getJSON(`${DIP}/trend`) });
export const useDipScale = () => useQuery({ queryKey: ["diptest", "reference-scale"], queryFn: () => getJSON(`${DIP}/reference-scale`) });

export async function analyzeDipWithPolling(payload, onTick) {
  const job = await postJson(`${DIP}/analyze/start`, payload);
  const started = Date.now();
  const deadline = started + 6 * 60 * 1000;
  while (Date.now() < deadline) {
    await sleep(2500);
    onTick?.(Math.round((Date.now() - started) / 1000));
    let status;
    try { status = await getJSON(`${DIP}/analyze/jobs/${job.id}`); } catch { continue; }
    if (status.status === "done" && status.record_id) return getJSON(`${DIP}/tests/${status.record_id}`);
    if (status.status === "error") throw new Error(status.error || "AI Vision analysis failed.");
  }
  throw new Error("Analisa AI terlalu lama. Coba foto spesimen yang lebih jelas.");
}

const invalidate = (qc) => qc.invalidateQueries({ queryKey: ["diptest"] });

export function useAnalyzeDip(onTick) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (payload) => analyzeDipWithPolling(payload, onTick), onSuccess: () => invalidate(qc) });
}

export function useUpdateDip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, changes }) => {
      const res = await fetch(`${DIP}/tests/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes) });
      if (!res.ok) throw new Error((await res.text()) || `Update failed: ${res.status}`);
      return res.json();
    },
    onSuccess: (data) => { qc.setQueryData(["diptest", "test", data.id], data); invalidate(qc); },
  });
}

export function useDeleteDip() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id) => {
      const res = await fetch(`${DIP}/tests/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error((await res.text()) || "Delete failed");
      return res.json();
    },
    onSuccess: () => invalidate(qc),
  });
}

export function defaultDipSampleId() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `DT-${d.getFullYear()}-${p(d.getMonth() + 1)}${p(d.getDate())}-${Math.floor(Math.random() * 900) + 100}`;
}
