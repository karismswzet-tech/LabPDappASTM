import React, { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, FileDown, Loader2, RotateCcw, StickyNote, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/kht/ui";
import { fileUrl } from "@/lib/saltspray/api";
import { fmtDateTime } from "@/lib/kht/format";
import { buildReport } from "@/lib/saltspray/obsReport";
import { buildObservationsHtml, printHtmlOnWeb } from "@/lib/saltspray/observationsPdf";
import { SAMPLE_COLORS, useDeleteSeries, useReopenSeries, useSeries } from "@/lib/saltspray/series";
import { ObsHeaderView, ObsReportTable, RustProgressChart } from "@/components/saltspray/ObsReport";
import { Modal } from "@/components/saltspray/SeriesComplete";
import { seriesDuration, SeriesStatus } from "@/pages/saltspray/ObsHistory";

const PLATE_COLORS = ["#F59E0B", "#22D3EE", "#A78BFA", "#34D399"];

function PhotoWithBoxes({ card, big }) {
  return (
    <div className="relative inline-block max-w-full">
      <img src={fileUrl(card.photo_path, big ? 2000 : 900)} alt={card.duration_label} className={`block max-w-full object-contain ${big ? "max-h-[70vh]" : ""}`} />
      {(card.plates || []).map((p, i) => p.bbox && (
        <div key={i} className="pointer-events-none absolute border-2" style={{ left: `${p.bbox[0] * 100}%`, top: `${p.bbox[1] * 100}%`, width: `${p.bbox[2] * 100}%`, height: `${p.bbox[3] * 100}%`, borderColor: PLATE_COLORS[i] }}>
          <span className="absolute left-0 top-0 px-1 font-mono text-[9px] font-bold text-zinc-950" style={{ background: PLATE_COLORS[i] }}>{i + 1}</span>
        </div>
      ))}
    </div>
  );
}

export default function ObsHistoryDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: s, isLoading, error } = useSeries(id);
  const del = useDeleteSeries();
  const reopen = useReopenSeries();
  const [lightbox, setLightbox] = useState(null);
  const [confirm, setConfirm] = useState(null); // 'delete' | 'reopen'
  const [exporting, setExporting] = useState(false);
  const cards = useMemo(() => s?.cards || [], [s]);
  const report = useMemo(() => buildReport(cards), [cards]);

  if (isLoading) return <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-amber-400" /></div>;
  if (error || !s) return <div className="py-16 text-center font-mono text-xs text-zinc-500" data-testid="obs-series-notfound">Seri tidak ditemukan. <Link to="/salt-spray/observation-history" className="text-amber-400 underline">Kembali</Link></div>;

  async function exportPdf() {
    setExporting(true);
    try { printHtmlOnWeb(await buildObservationsHtml(cards, s.header, report)); toast.success("Menyiapkan PDF — pilih \"Save as PDF\" di dialog print."); }
    catch (e) { toast.error(String(e?.message || "Gagal export PDF").slice(0, 120)); }
    finally { setExporting(false); }
  }
  async function doConfirm() {
    try {
      if (confirm === "delete") { await del.mutateAsync(s.id); toast.success(`Seri #${s.number} dihapus.`); navigate("/salt-spray/observation-history"); }
      else { await reopen.mutateAsync(s.id); toast.success(`Seri #${s.number} dibuka kembali di Kartu Pengamatan.`); navigate("/salt-spray/observations"); }
    } catch (e) { toast.error(String(e?.message || "Gagal").slice(0, 180)); setConfirm(null); }
  }
  const pending = del.isPending || reopen.isPending;

  return (
    <div className="flex flex-col gap-4 pb-16 animate-fade-up" data-testid="obs-series-detail">
      <section className="relative overflow-hidden rounded-xl border border-zinc-700 bg-gradient-to-br from-zinc-900 via-zinc-900 to-amber-950/30 p-5">
        <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-amber-500/10 blur-3xl" />
        <Link to="/salt-spray/observation-history" className="relative inline-flex items-center gap-1 font-mono text-[11px] text-zinc-400 hover:text-amber-400" data-testid="obs-series-back"><ArrowLeft className="h-3.5 w-3.5" />History Pengamatan</Link>
        <div className="relative mt-2 flex flex-wrap items-end gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2"><h2 className="font-mono text-2xl font-bold text-white" data-testid="obs-series-title">SERI #{s.number}</h2><SeriesStatus s={s} big /></div>
            <div className="mt-1 font-mono text-xs text-zinc-400">Duration <b className={s.all_reached ? "text-red-400" : "text-orange-300"}>{seriesDuration(s)}</b> · {s.samples.length} sample · {s.card_count} kartu · diarsipkan {fmtDateTime(s.completed_at)}</div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={exportPdf} disabled={exporting} data-testid="obs-series-export" className="flex h-10 items-center gap-2 rounded-md bg-amber-500 px-4 font-mono text-xs font-bold tracking-widest text-zinc-950 hover:bg-amber-400 disabled:opacity-50">{exporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}EXPORT PDF</button>
            <button type="button" onClick={() => setConfirm("reopen")} data-testid="obs-series-reopen" className="flex h-10 items-center gap-2 rounded-md border border-cyan-500/50 px-4 font-mono text-xs font-bold tracking-widest text-cyan-300 hover:bg-cyan-500/10"><RotateCcw className="h-4 w-4" />BUKA KEMBALI</button>
            <button type="button" onClick={() => setConfirm("delete")} data-testid="obs-series-delete" className="flex h-10 items-center gap-2 rounded-md border border-red-700/60 px-4 font-mono text-xs text-red-400 hover:bg-red-500/10"><Trash2 className="h-4 w-4" />HAPUS</button>
          </div>
        </div>
        {s.note && <div className="relative mt-3 flex items-start gap-2 rounded-lg border border-zinc-700 bg-zinc-950/60 p-3 font-mono text-xs text-zinc-300" data-testid="obs-series-note"><StickyNote className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />{s.note}</div>}
      </section>

      <ObsHeaderView header={s.header} report={report} durationLabel={s.all_reached ? undefined : `Dihentikan di ${seriesDuration(s).replace("*", "")} (belum semua sample 100%)`} />
      <ObsReportTable report={report} />
      {report.rows.length > 0 && <RustProgressChart report={report} colors={SAMPLE_COLORS} />}

      <Card data-testid="obs-series-gallery">
        <div className="mb-3 font-mono text-[11px] tracking-[0.15em] text-amber-400">FOTO KARTU PENGAMATAN · {cards.length}</div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {cards.map((c) => (
            <button type="button" key={c.id} onClick={() => setLightbox(c)} data-testid={`obs-series-photo-${c.id}`} className="group overflow-hidden rounded-lg border border-zinc-700 bg-zinc-950 text-left transition hover:border-amber-500/60">
              <div className="flex justify-center bg-black">{c.photo_path && <PhotoWithBoxes card={c} />}</div>
              <div className="flex items-center justify-between gap-2 p-2">
                <span className="font-mono text-xs font-bold text-zinc-100">{c.seq}. Pengamatan {c.duration_label}</span>
                <span className="font-mono text-[10px] text-zinc-500 group-hover:text-amber-400">perbesar</span>
              </div>
            </button>
          ))}
        </div>
      </Card>

      <Modal open={!!lightbox} onClose={() => setLightbox(null)} testId="obs-series-lightbox" wide>
        {lightbox && (
          <div>
            <div className="mb-3 font-mono text-sm font-bold text-white">{lightbox.seq}. Pengamatan {lightbox.duration_label}</div>
            <div className="flex justify-center rounded-lg bg-black"><PhotoWithBoxes card={lightbox} big /></div>
            <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
              {(lightbox.plates || []).map((p, i) => {
                const n = (p.grid_boxes || []).filter(Boolean).length;
                return (
                  <div key={i} className="rounded-lg border border-zinc-700 bg-zinc-950 p-2">
                    <div className="flex items-center gap-1.5 font-mono text-[10px] text-zinc-400"><span className="flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-bold text-zinc-950" style={{ background: PLATE_COLORS[i] }}>{i + 1}</span>SAMPLE {i + 1}</div>
                    <div className="truncate font-mono text-xs font-bold text-zinc-100">{p.code}</div>
                    <div className={`font-mono text-lg font-bold ${n >= 100 ? "text-red-500" : "text-zinc-100"}`}>{n}%</div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </Modal>

      <Modal open={!!confirm} onClose={() => !pending && setConfirm(null)} testId="obs-series-confirm">
        <div className="text-base font-bold text-white">{confirm === "delete" ? `Hapus Seri #${s.number}?` : `Buka kembali Seri #${s.number}?`}</div>
        <p className="mt-2 font-mono text-xs leading-5 text-zinc-400">{confirm === "delete" ? "Seri beserta semua kartu & fotonya akan dihapus dari history." : "Semua kartu & header seri ini dikembalikan ke Kartu Pengamatan agar bisa dilanjutkan/dikoreksi. Hanya bisa jika Kartu Pengamatan sedang kosong."}</p>
        <div className="mt-4 flex gap-2">
          <button type="button" onClick={() => setConfirm(null)} disabled={pending} className="flex-1 rounded-md border border-zinc-700 py-2.5 font-mono text-xs text-zinc-300 hover:bg-zinc-800" data-testid="obs-series-confirm-cancel">BATAL</button>
          <button type="button" onClick={doConfirm} disabled={pending} data-testid="obs-series-confirm-ok" className={`flex flex-[2] items-center justify-center gap-2 rounded-md py-2.5 font-mono text-xs font-bold tracking-widest text-white disabled:opacity-60 ${confirm === "delete" ? "bg-red-600 hover:bg-red-500" : "bg-cyan-600 hover:bg-cyan-500"}`}>
            {pending && <Loader2 className="h-4 w-4 animate-spin" />}{confirm === "delete" ? "HAPUS" : "BUKA KEMBALI"}
          </button>
        </div>
      </Modal>
    </div>
  );
}
