import React, { useMemo, useRef, useState } from "react";
import { Camera, ClipboardList, FileDown, ImageIcon, Loader2, Plus, RefreshCw, RotateCcw, Save, ScanSearch, Sparkles, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/kht/ui";
import { CameraCapture } from "@/components/kht/capture";
import { fileUrl, gradeForCount, SALT_GRADES, uploadImage } from "@/lib/saltspray/api";
import { pickPreview } from "@/lib/kht/api";
import { countBoxes, detectPlatesWithPolling, fetchObsHeader, useCreateObservation, useDeleteObservation, useObservations, useUpdateObservation } from "@/lib/saltspray/observations";
import { buildObservationsHtml, printHtmlOnWeb } from "@/lib/saltspray/observationsPdf";
import { nextReportHour, REPORT_HOURS } from "@/lib/saltspray/obsReport";
import { ObsHeaderForm, ObsReportTable } from "@/components/saltspray/ObsReport";
import { buildReport } from "@/lib/saltspray/obsReport";

const PLATE_COLORS = ["#F59E0B", "#22D3EE", "#A78BFA", "#34D399"];
const inputCls = "h-10 w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 font-mono text-sm text-zinc-50 outline-none placeholder:text-zinc-600 focus:border-amber-500";

/** Plate crop = active zone, divided evenly 10x10. Rusted boxes are red + numbered; click toggles. */
function PlateGrid({ src, boxes, onToggle, testId }) {
  return (
    <div className="relative w-full overflow-hidden rounded border border-zinc-600 bg-zinc-950" data-testid={testId}>
      {src ? <img src={src} alt="plat uji" className="block w-full select-none" draggable={false} /> : <div className="aspect-[3/4] w-full" />}
      <div className="absolute inset-0 grid grid-cols-10 grid-rows-[repeat(10,minmax(0,1fr))]">
        {Array.from({ length: 100 }, (_, i) => {
          const rusted = Boolean(boxes?.[i]);
          return (
            <button
              key={i}
              type="button"
              onClick={() => onToggle(i)}
              data-testid={`${testId}-box-${i + 1}`}
              aria-label={`Kotak ${i + 1}${rusted ? " berkarat" : ""}`}
              className={`flex items-center justify-center border-[0.5px] font-mono text-[8px] font-bold leading-none transition-colors sm:text-[9px] ${rusted ? "border-red-500 bg-red-500/45 text-white [text-shadow:0_0_2px_#000]" : "border-cyan-300/30 text-transparent hover:bg-amber-400/20 hover:text-white"}`}
            >{i + 1}</button>
          );
        })}
      </div>
    </div>
  );
}

function PlateCard({ plate, i, onCode, onToggle, onReset }) {
  const n = countBoxes(plate.grid_boxes);
  const g = gradeForCount(n);
  const aiN = plate.ai_rusted_box_count ?? countBoxes(plate.ai_grid_boxes);
  const edited = JSON.stringify((plate.grid_boxes || []).map(Boolean)) !== JSON.stringify((plate.ai_grid_boxes || plate.grid_boxes || []).map(Boolean));
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-lg border border-zinc-700 bg-zinc-900/60 p-2" data-testid={`obs-plate-${i + 1}`}>
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full font-mono text-[11px] font-bold text-zinc-950" style={{ background: PLATE_COLORS[i] }}>{i + 1}</span>
        <span className="font-mono text-[11px] font-bold tracking-widest text-zinc-200">SAMPLE {i + 1}</span>
      </div>
      <input value={plate.code || ""} onChange={(e) => onCode(e.target.value)} placeholder={plate.label ? `contoh: ${plate.label}` : "Kode sample"} list="obs-known-codes" className={inputCls} data-testid={`obs-plate-code-${i + 1}`} />
      <PlateGrid src={plate.crop_path ? fileUrl(plate.crop_path, 900) : null} boxes={plate.grid_boxes} onToggle={onToggle} testId={`obs-plate-grid-${i + 1}`} />
      <div className="flex items-center justify-between gap-2">
        <div className="font-mono text-xs text-zinc-200"><span className="text-lg font-bold text-white" data-testid={`obs-plate-count-${i + 1}`}>{n}</span>/100</div>
        <span className="rounded px-2 py-0.5 font-mono text-xs font-bold text-zinc-950" style={{ background: SALT_GRADES[g].color }} data-testid={`obs-plate-grade-${i + 1}`}>GRADE {g}</span>
      </div>
      <div className="font-mono text-[10px] text-zinc-400">{SALT_GRADES[g].label}{plate.confidence ? ` · conf ${Math.round(plate.confidence)}%` : ""}</div>
      {edited && (
        <div className="flex items-center justify-between gap-1 rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1 font-mono text-[10px] text-amber-300">
          <span>Dikoreksi inspector · AI: {aiN}</span>
          <button type="button" onClick={onReset} className="flex items-center gap-1 hover:text-white" data-testid={`obs-plate-reset-${i + 1}`}><RotateCcw className="h-3 w-3" />AI</button>
        </div>
      )}
      {plate.summary && <p className="font-mono text-[10px] leading-4 text-zinc-400">{plate.summary}</p>}
    </div>
  );
}

