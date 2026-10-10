import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API } from "@/lib/api";
import { fileUrl, imageToDataUri, uploadImage } from "@/lib/kht/api";

export { fileUrl, imageToDataUri, uploadImage };

export const RUST = `${API}/rust`;

export const RUST_GRADES = {
  A: { min: 0, max: 0, label: "Bersih tanpa karat", color: "#10B981", status: "EXCELLENT PASS" },
  B: { min: 1, max: 10, label: "Karat ringan", color: "#34D399", status: "GOOD / MINOR" },
  C: { min: 11, max: 25, label: "Karat sedang", color: "#FBBF24", status: "FAIR / MODERATE" },
  D: { min: 26, max: 50, label: "Karat luas", color: "#F97316", status: "POOR / EXTENSIVE" },
  E: { min: 51, max: 100, label: "Karat berat", color: "#EF4444", status: "REJECT / SEVERE" },
};

export function gradeForCount(count) {
  const n = Math.max(0, Math.min(100, Number(count) || 0));
  return Object.entries(RUST_GRADES).find(([, g]) => n >= g.min && n <= g.max)?.[0] || "E";
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

export const useRustDashboard = () => useQuery({ queryKey: ["rust", "dashboard"], queryFn: () => getJSON(`${RUST}/dashboard`) });
export const useRustTests = (q) => useQuery({ queryKey: ["rust", "tests", q ?? ""], queryFn: () => getJSON(`${RUST}/tests${q ? `?q=${encodeURIComponent(q)}` : ""}`) });
export const useRustTest = (id) => useQuery({ queryKey: ["rust", "test", id], queryFn: () => getJSON(`${RUST}/tests/${id}`), enabled: !!id, retry: false });
export const useRustTrend = () => useQuery({ queryKey: ["rust", "trend"], queryFn: () => getJSON(`${RUST}/trend`) });
export const useRustScale = () => useQuery({ queryKey: ["rust", "reference-scale"], queryFn: () => getJSON(`${RUST}/reference-scale`) });

export async function analyzeRustWithPolling(payload, onTick) {
  const job = await postJson(`${RUST}/analyze/start`, payload);
  const started = Date.now();
  const deadline = started + 6 * 60 * 1000;
  while (Date.now() < deadline) {
    await sleep(2500);
    onTick?.(Math.round((Date.now() - started) / 1000));
    let status;
    try { status = await getJSON(`${RUST}/analyze/jobs/${job.id}`); } catch { continue; }
    if (status.status === "done" && status.record_id) return getJSON(`${RUST}/tests/${status.record_id}`);
    if (status.status === "error") throw new Error(status.error || "AI Vision analysis failed.");
  }
  throw new Error("Analisa AI terlalu lama. Coba foto dengan grid transparan yang lebih jelas.");
}

const invalidate = (qc) => qc.invalidateQueries({ queryKey: ["rust"] });

export async function ocrRustLabelWithPolling(image_path, onTick) {
  const job = await postJson(`${RUST}/ocr/start`, { image_path });
  const started = Date.now();
  const deadline = started + 4 * 60 * 1000;
  while (Date.now() < deadline) {
    await sleep(2000);
    onTick?.(Math.round((Date.now() - started) / 1000));
    let st;
    try { st = await getJSON(`${RUST}/ocr/jobs/${job.id}`); } catch { continue; }
    if (st.status === "done") return st.result || {};
    if (st.status === "error") throw new Error(st.error || "OCR gagal membaca label.");
  }
  throw new Error("OCR memakan waktu terlalu lama. Coba foto label yang lebih jelas.");
}

export function useAnalyzeRust(onTick) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (payload) => analyzeRustWithPolling(payload, onTick), onSuccess: () => invalidate(qc) });
}

export function useUpdateRust() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, changes }) => {
      const res = await fetch(`${RUST}/tests/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes) });
      if (!res.ok) throw new Error((await res.text()) || `Update failed: ${res.status}`);
      return res.json();
    },
    onSuccess: (data) => { qc.setQueryData(["rust", "test", data.id], data); invalidate(qc); },
  });
}

export async function analyzeRustMethodWithPolling(id, method, onTick) {
  const job = await postJson(`${RUST}/tests/${id}/method/analyze`, { method });
  const started = Date.now();
  const deadline = started + 6 * 60 * 1000;
  while (Date.now() < deadline) {
    await sleep(2500);
    onTick?.(Math.round((Date.now() - started) / 1000));
    let status;
    try { status = await getJSON(`${RUST}/analyze/jobs/${job.id}`); } catch { continue; }
    if (status.status === "done") return getJSON(`${RUST}/tests/${id}`);
    if (status.status === "error") throw new Error(status.error || "AI Vision analysis failed.");
  }
  throw new Error("Analisa AI terlalu lama. Coba lagi.");
}

export function useAnalyzeRustMethod(onTick) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, method }) => analyzeRustMethodWithPolling(id, method, onTick),
    onSuccess: (data) => { qc.setQueryData(["rust", "test", data.id], data); invalidate(qc); },
  });
}

export function useSwitchRustMethod() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, method }) => {
      const res = await fetch(`${RUST}/tests/${id}/method`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ method }) });
      if (!res.ok) {
        let msg = `Gagal mengganti metode: ${res.status}`;
        try { msg = (await res.json()).detail || msg; } catch { /* ignore */ }
        throw new Error(msg);
      }
      return res.json();
    },
    onSuccess: (data) => { qc.setQueryData(["rust", "test", data.id], data); invalidate(qc); },
  });
}

export function useLocateRustGrid() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id) => {
      const res = await fetch(`${RUST}/tests/${id}/locate-grid`, { method: "POST" });
      if (!res.ok) {
        let msg = `Deteksi grid gagal: ${res.status}`;
        try { msg = (await res.json()).detail || msg; } catch { /* ignore */ }
        throw new Error(msg);
      }
      return res.json();
    },
    onSuccess: (data) => { qc.setQueryData(["rust", "test", data.id], data); invalidate(qc); },
  });
}

export function useDeleteRust() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id) => {
      const res = await fetch(`${RUST}/tests/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error((await res.text()) || "Delete failed");
      return res.json();
    },
    onSuccess: () => invalidate(qc),
  });
}

export function defaultRustSampleId() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `RP-${d.getFullYear()}-${p(d.getMonth() + 1)}${p(d.getDate())}-${Math.floor(Math.random() * 900) + 100}`;
}
