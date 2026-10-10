import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { FileDown, Loader2, Save, Trash2, UserCheck, X } from "lucide-react";
import { toast } from "sonner";
import { useDeleteHumidity, useHumidityTest, useUpdateHumidity, HUM_GRADES, gradeForCount } from "@/lib/humidity/api";
import HumidityGrid from "@/components/humidity/Grid";
import { Card, InfoRow } from "@/components/kht/ui";
import { fileUrl, imageToDataUri } from "@/lib/kht/api";
import { fmtDateTime } from "@/lib/kht/format";
import { hitBox, renderCalcFigure, renderOverlay } from "@/lib/rust/figure";
import { buildHumiditySingleHtml, printHtmlOnWeb } from "@/lib/humidity/pdf";

const Label = ({ children, right }) => (
  <div className="mb-3 flex items-center justify-between gap-2">
    <div className="font-mono text-[11px] tracking-[0.15em] text-amber-400">{children}</div>
    {right}
  </div>
);

const Seg = ({ options, value, onChange, testId }) => (
  <div className="flex rounded-md border border-zinc-700 bg-zinc-950 p-0.5" data-testid={testId}>
    {options.map(([k, label]) => (
      <button key={k} type="button" onClick={() => onChange(k)} data-testid={`${testId}-${k}`}
        className={`rounded px-2.5 py-1 font-mono text-[10px] font-bold tracking-widest ${value === k ? "bg-amber-500 text-zinc-950" : "text-zinc-400 hover:text-zinc-100"}`}>{label}</button>
    ))}
  </div>
);

function Detail({ data, boxesForCalc }) {
  const calc = useMemo(() => renderCalcFigure(boxesForCalc, { method: "full" }), [boxesForCalc]);
  const n = (boxesForCalc || []).filter(Boolean).length;
  const g = gradeForCount(n); const spec = HUM_GRADES[g];
  return (
    <div className="mt-4 flex flex-col gap-3" data-testid="humidity-detail">
      <div className="font-mono text-[11px] tracking-[0.15em] text-amber-400">DETAIL ANALISA · SELURUH GAMBAR</div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {[["KOTAK BERKARAT", `${n}/100`, "humidity-detail-count"], ["LUAS TERDAMPAK", `${n}%`, "humidity-detail-area"], ["GRADE", g, "humidity-detail-grade"], ["CONFIDENCE AI", `${Number(data.confidence || 0).toFixed(0)}%`, "humidity-detail-confidence"]].map(([k, v, t]) => (
          <div key={k} className="rounded border border-zinc-700 bg-zinc-950 p-2 text-center">
            <div className="font-mono text-[9px] tracking-widest text-zinc-500">{k}</div>
            <div className="mt-1 font-heading text-2xl font-bold" style={{ color: k === "GRADE" ? spec.color : "#fafafa" }} data-testid={t}>{v}</div>
          </div>
        ))}
      </div>
      <div className="rounded border p-2 text-center font-mono text-[11px]" style={{ color: spec.color, borderColor: `${spec.color}66`, backgroundColor: `${spec.color}12` }}>
        {spec.status} · {spec.label}
      </div>
      {data.specimen_box_count != null && <div className="font-mono text-[11px] text-zinc-400" data-testid="humidity-detail-specimen">Kotak berisi permukaan spesimen: {data.specimen_box_count}/100 · karat pada spesimen: {n} kotak</div>}
      <p className="font-mono text-[12px] leading-5 text-zinc-200" data-testid="humidity-detail-summary">{data.ai_summary || "—"}</p>
      <p className="font-mono text-[11px] leading-4 text-zinc-400">{data.recommendation || ""}</p>
      <div className="overflow-hidden rounded-lg border border-zinc-700 bg-white" data-testid="humidity-detail-calc"><img src={calc} alt="perhitungan ASTM D1748" className="w-full" /></div>
      <div className="font-mono text-[10px] text-zinc-500">Dianalisa {fmtDateTime(data.analyzed_at || data.created_at)}{data.edited ? " · grid dikoreksi inspector" : ""}</div>
    </div>
  );
}

