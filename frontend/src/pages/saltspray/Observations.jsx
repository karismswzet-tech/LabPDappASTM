import React, { useRef, useState } from "react";
import { ClipboardList, FileDown, ImagePlus, Loader2, Plus, Save, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/kht/ui";
import { fileUrl, uploadImage } from "@/lib/saltspray/api";
import { obsGroupLabel, useCreateObservation, useDeleteObservation, useObservations, useUpdateObservation } from "@/lib/saltspray/observations";
import { buildObservationsHtml, printHtmlOnWeb } from "@/lib/saltspray/observationsPdf";

let uidCounter = 0;
const nextUid = () => `s${Date.now()}_${uidCounter++}`;
const withUid = (samples) => (samples || []).map((s) => ({ uid: nextUid(), code: s.code, type: s.type, photo_path: s.photo_path || null }));

function SampleCell({ sample, onPhoto, onRemove }) {
  const fileRef = useRef(null);
  const [busy, setBusy] = useState(false);
  async function pick(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setBusy(true);
    const url = URL.createObjectURL(file);
    try {
      const path = await uploadImage(url);
      onPhoto(path);
    } catch (err) {
      toast.error(`Gagal unggah foto: ${String(err?.message || "error").slice(0, 100)}`);
    } finally {
      URL.revokeObjectURL(url);
      setBusy(false);
    }
  }
  return (
    <div className="flex w-28 shrink-0 flex-col gap-1" data-testid={`obs-cell-${sample.code}-${sample.type}`}>
      <div className="relative flex h-36 items-center justify-center overflow-hidden rounded border border-zinc-600 bg-zinc-950">
        {sample.photo_path ? (
          <img src={fileUrl(sample.photo_path, 640)} alt={sample.code} className="h-full w-full object-cover" />
        ) : (
          <span className="px-1 text-center font-mono text-[9px] text-zinc-500">tanpa foto</span>
        )}
        {busy && <div className="absolute inset-0 flex items-center justify-center bg-zinc-950/70"><Loader2 className="h-5 w-5 animate-spin text-amber-400" /></div>}
        <button type="button" onClick={onRemove} data-testid={`obs-cell-remove-${sample.code}-${sample.type}`} className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full bg-red-600/90 text-white hover:bg-red-500"><X className="h-3 w-3" /></button>
      </div>
      <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={pick} />
      <button type="button" onClick={() => fileRef.current?.click()} disabled={busy} className="flex items-center justify-center gap-1 rounded border border-zinc-700 bg-zinc-800 py-1 font-mono text-[10px] text-zinc-200 hover:border-amber-500/60 disabled:opacity-50">
        <ImagePlus className="h-3 w-3" />{sample.photo_path ? "Ganti" : "Upload"}
      </button>
      <div className="text-center font-mono text-[10px] font-bold text-zinc-300">{sample.code} ({sample.type})</div>
    </div>
  );
}

function Group({ title, prefix, list, onPhoto, onRemove }) {
  return (
    <div className="flex flex-col gap-2" data-testid={`obs-group-${title}`}>
      <div className="font-mono text-[11px] leading-5 text-zinc-100">
        <span className="mr-2 rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-bold tracking-widest text-amber-400">GRUP {title}</span>
        {list.length ? obsGroupLabel(prefix, list) : <span className="text-zinc-500">belum ada sample tipe {title}</span>}
      </div>
      {list.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1" data-testid={`obs-group-photos-${title}`}>
          {list.map((s) => <SampleCell key={s.uid} sample={s} onPhoto={(p) => onPhoto(s.uid, p)} onRemove={() => onRemove(s.uid)} />)}
        </div>
      )}
    </div>
  );
}

