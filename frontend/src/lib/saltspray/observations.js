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

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Upload-ready photo path -> AI detects 4 plates + rates each (whole-image 10x10). */
export async function detectPlatesWithPolling(photoPath, onTick) {
  const job = await send(`${SALT_OBS}/detect/start`, "POST", { photo_path: photoPath });
  const started = Date.now();
  const deadline = started + 8 * 60 * 1000;
  while (Date.now() < deadline) {
    await sleep(2500);
    let status;
    try { status = await getJSON(`${SALT_OBS}/detect/jobs/${job.id}`); } catch { continue; }
    onTick?.(Math.round((Date.now() - started) / 1000), status.stage);
    if (status.status === "done") return status;
    if (status.status === "error") throw new Error(status.error || "AI Vision gagal mendeteksi plat.");
  }
  throw new Error("Deteksi AI terlalu lama. Coba lagi dengan foto yang lebih jelas.");
}

export const countBoxes = (boxes) => (boxes || []).filter(Boolean).length;