function OverlayCard({ data, boxes, onToggle, onSave, dirty, saving }) {
  const [photo, setPhoto] = useState(null);
  const [view, setView] = useState("ai");
  const [img, setImg] = useState(null);
  const [geom, setGeom] = useState(null);
  const srcBoxes = useMemo(() => (view === "ai" ? (data.ai_grid_boxes || data.grid_boxes) : boxes), [data, view, boxes]);

  useEffect(() => {
    let alive = true;
    const url = fileUrl(data.image_path, 1600);
    imageToDataUri(url).then((d) => alive && setPhoto(d || url));
    return () => { alive = false; };
  }, [data.image_path]);

  useEffect(() => {
    if (!photo) return undefined;
    let alive = true;
    renderOverlay(photo, data.grid_corners, srcBoxes, { method: "full", label: view === "ai" ? "AI VISION" : "KOREKSI" })
      .then((r) => { if (alive) { setImg(r.dataUrl); setGeom(r.geom); } })
      .catch(() => alive && setImg(null));
    return () => { alive = false; };
  }, [photo, data, srcBoxes, view]);

  function clickPhoto(e) {
    if (!geom) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const idx = hitBox(geom, ((e.clientX - rect.left) / rect.width) * geom.w, ((e.clientY - rect.top) / rect.height) * geom.h);
    if (idx < 0) return;
    if (view !== "corr") setView("corr");
    onToggle(idx);
  }
  const corrN = boxes.filter(Boolean).length;
  const corrG = gradeForCount(corrN);
  const btn = "flex items-center gap-2 rounded-md px-3 py-2 font-mono text-[11px] font-bold tracking-widest disabled:opacity-50";

  return (
    <Card data-testid="humidity-overlay-card">
      <Label right={<Seg testId="humidity-overlay-view" value={view} onChange={setView} options={[["ai", "AI"], ["corr", "KOREKSI"]]} />}>PETA GRID PADA FOTO · SELURUH GAMBAR</Label>
      <div className="flex min-h-[220px] items-center justify-center overflow-hidden rounded-lg border border-zinc-700 bg-zinc-950" data-testid="humidity-overlay-wrap">
        {img ? <img src={img} alt="overlay grid ASTM D1748" onClick={clickPhoto} className="max-h-[520px] max-w-full cursor-crosshair" data-testid="humidity-overlay-image" /> : <Loader2 className="h-6 w-6 animate-spin text-amber-400" />}
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-md border border-red-500/40 bg-red-500/10 p-2" data-testid="humidity-overlay-edit-bar">
        <span className="font-mono text-[11px] text-zinc-200">Klik kotak pada foto untuk menghapus/menambah kotak merah · <b data-testid="humidity-overlay-live-count">{corrN}/100</b> · Grade <b style={{ color: HUM_GRADES[corrG].color }} data-testid="humidity-overlay-live-grade">{corrG}</b></span>
        <button type="button" onClick={onSave} disabled={!dirty || saving} data-testid="humidity-overlay-save" className={`${btn} bg-amber-500 text-zinc-950 hover:bg-amber-400`}>
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}SIMPAN KOREKSI
        </button>
      </div>
      <div className="mt-2 font-mono text-[10px] text-zinc-500">Seluruh foto = active zone, dibagi rata 10×10 kotak @10% lebar × 10% tinggi. Kotak merah = karat/korosi.</div>
      <Detail data={data} boxesForCalc={srcBoxes} />
    </Card>
  );
}

