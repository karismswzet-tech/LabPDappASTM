import React, { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Camera, ImageIcon, Loader2, ScanLine, ShieldAlert, Sparkles, Tag } from "lucide-react";
import { toast } from "sonner";
import { defaultRustSampleId, ocrRustLabelWithPolling, uploadImage, useAnalyzeRust } from "@/lib/rust/api";
import { CameraCapture } from "@/components/kht/capture";
import { pickPreview } from "@/lib/kht/api";
import { METHOD_INFO } from "@/lib/rust/figure";

const GridOverlay = () => (
  <div className="pointer-events-none absolute inset-0 grid border-2 border-amber-400" style={{ gridTemplateColumns: "repeat(10, 1fr)", gridTemplateRows: "repeat(10, 1fr)" }} data-testid="rust-preview-full-grid">
    {Array.from({ length: 100 }, (_, i) => <div key={i} className="border border-cyan-300/70 text-[8px] leading-none text-white/80 [text-shadow:0_0_2px_#000]">{i + 1}</div>)}
  </div>
);

function MethodPicker({ value, onChange }) {
  return (
    <div className="flex flex-col gap-2" data-testid="rust-method-picker">
      <div className="font-mono text-[11px] tracking-[0.15em] text-amber-400">METODE PENILAIAN</div>
      <div className="grid gap-2 sm:grid-cols-2">
        {["zone", "full"].map((m) => (
          <button key={m} type="button" onClick={() => onChange(m)} data-testid={`rust-method-${m}`} aria-pressed={value === m}
            className={`flex flex-col gap-1 rounded-lg border p-3 text-left transition-colors ${value === m ? "border-amber-500 bg-amber-500/10" : "border-zinc-700 bg-zinc-900 hover:border-zinc-500"}`}>
            <span className="flex items-center gap-2 font-mono text-xs font-bold tracking-widest text-zinc-50">
              <span className={`h-3 w-3 rounded-full border ${value === m ? "border-amber-400 bg-amber-400" : "border-zinc-500"}`} />{METHOD_INFO[m].label.toUpperCase()}
            </span>
            <span className="font-mono text-[11px] leading-4 text-zinc-400">{METHOD_INFO[m].desc}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

const Field = ({ label, value, onChange, placeholder, numeric, testId }) => <label className="flex flex-1 flex-col gap-1"><span className="font-mono text-[11px] text-zinc-300">{label}</span><input data-testid={testId} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} inputMode={numeric ? "decimal" : "text"} className="h-11 rounded-md border border-zinc-700 bg-zinc-900 px-3 font-mono text-sm font-medium text-zinc-50 outline-none placeholder:text-zinc-500 focus:border-amber-500" /></label>;

function LabelOcrCard({ busy, stage, result, error, onScan, disabled }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-cyan-500/30 bg-zinc-900 p-3" data-testid="rust-ocr-card">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.15em] text-amber-400"><Tag className="h-4 w-4" />LABEL OCR (AI VISION)</div>
        <button type="button" onClick={onScan} disabled={disabled || busy} data-testid="rust-ocr-scan" className="flex items-center gap-2 rounded border border-zinc-700 bg-zinc-800 px-3 py-1.5 font-mono text-[11px] font-bold tracking-widest text-zinc-50 hover:border-amber-500/50 disabled:opacity-50">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ScanLine className="h-4 w-4" />}{result ? "BACA ULANG" : "BACA LABEL"}
        </button>
      </div>
      {busy ? <p className="font-mono text-[11px] text-zinc-300" data-testid="rust-ocr-stage">{stage || "Membaca label…"}</p>
        : error ? <p className="font-mono text-[11px] text-red-400" data-testid="rust-ocr-error">{error}</p>
        : result ? (
          <div className="flex flex-col gap-1 font-mono text-[11px] text-zinc-300" data-testid="rust-ocr-result">
            <div>Sample ID: <span className="font-bold text-zinc-50" data-testid="rust-ocr-sample-id">{result.sample_id || "— tidak terbaca —"}</span></div>
            {(result.operator || result.batch || result.temperature_c != null || result.duration_hours != null) && (
              <div className="flex flex-wrap gap-x-4">
                {result.operator && <span>Operator: <b className="text-zinc-50">{result.operator}</b></span>}
                {result.batch && <span>Batch: <b className="text-zinc-50">{result.batch}</b></span>}
                {result.temperature_c != null && <span>Temp: <b className="text-zinc-50">{result.temperature_c}°C</b></span>}
                {result.duration_hours != null && <span>Exposure: <b className="text-zinc-50">{result.duration_hours} h</b></span>}
              </div>
            )}
            {result.raw_text && <div className="truncate text-zinc-500" title={result.raw_text}>Teks terbaca: “{result.raw_text}”</div>}
          </div>
        ) : <p className="font-mono text-[11px] text-zinc-400">Kode sampel pada label/stiker panel dibaca otomatis setelah foto dipilih. Hasil langsung mengisi form dan tetap bisa dikoreksi manual.</p>}
    </div>
  );
}

export default function RustNewTest() {
  const navigate = useNavigate(); const galleryRef = useRef(null); const [imageUri, setImageUri] = useState(null); const [imagePath, setImagePath] = useState(null); const [showCamera, setShowCamera] = useState(false); const [busy, setBusy] = useState(false); const [method, setMethod] = useState("zone"); const [stage, setStage] = useState(""); const analyze = useAnalyzeRust((sec) => setStage(`AI Vision membaca grid 100 kotak… ${sec}s`));
  const [f, setF] = useState(() => ({ sampleId: defaultRustSampleId(), product: "", batch: "", operator: "", exposure: "168", temperature: "48.9", humidity: "95", substrate: "Cold Rolled Steel 1018", remark: "" })); const set = (k) => (v) => setF((s) => ({ ...s, [k]: v }));
  const sampleTouched = useRef(false); const uploadRef = useRef(null); const photoSeq = useRef(0);
  const [uploading, setUploading] = useState(false); const [ocrBusy, setOcrBusy] = useState(false); const [ocrStage, setOcrStage] = useState(""); const [ocrResult, setOcrResult] = useState(null); const [ocrError, setOcrError] = useState("");

  // Upload once per photo; analysis + OCR reuse the same storage path.
  function ensureUploaded(uri, knownPath) {
    if (knownPath) { uploadRef.current = { uri, promise: Promise.resolve(knownPath) }; return uploadRef.current.promise; }
    if (uploadRef.current?.uri === uri) return uploadRef.current.promise;
    setUploading(true);
    const promise = uploadImage(uri).then((p) => { if (uploadRef.current?.uri === uri) setImagePath(p); return p; }).finally(() => setUploading(false));
    uploadRef.current = { uri, promise };
    promise.catch(() => { if (uploadRef.current?.uri === uri) uploadRef.current = null; });
    return promise;
  }

  async function scanLabel(uri = imageUri, knownPath = imagePath) {
    if (!uri) return;
    const seq = photoSeq.current;
    setOcrBusy(true); setOcrError(""); setOcrStage("Mengunggah foto…");
    try {
      const path = await ensureUploaded(uri, knownPath);
      setOcrStage("Membaca label sampel…");
      const r = await ocrRustLabelWithPolling(path, (sec) => setOcrStage(`Membaca label sampel… ${sec}s`));
      if (seq !== photoSeq.current) return; // foto sudah diganti
      setOcrResult(r);
      const code = String(r.sample_id || "").trim();
      setF((s) => ({
        ...s,
        sampleId: code && !sampleTouched.current ? code : s.sampleId,
        operator: r.operator && !s.operator ? r.operator : s.operator,
        batch: r.batch && !s.batch ? r.batch : s.batch,
        temperature: r.temperature_c != null && s.temperature === "48.9" ? String(r.temperature_c) : s.temperature,
        exposure: r.duration_hours != null && s.exposure === "168" ? String(r.duration_hours) : s.exposure,
      }));
      if (code) { toast.success(`Label terbaca: ${code}`); }
      else toast.info("Kode sampel tidak terbaca pada label — isi manual bila perlu.");
    } catch (err) {
      if (seq !== photoSeq.current) return;
      const msg = `Baca label gagal: ${String(err?.message || "OCR error").slice(0, 140)}`;
      setOcrError(msg); toast.error(msg);
    } finally { if (seq === photoSeq.current) { setOcrBusy(false); setOcrStage(""); } }
  }

  async function choosePhoto(uri, path = null) {
    photoSeq.current += 1; uploadRef.current = null;
    setImageUri(uri); setImagePath(path); setOcrResult(null); setOcrError(""); setOcrBusy(false);
    void scanLabel(uri, path);
  }
  async function onGalleryPick(e) { const file = e.target.files?.[0]; e.target.value = ""; if (!file) return; try { const picked = await pickPreview(file); await choosePhoto(picked.previewUri, picked.imagePath); } catch (err) { toast.error(`Gagal membaca foto: ${String(err?.message || "format tidak didukung").slice(0, 120)}`); } }
  async function runAnalysis() { if (!imageUri) { toast.error("Ambil atau unggah foto metal panel bersama plat ukur 100 kotak."); return; } setBusy(true); try { setStage("Uploading foto inspeksi…"); const path = await ensureUploaded(imageUri, imagePath); setStage("AI Vision menghitung kotak berkarat…"); const result = await analyze.mutateAsync({ image_path: path, sample_id: f.sampleId, product: f.product, batch: f.batch, operator: f.operator, exposure_hours: Number(f.exposure) || 168, temperature_c: Number(f.temperature) || 48.9, humidity_pct: Number(f.humidity) || 95, substrate: f.substrate, remark: f.remark, method }); toast.success(`Analisa selesai — Grade ${result.grade}, ${result.rusted_box_count}/100 kotak berkarat.`); navigate(`/rust-preventing/result/${result.id}`); } catch (err) { toast.error(`Analisa gagal: ${String(err?.message || "AI Vision error").slice(0, 160)}`); } finally { setBusy(false); setStage(""); } }
  const pickBtn = (icon, label, onClick, testId) => <button type="button" onClick={onClick} data-testid={testId} className="flex min-w-[120px] flex-col items-center gap-2 rounded-md border border-zinc-700 bg-zinc-800 px-6 py-4 hover:border-amber-500/50">{icon}<span className="font-mono text-xs font-bold tracking-widest text-zinc-50">{label}</span></button>;
  return <div className="flex flex-col gap-3 pb-24 animate-fade-up" data-testid="rust-new-test"><input ref={galleryRef} type="file" accept="image/*" className="hidden" onChange={onGalleryPick} data-testid="rust-gallery-input" />
    {imageUri ? <div className="overflow-hidden rounded-xl border border-amber-500" data-testid="rust-image-preview-wrap"><div className="flex h-72 items-center justify-center bg-zinc-800"><div className="relative inline-block max-h-full"><img src={imageUri} alt="metal panel with measuring plate" className="block max-h-72 max-w-full object-contain" data-testid="rust-image-preview" />{method === "full" && <GridOverlay />}</div></div><div className="flex gap-2 bg-zinc-900 p-2"><button type="button" onClick={() => setShowCamera(true)} data-testid="rust-retake-camera" className="flex flex-1 items-center justify-center gap-2 rounded border border-zinc-700 bg-zinc-800 py-2 font-mono text-xs text-zinc-50"><Camera className="h-4 w-4" />Retake</button><button type="button" onClick={() => galleryRef.current?.click()} data-testid="rust-change-gallery" className="flex flex-1 items-center justify-center gap-2 rounded border border-zinc-700 bg-zinc-800 py-2 font-mono text-xs text-zinc-50"><ImageIcon className="h-4 w-4" />Change</button></div></div> : <div className="flex flex-col items-center gap-4 rounded-xl border border-dashed border-zinc-600 bg-zinc-900 p-6" data-testid="rust-pick-box"><ShieldAlert className="h-8 w-8 text-amber-400" /><p className="max-w-md text-center font-mono text-xs leading-5 text-zinc-300">Foto satu metal panel dengan measuring plate transparan 10×10. Pastikan area tengah 50×50 mm terlihat jelas dan bebas glare.</p><div className="flex gap-3">{pickBtn(<Camera className="h-6 w-6 text-amber-400" />, "CAMERA", () => setShowCamera(true), "rust-pick-camera")}{pickBtn(<ImageIcon className="h-6 w-6 text-amber-400" />, "GALLERY", () => galleryRef.current?.click(), "rust-pick-gallery")}</div></div>}
    {imageUri && <LabelOcrCard busy={ocrBusy} stage={ocrStage} result={ocrResult} error={ocrError} onScan={() => scanLabel()} disabled={!imageUri} />}
    {uploading && !ocrBusy && <p className="font-mono text-[11px] text-zinc-400" data-testid="rust-uploading">Mengunggah foto…</p>}
    <MethodPicker value={method} onChange={setMethod} />
    <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3" data-testid="rust-method-tip"><p className="font-mono text-[11px] leading-5 text-zinc-200">{method === "full" ? "Metode Seluruh Gambar: seluruh foto menjadi active zone dan dibagi rata 10×10 = 100 kotak. AI menandai kotak yang memuat karat pada permukaan spesimen; karat pada peralatan latar tidak dihitung." : "Metode Active Zone: AI hanya menghitung titik karat yang terlihat di dalam 100 kotak zona ukur 50×50 mm. Karat yang melewati garis potong ikut menghitung kotak tetangga."}</p></div>
    <div className="mt-2 font-mono text-[11px] tracking-[0.15em] text-amber-400">SAMPLE INFORMATION</div><Field label="Sample ID" value={f.sampleId} onChange={(v) => { sampleTouched.current = true; set("sampleId")(v); }} testId="rust-input-sample-id" /><Field label="Product / Rust Preventive Oil" value={f.product} onChange={set("product")} placeholder="Nama produk" testId="rust-input-product" /><Field label="Batch / Lot No." value={f.batch} onChange={set("batch")} placeholder="LOT-…" testId="rust-input-batch" /><Field label="Operator / Inspector" value={f.operator} onChange={set("operator")} placeholder="Nama inspector" testId="rust-input-operator" />
    <div className="mt-2 font-mono text-[11px] tracking-[0.15em] text-amber-400">EXPOSURE CONDITION</div><div className="flex gap-3"><Field label="Exposure (h)" value={f.exposure} onChange={set("exposure")} numeric testId="rust-input-exposure" /><Field label="Temp (°C)" value={f.temperature} onChange={set("temperature")} numeric testId="rust-input-temperature" /><Field label="RH (%)" value={f.humidity} onChange={set("humidity")} numeric testId="rust-input-humidity" /></div><Field label="Panel Substrate" value={f.substrate} onChange={set("substrate")} testId="rust-input-substrate" /><Field label="Remark" value={f.remark} onChange={set("remark")} placeholder="Opsional" testId="rust-input-remark" />
    <div className="fixed bottom-0 left-0 right-0 z-20 border-t border-zinc-700 bg-zinc-900 px-4 py-3 lg:left-72"><button type="button" onClick={runAnalysis} disabled={busy || !imageUri} data-testid="rust-run-analysis" className="mx-auto flex h-14 w-full max-w-4xl items-center justify-center gap-2 rounded-md bg-amber-500 font-mono text-sm font-bold tracking-widest text-zinc-950 hover:bg-amber-400 disabled:opacity-50">{busy ? <><Loader2 className="h-5 w-5 animate-spin" /><span data-testid="rust-analysis-stage">{stage || "PROCESSING…"}</span></> : <><Sparkles className="h-5 w-5" />RUN ASTM D1748 AI · {method === "full" ? "SELURUH GAMBAR" : "ZONA 50×50"}</>}</button></div><CameraCapture open={showCamera} onClose={() => setShowCamera(false)} onCapture={(uri) => { setShowCamera(false); void choosePhoto(uri); }} />
  </div>;
}