function CardEditor({ card }) {
  const update = useUpdateObservation();
  const del = useDeleteObservation();
  const [seq, setSeq] = useState(String(card.seq ?? 1));
  const [duration, setDuration] = useState(card.duration_label || "");
  const [prefix, setPrefix] = useState(card.prefix ?? "RD-");
  const [samples, setSamples] = useState(() => withUid(card.samples));
  const [newCode, setNewCode] = useState("");
  const [newType, setNewType] = useState("S");

  const sList = samples.filter((s) => s.type === "S");
  const dList = samples.filter((s) => s.type === "D");

  function addSample() {
    const code = newCode.trim();
    if (!code) { toast.error("Isi kode sample dulu."); return; }
    setSamples((prev) => [...prev, { uid: nextUid(), code, type: newType, photo_path: null }]);
    setNewCode("");
  }
  const setPhoto = (uid, path) => setSamples((prev) => prev.map((s) => (s.uid === uid ? { ...s, photo_path: path } : s)));
  const removeSample = (uid) => setSamples((prev) => prev.filter((s) => s.uid !== uid));

  async function save() {
    const body = {
      seq: Number(seq) || 1,
      duration_label: duration.trim(),
      prefix,
      samples: samples.map((s) => ({ code: s.code, type: s.type, photo_path: s.photo_path })),
    };
    try { await update.mutateAsync({ id: card.id, body }); toast.success("Kartu pengamatan tersimpan."); }
    catch (e) { toast.error(String(e?.message || "Gagal menyimpan").slice(0, 120)); }
  }
  async function remove() {
    if (!window.confirm("Hapus kartu pengamatan ini?")) return;
    try { await del.mutateAsync(card.id); toast.success("Kartu dihapus."); }
    catch (e) { toast.error(String(e?.message || "Gagal menghapus").slice(0, 120)); }
  }

  const inputCls = "h-10 rounded-md border border-zinc-700 bg-zinc-900 px-3 font-mono text-sm text-zinc-50 outline-none focus:border-amber-500";

  return (
    <Card data-testid={`obs-card-${card.id}`}>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex w-24 flex-col gap-1"><span className="font-mono text-[10px] text-zinc-400">No. Urut</span>
          <input type="number" min={1} value={seq} onChange={(e) => setSeq(e.target.value)} className={inputCls} data-testid="obs-seq" /></label>
        <label className="flex flex-1 flex-col gap-1"><span className="font-mono text-[10px] text-zinc-400">Durasi Pengamatan</span>
          <input value={duration} onChange={(e) => setDuration(e.target.value)} placeholder="contoh: 6 Jam" list="obs-durations" className={inputCls} data-testid="obs-duration" /></label>
        <label className="flex w-28 flex-col gap-1"><span className="font-mono text-[10px] text-zinc-400">Prefix Kode</span>
          <input value={prefix} onChange={(e) => setPrefix(e.target.value)} placeholder="RD-" className={inputCls} data-testid="obs-prefix" /></label>
        <datalist id="obs-durations"><option value="6 Jam" /><option value="24 Jam" /><option value="48 Jam" /><option value="72 Jam" /></datalist>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-2 rounded-lg border border-zinc-700 bg-zinc-900/60 p-3">
        <label className="flex flex-1 flex-col gap-1"><span className="font-mono text-[10px] text-zinc-400">Kode Sample</span>
          <input value={newCode} onChange={(e) => setNewCode(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSample(); } }} placeholder="contoh: 251362" className={inputCls} data-testid="obs-new-code" /></label>
        <div className="flex flex-col gap-1"><span className="font-mono text-[10px] text-zinc-400">Tipe</span>
          <div className="flex rounded-md border border-zinc-700 bg-zinc-950 p-0.5" data-testid="obs-new-type">
            {["S", "D"].map((t) => <button key={t} type="button" onClick={() => setNewType(t)} data-testid={`obs-new-type-${t}`} className={`rounded px-3 py-1.5 font-mono text-xs font-bold ${newType === t ? "bg-amber-500 text-zinc-950" : "text-zinc-400 hover:text-zinc-100"}`}>{t}</button>)}
          </div>
        </div>
        <button type="button" onClick={addSample} data-testid="obs-add-sample" className="flex h-10 items-center gap-1 rounded-md bg-amber-500 px-4 font-mono text-xs font-bold tracking-widest text-zinc-950 hover:bg-amber-400"><Plus className="h-4 w-4" />TAMBAH</button>
      </div>

      <div className="mt-4 flex flex-col gap-4">
        <Group title="S" prefix={prefix} list={sList} onPhoto={setPhoto} onRemove={removeSample} />
        <Group title="D" prefix={prefix} list={dList} onPhoto={setPhoto} onRemove={removeSample} />
      </div>

      <div className="mt-4 flex gap-2 border-t border-zinc-700 pt-3">
        <button type="button" onClick={save} disabled={update.isPending} data-testid="obs-save" className="flex flex-1 items-center justify-center gap-2 rounded-md bg-amber-500 py-2.5 font-mono text-xs font-bold tracking-widest text-zinc-950 hover:bg-amber-400 disabled:opacity-50"><Save className="h-4 w-4" />{update.isPending ? "MENYIMPAN…" : "SIMPAN KARTU"}</button>
        <button type="button" onClick={remove} disabled={del.isPending} data-testid="obs-delete" className="flex items-center justify-center gap-1 rounded-md border border-red-700/60 px-4 font-mono text-xs text-red-400 hover:bg-red-500/10"><Trash2 className="h-4 w-4" />HAPUS</button>
      </div>
    </Card>
  );
}