function InspectorCard({ data }) {
  const update = useUpdateHumidity();
  const [count, setCount] = useState("");
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  useEffect(() => {
    setCount(data.inspector_count ?? "");
    setName(data.inspector_name || data.meta?.operator || "");
    setNotes(data.inspector_notes || "");
  }, [data.id, data.inspector_count, data.inspector_name, data.inspector_notes, data.meta?.operator]);
  const n = count === "" ? null : Math.max(0, Math.min(100, Number(count) || 0));
  const g = n === null ? null : gradeForCount(n);
  const spec = g ? HUM_GRADES[g] : null;
  const aiN = data.ai_rusted_box_count ?? data.rusted_box_count;

  async function save() {
    if (n === null) { toast.error("Isi jumlah kotak berkarat (0–100)."); return; }
    try { await update.mutateAsync({ id: data.id, changes: { inspector_count: n, inspector_name: name, inspector_notes: notes } }); toast.success(`Penilaian inspector tersimpan — Grade ${g}.`); }
    catch (e) { toast.error(String(e?.message || "Gagal menyimpan").slice(0, 120)); }
  }
  async function clear() {
    try { await update.mutateAsync({ id: data.id, changes: { inspector_count: -1, inspector_notes: "" } }); toast.success("Penilaian manual dihapus."); }
    catch (e) { toast.error(String(e?.message || "Gagal menghapus").slice(0, 120)); }
  }

  return (
    <Card data-testid="humidity-inspector-card">
      <Label right={data.inspector_at ? <span className="font-mono text-[10px] text-zinc-500">Disimpan {fmtDateTime(data.inspector_at)}</span> : null}>PENILAIAN MANUAL INSPECTOR</Label>
      <div className="flex flex-col gap-3 sm:flex-row">
        <label className="flex flex-1 flex-col gap-1">
          <span className="font-mono text-[11px] text-zinc-300">Kotak berkarat (0–100)</span>
          <input data-testid="humidity-inspector-count" type="number" min={0} max={100} value={count} onChange={(e) => setCount(e.target.value)} placeholder={`AI: ${aiN}`}
            className="h-11 rounded-md border border-zinc-700 bg-zinc-900 px-3 font-mono text-sm text-zinc-50 outline-none focus:border-amber-500" />
        </label>
        <label className="flex flex-1 flex-col gap-1">
          <span className="font-mono text-[11px] text-zinc-300">Nama inspector</span>
          <input data-testid="humidity-inspector-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Nama inspector"
            className="h-11 rounded-md border border-zinc-700 bg-zinc-900 px-3 font-mono text-sm text-zinc-50 outline-none focus:border-amber-500" />
        </label>
        <div className="flex min-w-[120px] flex-col items-center justify-center rounded-md border px-3 py-1" data-testid="humidity-inspector-grade"
          style={spec ? { borderColor: `${spec.color}88`, backgroundColor: `${spec.color}14` } : { borderColor: "#3f3f46" }}>
          <span className="font-heading text-3xl font-bold" style={{ color: spec?.color || "#71717a" }}>{g || "—"}</span>
          <span className="font-mono text-[9px] tracking-widest text-zinc-500">{spec ? spec.status : "GRADE"}</span>
        </div>
      </div>
      <label className="mt-3 flex flex-col gap-1">
        <span className="font-mono text-[11px] text-zinc-300">Catatan inspector</span>
        <textarea data-testid="humidity-inspector-notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} placeholder="Observasi visual, alasan perbedaan dengan AI, dll."
          className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 font-mono text-[13px] text-zinc-50 outline-none focus:border-amber-500" />
      </label>
      {n !== null && <div className="mt-2 font-mono text-[11px] text-zinc-400" data-testid="humidity-inspector-diff">Selisih vs AI Vision: {n - aiN > 0 ? "+" : ""}{n - aiN} kotak (AI {aiN} · Grade {data.ai_grade || gradeForCount(aiN)})</div>}
      <div className="mt-3 flex gap-2">
        <button type="button" onClick={save} disabled={update.isPending} data-testid="humidity-inspector-save"
          className="flex flex-1 items-center justify-center gap-2 rounded-md bg-amber-500 py-3 font-mono text-xs font-bold tracking-widest text-zinc-950 hover:bg-amber-400 disabled:opacity-50">
          <UserCheck className="h-4 w-4" />{update.isPending ? "MENYIMPAN…" : "SIMPAN PENILAIAN"}
        </button>
        {data.inspector_count != null && (
          <button type="button" onClick={clear} disabled={update.isPending} data-testid="humidity-inspector-clear"
            className="flex items-center justify-center gap-1 rounded-md border border-zinc-700 px-4 font-mono text-xs text-zinc-300 hover:bg-zinc-800"><X className="h-4 w-4" />HAPUS</button>
        )}
      </div>
    </Card>
  );
}