function CardEditor({ card, draft = false, onDone }) {
  const create = useCreateObservation();
  const update = useUpdateObservation();
  const del = useDeleteObservation();
  const galleryRef = useRef(null);
  const [seq, setSeq] = useState(String(card.seq ?? 1));
  const [hours, setHours] = useState(card.hours == null ? "" : String(card.hours));
  const [photoPath, setPhotoPath] = useState(card.photo_path || null);
  const [preview, setPreview] = useState(card.photo_path ? fileUrl(card.photo_path, 1600) : null);
  const [plates, setPlates] = useState(card.plates || []);
  const [detection, setDetection] = useState(card.detection || "");
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("");
  const [showCamera, setShowCamera] = useState(false);
  const saving = create.isPending || update.isPending;

  async function detect(path, keepCodes = true) {
    setBusy(true);
    setStage("AI Vision mendeteksi 4 plat…");
    try {
      const res = await detectPlatesWithPolling(path, (sec, st) => setStage(`${st || "Memproses…"} ${sec}s`));
      setPlates((prev) => res.plates.map((p, i) => ({ ...p, code: keepCodes ? (prev[i]?.code || "") : "" })));
      setDetection(res.detection);
      if (res.detection === "ai") toast.success("4 plat terdeteksi & dinilai. Isi kode Sample 1–4 lalu simpan.");
      else toast.warning("AI tidak menemukan tepat 4 plat — foto dibagi 4 kolom sama rata. Coba Deteksi Ulang bila perlu.");
    } catch (e) {
      toast.error(String(e?.message || "Deteksi gagal").slice(0, 160));
    } finally {
      setBusy(false);
      setStage("");
    }
  }

  async function applyPhoto(uri, path = null) {
    setPreview(uri);
    setBusy(true);
    setStage("Mengunggah foto…");
    try {
      const p = path || await uploadImage(uri);
      setPhotoPath(p);
      setPreview(fileUrl(p, 1600));
      await detect(p, true);
    } catch (e) {
      toast.error(`Gagal unggah foto: ${String(e?.message || "error").slice(0, 120)}`);
      setBusy(false);
      setStage("");
    }
  }

  async function onGallery(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try { const picked = await pickPreview(file); await applyPhoto(picked.previewUri, picked.imagePath); }
    catch (err) { toast.error(`Gagal membaca foto: ${String(err?.message || "format tidak didukung").slice(0, 120)}`); }
  }

  const patch = (i, fn) => setPlates((prev) => prev.map((p, k) => (k === i ? fn(p) : p)));
  const toggle = (i, box) => patch(i, (p) => { const b = Array.from({ length: 100 }, (_, k) => Boolean(p.grid_boxes?.[k])); b[box] = !b[box]; return { ...p, grid_boxes: b }; });

  async function save() {
    if (!photoPath || plates.length !== 4) { toast.error("Upload foto 4 plat dan tunggu deteksi selesai."); return; }
    const missing = plates.findIndex((p) => !String(p.code || "").trim());
    if (missing >= 0) { toast.error(`Isi kode Sample ${missing + 1} dulu.`); return; }
    if (hours === "" || Number.isNaN(Number(hours)) || Number(hours) < 0) { toast.error("Isi Jam Pengamatan (angka jam, mis. 24)."); return; }
    const body = { seq: Number(seq) || 1, hours: Number(hours), duration_label: `${Number(hours)} Jam`, photo_path: photoPath, detection, plates };
    try {
      if (draft) { await create.mutateAsync(body); toast.success("Kartu pengamatan tersimpan."); onDone?.(); }
      else { await update.mutateAsync({ id: card.id, body }); toast.success("Kartu pengamatan diperbarui."); }
    } catch (e) { toast.error(String(e?.message || "Gagal menyimpan").slice(0, 160)); }
  }

  async function remove() {
    if (draft) { onDone?.(); return; }
    if (!window.confirm("Hapus kartu pengamatan ini?")) return;
    try { await del.mutateAsync(card.id); toast.success("Kartu dihapus."); }
    catch (e) { toast.error(String(e?.message || "Gagal menghapus").slice(0, 120)); }
  }

  return (
    <Card data-testid={draft ? "obs-card-draft" : `obs-card-${card.id}`}>
      <input ref={galleryRef} type="file" accept="image/*" className="hidden" onChange={onGallery} data-testid="obs-photo-input" />
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex w-24 flex-col gap-1"><span className="font-mono text-[10px] text-zinc-400">No. Urut</span>
          <input type="number" min={1} value={seq} onChange={(e) => setSeq(e.target.value)} className={inputCls} data-testid="obs-seq" /></label>
        <label className="flex min-w-[160px] flex-1 flex-col gap-1"><span className="font-mono text-[10px] text-zinc-400">Jam Pengamatan (Hours)</span>
          <div className="relative"><input type="number" min={0} step="any" value={hours} onChange={(e) => setHours(e.target.value)} placeholder="pilih / ketik jam, mis. 24" list="obs-hours-list" className={`${inputCls} pr-14`} data-testid="obs-hours" />
            <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 font-mono text-xs text-zinc-500">Jam</span></div></label>
        <datalist id="obs-hours-list">{REPORT_HOURS.map((h) => <option key={h} value={h} />)}</datalist>
        {draft && <span className="rounded bg-amber-500/20 px-2 py-1 font-mono text-[10px] font-bold tracking-widest text-amber-400">KARTU BARU · BELUM DISIMPAN</span>}
      </div>

      {!preview ? (
        <div className="mt-4 flex flex-col items-center gap-3 rounded-xl border border-dashed border-zinc-600 bg-zinc-900 p-6" data-testid="obs-photo-pick">
          <ScanSearch className="h-8 w-8 text-amber-400" />
          <p className="max-w-md text-center font-mono text-xs leading-5 text-zinc-300">Upload <b>1 foto berisi 4 plat uji</b>. AI Vision memisahkan tiap plat, lalu menilai dengan Metode Seluruh Gambar: potongan plat = active zone, dibagi rata 10×10 (10% lebar × 10% tinggi).</p>
          <div className="flex gap-3">
            <button type="button" onClick={() => setShowCamera(true)} data-testid="obs-pick-camera" className="flex min-w-[120px] flex-col items-center gap-2 rounded-md border border-zinc-700 bg-zinc-800 px-6 py-4 hover:border-amber-500/50"><Camera className="h-6 w-6 text-amber-400" /><span className="font-mono text-xs font-bold tracking-widest text-zinc-50">CAMERA</span></button>
            <button type="button" onClick={() => galleryRef.current?.click()} data-testid="obs-pick-gallery" className="flex min-w-[120px] flex-col items-center gap-2 rounded-md border border-zinc-700 bg-zinc-800 px-6 py-4 hover:border-amber-500/50"><ImageIcon className="h-6 w-6 text-amber-400" /><span className="font-mono text-xs font-bold tracking-widest text-zinc-50">GALLERY</span></button>
          </div>
        </div>
      ) : (
        <div className="mt-4 overflow-hidden rounded-xl border border-zinc-700" data-testid="obs-photo-wrap">
          <div className="flex justify-center bg-zinc-950">
            <div className="relative inline-block">
              <img src={preview} alt="foto 4 plat" className="block max-h-80 max-w-full object-contain" data-testid="obs-photo-preview" />
              {!busy && plates.map((p, i) => p.bbox && (
                <div key={i} className="pointer-events-none absolute border-2" style={{ left: `${p.bbox[0] * 100}%`, top: `${p.bbox[1] * 100}%`, width: `${p.bbox[2] * 100}%`, height: `${p.bbox[3] * 100}%`, borderColor: PLATE_COLORS[i] }} data-testid={`obs-photo-bbox-${i + 1}`}>
                  <span className="absolute left-0 top-0 px-1.5 font-mono text-[11px] font-bold text-zinc-950" style={{ background: PLATE_COLORS[i] }}>{i + 1}{p.code ? ` · ${p.code}` : ""}</span>
                </div>
              ))}
              {busy && <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-zinc-950/70"><Loader2 className="h-7 w-7 animate-spin text-amber-400" /><span className="px-3 text-center font-mono text-xs text-amber-300" data-testid="obs-detect-stage">{stage}</span></div>}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 bg-zinc-900 p-2">
            {detection && <span className={`rounded px-2 py-1 font-mono text-[10px] font-bold tracking-wider ${detection === "ai" ? "bg-emerald-500/15 text-emerald-400" : "bg-orange-500/15 text-orange-400"}`} data-testid="obs-detection-mode">{detection === "ai" ? "AI: 4 PLAT TERDETEKSI" : "FALLBACK: DIBAGI 4 KOLOM"}</span>}
            <div className="ml-auto flex gap-2">
              <button type="button" disabled={busy || !photoPath} onClick={() => detect(photoPath, true)} data-testid="obs-redetect" className="flex items-center gap-1 rounded border border-zinc-700 bg-zinc-800 px-3 py-1.5 font-mono text-[11px] text-zinc-100 hover:border-amber-500/60 disabled:opacity-50"><RefreshCw className="h-3.5 w-3.5" />Deteksi Ulang</button>
              <button type="button" disabled={busy} onClick={() => galleryRef.current?.click()} data-testid="obs-change-photo" className="flex items-center gap-1 rounded border border-zinc-700 bg-zinc-800 px-3 py-1.5 font-mono text-[11px] text-zinc-100 hover:border-amber-500/60 disabled:opacity-50"><ImageIcon className="h-3.5 w-3.5" />Ganti Foto</button>
            </div>
          </div>
        </div>
      )}

      {plates.length === 4 && (
        <>
          <div className="mt-4 flex items-center gap-2 font-mono text-[10px] tracking-widest text-zinc-400"><Sparkles className="h-3.5 w-3.5 text-amber-400" />KOTAK MERAH BERNOMOR = KOTAK BERKARAT · KLIK KOTAK UNTUK KOREKSI INSPECTOR</div>
          <div className="mt-2 grid grid-cols-2 gap-3 md:grid-cols-4" data-testid="obs-plates">
            {plates.map((p, i) => (
              <PlateCard key={i} plate={p} i={i}
                onCode={(v) => patch(i, (x) => ({ ...x, code: v }))}
                onToggle={(box) => toggle(i, box)}
                onReset={() => patch(i, (x) => ({ ...x, grid_boxes: [...(x.ai_grid_boxes || x.grid_boxes)] }))} />
            ))}
          </div>
        </>
      )}

      <div className="mt-4 flex gap-2 border-t border-zinc-700 pt-3">
        <button type="button" onClick={save} disabled={saving || busy || plates.length !== 4} data-testid="obs-save" className="flex flex-1 items-center justify-center gap-2 rounded-md bg-amber-500 py-2.5 font-mono text-xs font-bold tracking-widest text-zinc-950 hover:bg-amber-400 disabled:opacity-50"><Save className="h-4 w-4" />{saving ? "MENYIMPAN…" : "SIMPAN KARTU"}</button>
        <button type="button" onClick={remove} disabled={del.isPending || busy} data-testid="obs-delete" className="flex items-center justify-center gap-1 rounded-md border border-red-700/60 px-4 font-mono text-xs text-red-400 hover:bg-red-500/10 disabled:opacity-50">{draft ? <><X className="h-4 w-4" />BATAL</> : <><Trash2 className="h-4 w-4" />HAPUS</>}</button>
      </div>
      <CameraCapture open={showCamera} onClose={() => setShowCamera(false)} onCapture={(uri) => { setShowCamera(false); void applyPhoto(uri); }} />
    </Card>
  );
}

export default function SaltObservations() {
  const { data, isLoading } = useObservations();
  const [draft, setDraft] = useState(null);
  const [exporting, setExporting] = useState(false);
  const cards = useMemo(() => data || [], [data]);
  const report = useMemo(() => buildReport(cards), [cards]);

  function addCard() {
    if (draft) { toast.info("Selesaikan atau batalkan kartu baru terlebih dahulu."); return; }
    const nextSeq = cards.reduce((m, c) => Math.max(m, c.seq || 0), 0) + 1;
    setDraft({ key: Date.now(), seq: nextSeq, hours: nextReportHour(cards), plates: [] });
  }
  async function exportPdf() {
    if (!cards.length) { toast.info("Belum ada kartu untuk diexport."); return; }
    setExporting(true);
    try { const header = await fetchObsHeader().catch(() => ({}));
      printHtmlOnWeb(await buildObservationsHtml(cards, header, report)); toast.success("Menyiapkan PDF — pilih \"Save as PDF\" di dialog print."); }
    catch (e) { toast.error(String(e?.message || "Gagal export PDF").slice(0, 120)); }
    finally { setExporting(false); }
  }

  return (
    <div className="flex flex-col gap-4 pb-16 animate-fade-up" data-testid="salt-observations">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.15em] text-amber-400"><ClipboardList className="h-4 w-4" /> KARTU PENGAMATAN · 1 FOTO = 4 PLAT</div>
        <div className="ml-auto flex gap-2">
          <button type="button" onClick={addCard} data-testid="obs-add-card" className="flex h-10 items-center gap-2 rounded-md bg-amber-500 px-4 font-mono text-xs font-bold tracking-widest text-zinc-950 hover:bg-amber-400"><Plus className="h-4 w-4" />KARTU BARU</button>
          <button type="button" onClick={exportPdf} disabled={exporting || !cards.length} data-testid="obs-export-pdf" className="flex h-10 items-center gap-2 rounded-md border border-amber-500/60 px-4 font-mono text-xs font-bold tracking-widest text-amber-400 hover:bg-amber-500/10 disabled:opacity-50">{exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}EXPORT PDF</button>
        </div>
      </div>

      <datalist id="obs-known-codes">{report.samples.map((c) => <option key={c} value={c} />)}</datalist>
      <ObsHeaderForm report={report} />
      <ObsReportTable report={report} />
      <div className="mt-2 flex items-center gap-2 font-mono text-[11px] tracking-[0.15em] text-amber-400"><ClipboardList className="h-4 w-4" /> DAFTAR KARTU PENGAMATAN</div>

      {draft && <CardEditor key={draft.key} card={draft} draft onDone={() => setDraft(null)} />}

      {isLoading ? <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-amber-400" /></div>
        : cards.length === 0 && !draft ? <div className="py-16 text-center font-mono text-xs text-zinc-500" data-testid="obs-empty">Belum ada kartu pengamatan. Klik tombol KARTU BARU lalu upload 1 foto berisi 4 plat.</div>
          : <div className="flex flex-col gap-4">{cards.map((c) => <CardEditor key={`${c.id}-${c.updated_at || c.created_at}`} card={c} />)}</div>}
    </div>
  );
}