export default function SaltObservations() {
  const { data, isLoading } = useObservations();
  const create = useCreateObservation();
  const [exporting, setExporting] = useState(false);
  const cards = data || [];

  async function addCard() {
    const nextSeq = cards.reduce((m, c) => Math.max(m, c.seq || 0), 0) + 1;
    try { await create.mutateAsync({ seq: nextSeq, duration_label: "", prefix: "RD-", samples: [] }); toast.success("Kartu baru ditambahkan."); }
    catch (e) { toast.error(String(e?.message || "Gagal membuat kartu").slice(0, 120)); }
  }
  async function exportPdf() {
    if (!cards.length) { toast.info("Belum ada kartu untuk diexport."); return; }
    setExporting(true);
    try { printHtmlOnWeb(await buildObservationsHtml(cards)); toast.success("Menyiapkan PDF — pilih \"Save as PDF\" di dialog print."); }
    catch (e) { toast.error(String(e?.message || "Gagal export PDF").slice(0, 120)); }
    finally { setExporting(false); }
  }

  return (
    <div className="flex flex-col gap-4 pb-16 animate-fade-up" data-testid="salt-observations">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.15em] text-amber-400"><ClipboardList className="h-4 w-4" /> KARTU PENGAMATAN</div>
        <div className="ml-auto flex gap-2">
          <button type="button" onClick={addCard} disabled={create.isPending} data-testid="obs-add-card" className="flex h-10 items-center gap-2 rounded-md bg-amber-500 px-4 font-mono text-xs font-bold tracking-widest text-zinc-950 hover:bg-amber-400 disabled:opacity-50"><Plus className="h-4 w-4" />KARTU BARU</button>
          <button type="button" onClick={exportPdf} disabled={exporting || !cards.length} data-testid="obs-export-pdf" className="flex h-10 items-center gap-2 rounded-md border border-amber-500/60 px-4 font-mono text-xs font-bold tracking-widest text-amber-400 hover:bg-amber-500/10 disabled:opacity-50">{exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}EXPORT PDF</button>
        </div>
      </div>

      {isLoading ? <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-amber-400" /></div>
        : cards.length === 0 ? <div className="py-16 text-center font-mono text-xs text-zinc-500" data-testid="obs-empty">Belum ada kartu pengamatan. Klik tombol KARTU BARU untuk membuat.</div>
          : <div className="flex flex-col gap-4">{cards.map((c) => <CardEditor key={c.id} card={c} />)}</div>}
    </div>
  );
}