export default function HumidityResult() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data, isLoading, isError } = useHumidityTest(id);
  const update = useUpdateHumidity();
  const del = useDeleteHumidity();
  const [boxes, setBoxes] = useState([]);
  const [exporting, setExporting] = useState(false);
  useEffect(() => { if (data) setBoxes(data.grid_boxes || Array(100).fill(false)); }, [data]);
  if (isLoading) return <div className="flex justify-center py-24"><Loader2 className="h-6 w-6 animate-spin text-amber-400" /></div>;
  if (isError || !data) return <div className="py-24 text-center font-mono text-xs text-zinc-500" data-testid="humidity-result-not-found">Inspection tidak ditemukan.</div>;
  const count = boxes.filter(Boolean).length;
  const liveGrade = gradeForCount(count);
  const grade = HUM_GRADES[liveGrade];
  const dirty = JSON.stringify(boxes) !== JSON.stringify(data.grid_boxes);
  const toggleBox = (index) => setBoxes((prev) => prev.map((value, i) => (i === index ? !value : value)));
  const aiN = data.ai_rusted_box_count ?? data.rusted_box_count;
  const aiGrade = data.ai_grade || gradeForCount(aiN);

  async function saveGrid() { try { await update.mutateAsync({ id, changes: { grid_boxes: boxes } }); toast.success(`Grid tersimpan — ${count}/100 kotak, Grade ${gradeForCount(count)}.`); } catch (e) { toast.error(String(e?.message || "Gagal menyimpan grid").slice(0, 120)); } }
  async function deleteRecord() { try { await del.mutateAsync(id); toast.success("Inspeksi dihapus."); navigate("/humidity-cabinet/history"); } catch (e) { toast.error(String(e?.message || "Gagal menghapus").slice(0, 120)); } }
  async function exportPdf() {
    setExporting(true);
    try { printHtmlOnWeb(await buildHumiditySingleHtml(data)); toast.success("Menyiapkan PDF — pilih \"Save as PDF\" di dialog print."); }
    catch (e) { toast.error(String(e?.message || "Gagal export PDF").slice(0, 120)); }
    finally { setExporting(false); }
  }
  function resetToAi() { setBoxes([...(data.ai_grid_boxes || data.grid_boxes)]); }

  return (
    <div className="flex flex-col gap-4 animate-fade-up" data-testid="humidity-result">
      <Card>
        <div className="flex items-center justify-between">
          <div className="font-mono text-[11px] tracking-[0.15em] text-amber-400">ASTM D1748 HUMIDITY CABINET RESULT</div>
          <button type="button" onClick={exportPdf} disabled={exporting} data-testid="humidity-export-pdf" title="Export PDF" className="flex h-10 items-center gap-2 rounded-md px-3 font-mono text-[11px] font-bold tracking-widest text-amber-400 hover:bg-zinc-800 disabled:opacity-50">
            {exporting ? <Loader2 className="h-5 w-5 animate-spin" /> : <FileDown className="h-5 w-5" />}<span className="hidden sm:inline">{exporting ? "MENYIAPKAN…" : "EXPORT PDF"}</span>
          </button>
        </div>
        <div className="mt-2 font-mono text-[15px] font-bold text-zinc-50" data-testid="humidity-result-sample-id">{data.meta.sample_id || "—"}</div>
        <div className="my-5 flex items-center justify-center gap-6">
          <div className="text-center"><div className="font-heading text-7xl font-bold" style={{ color: grade.color }} data-testid="humidity-result-grade">{liveGrade}</div><div className="font-mono text-[10px] tracking-widest text-zinc-500">GRADE RATING</div></div>
          <div className="h-20 w-px bg-zinc-700" />
          <div className="text-center"><div className="font-heading text-5xl font-bold text-zinc-50" data-testid="humidity-result-count">{count}</div><div className="font-mono text-[10px] tracking-widest text-zinc-500">RUSTED / 100</div></div>
        </div>
        <div className="rounded border p-3 text-center font-mono text-xs" style={{ color: grade.color, borderColor: `${grade.color}66`, backgroundColor: `${grade.color}12` }} data-testid="humidity-result-status">{grade.status} · {grade.label}</div>
        <div className="mt-3 grid grid-cols-3 gap-2 font-mono text-[10px]" data-testid="humidity-result-verdicts">
          <div className="rounded border border-zinc-700 bg-zinc-950 p-2 text-center"><div className="tracking-widest text-zinc-500">AI VISION · SELURUH FOTO</div><div className="mt-1 text-sm font-bold text-zinc-50" data-testid="humidity-result-ai-original">{aiN}/100 · {aiGrade}</div></div>
          <div className="rounded border border-zinc-700 bg-zinc-950 p-2 text-center"><div className="tracking-widest text-zinc-500">KOREKSI GRID</div><div className="mt-1 text-sm font-bold text-zinc-50">{data.rusted_box_count}/100 · {data.grade}</div></div>
          <div className="rounded border border-zinc-700 bg-zinc-950 p-2 text-center"><div className="tracking-widest text-zinc-500">MANUAL</div><div className="mt-1 text-sm font-bold text-zinc-50" data-testid="humidity-result-manual">{data.inspector_count != null ? `${data.inspector_count}/100 · ${data.inspector_grade}` : "—"}</div></div>
        </div>
      </Card>

      <OverlayCard data={data} boxes={boxes} onToggle={toggleBox} onSave={saveGrid} dirty={dirty} saving={update.isPending} />

      <Card>
        <Label right={<span className="font-mono text-[10px] text-zinc-500">Klik kotak untuk audit/koreksi</span>}>AI GRID DETECTION · SELURUH FOTO</Label>
        <HumidityGrid boxes={boxes} interactive onToggle={toggleBox} />
        <div className="mt-3 flex gap-2">
          <button type="button" onClick={saveGrid} disabled={update.isPending || !dirty} data-testid="humidity-save-grid" className="flex flex-1 items-center justify-center gap-2 rounded-md bg-amber-500 py-3 font-mono text-xs font-bold tracking-widest text-zinc-950 hover:bg-amber-400 disabled:opacity-50"><Save className="h-4 w-4" />{update.isPending ? "MENYIMPAN…" : "SIMPAN KOREKSI GRID"}</button>
          <button type="button" onClick={resetToAi} data-testid="humidity-reset-grid-ai" className="rounded-md border border-zinc-700 px-3 font-mono text-[11px] text-zinc-300 hover:bg-zinc-800">RESET KE AI</button>
        </div>
      </Card>

      <InspectorCard data={data} />

      <Card><div className="font-mono text-[11px] tracking-[0.15em] text-amber-400">CATATAN ANALISIS</div><p className="mt-2 font-mono text-[13px] leading-5 text-zinc-200" data-testid="humidity-result-summary">{data.ai_summary || "—"}</p><p className="mt-2 font-mono text-[11px] leading-4 text-zinc-400">{data.recommendation || "—"}</p></Card>
      <Card><div className="font-mono text-[11px] tracking-[0.15em] text-amber-400">TEST INFORMATION</div><InfoRow k="Product / Oil" v={data.meta.product || "—"} /><InfoRow k="Batch / Lot" v={data.meta.batch || "—"} /><InfoRow k="Exposure" v={`${data.meta.exposure_hours}h @ ${data.meta.temperature_c}°C`} /><InfoRow k="Humidity" v={`${data.meta.humidity_pct}% RH`} /><InfoRow k="Substrate" v={data.meta.substrate || "—"} /><InfoRow k="Operator" v={data.meta.operator || "—"} /><InfoRow k="AI confidence" v={`${Number(data.confidence).toFixed(0)}%`} /><InfoRow k="Analyzed" v={fmtDateTime(data.created_at)} last /></Card>
      <button type="button" onClick={deleteRecord} disabled={del.isPending} data-testid="humidity-delete-result" className="flex items-center justify-center gap-2 py-3 font-mono text-xs text-red-500 hover:text-red-400"><Trash2 className="h-4 w-4" /> HAPUS INSPEKSI</button>
    </div>
  );
}
