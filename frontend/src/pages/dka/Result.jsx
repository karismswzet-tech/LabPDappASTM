import React, { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { FileDown, Loader2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { DKA_CATEGORIES, DKA_FALLBACK_COLORS, fileUrl, textOnColor, useDeleteDka, useDkaScale, useDkaTest, useUpdateDka } from "@/lib/dka/api";
import { fmtDateTime } from "@/lib/kht/format";
import { buildDkaSingleHtml, printHtmlOnWeb } from "@/lib/dka/pdf";
import { Card, InfoRow, KhtHeader } from "@/components/kht/ui";
import { BlueBtn } from "@/components/dka/ui";

const SampleEditor = ({ sample, colorFor, busy, onRating, onSaveId }) => {
  const [sid, setSid] = useState(sample.sample_id);
  return (
    <Card data-testid={`dka-editor-${sample.index}`}>
      <div className="flex gap-4">
        <img src={fileUrl(sample.crop_path || "", 400)} alt={`sample ${sample.index}`} className="h-36 w-28 shrink-0 rounded-lg border border-zinc-700 bg-zinc-800 object-cover" />
        <div className="flex flex-1 flex-col gap-1">
          <span className="font-mono text-[10px] tracking-widest text-blue-400">SAMPLE #{sample.index}</span>
          <span className="mt-1 font-mono text-[11px] text-zinc-300">Sample ID (OCR)</span>
          <input
            data-testid={`dka-sid-${sample.index}`}
            value={sid}
            onChange={(e) => setSid(e.target.value)}
            onBlur={() => onSaveId(sid)}
            onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
            placeholder={`Unknown ${sample.index}`}
            className="h-11 rounded-md border border-zinc-700 bg-zinc-950 px-3 font-mono text-sm font-bold text-zinc-50 outline-none focus:border-blue-500"
          />
          <span className="font-mono text-[10px] text-zinc-500">Confidence {sample.confidence.toFixed(0)}%</span>
        </div>
      </div>
      <div className="mt-4 font-mono text-[11px] text-zinc-300">Rating</div>
      <div className="mt-2 flex flex-wrap gap-2" data-testid={`dka-rating-chips-${sample.index}`}>
        {DKA_CATEGORIES.map((code) => {
          const col = colorFor(code);
          const active = code === sample.rating;
          return (
            <button
              key={code}
              type="button"
              data-testid={`dka-rate-${sample.index}-${code.replace(" ", "-")}`}
              aria-pressed={active}
              disabled={busy}
              onClick={() => onRating(code)}
              className={`rounded-md px-4 py-2 font-mono text-xs font-bold transition-transform ${active ? "scale-105 ring-2 ring-blue-400 ring-offset-2 ring-offset-zinc-900" : "opacity-70 hover:opacity-100"} ${busy ? "opacity-60" : ""}`}
              style={{ backgroundColor: col, color: textOnColor(col) }}
            >
              {code}
            </button>
          );
        })}
      </div>
      {sample.rating_source === "manual" && (
        <div className="mt-3 inline-flex items-center gap-2 rounded border border-amber-500/50 bg-amber-500/10 px-2 py-0.5 font-mono text-[10px] font-bold tracking-wider text-amber-300" data-testid={`dka-manual-badge-${sample.index}`}>
          DIKOREKSI MANUAL{sample.ai_rating ? ` · AI: ${sample.ai_rating}` : ""}
        </div>
      )}
      {!!sample.summary && <p className="mt-3 font-mono text-[12px] leading-5 text-zinc-200" data-testid={`dka-summary-${sample.index}`}>{sample.summary}</p>}
    </Card>
  );
};

export default function DkaResult() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data: rec, isLoading, isError } = useDkaTest(id);
  const { data: scale } = useDkaScale();
  const del = useDeleteDka();
  const update = useUpdateDka();
  const [exporting, setExporting] = useState(false);

  const colorFor = (code) => scale?.categories?.find((c) => c.code === code)?.color ?? DKA_FALLBACK_COLORS[code] ?? "#888";

  async function changeRating(index, code) {
    try {
      await update.mutateAsync({ id: rec.id, changes: { samples: [{ index, rating: code }] } });
    } catch (e) {
      toast.error(String(e?.message || "Gagal menyimpan.").slice(0, 120));
    }
  }

  async function saveSampleId(index, sample_id) {
    const cur = rec.samples.find((s) => s.index === index);
    if (!cur || cur.sample_id === sample_id.trim() || !sample_id.trim()) return;
    try {
      await update.mutateAsync({ id: rec.id, changes: { samples: [{ index, sample_id }] } });
      toast.success("Sample ID tersimpan.");
    } catch (e) {
      toast.error(String(e?.message || "Gagal menyimpan.").slice(0, 120));
    }
  }

  async function exportPdf() {
    setExporting(true);
    try {
      printHtmlOnWeb(await buildDkaSingleHtml(rec));
      toast.success("Menyiapkan PDF batch report…");
    } catch (e) {
      toast.error(`Export PDF gagal: ${String(e?.message || "unknown error").slice(0, 140)}`);
    } finally {
      setExporting(false);
    }
  }

  async function onDelete() {
    try {
      await del.mutateAsync(rec.id);
      toast.success("Batch dihapus");
      navigate("/rating-dka/history");
    } catch {
      toast.error("Gagal menghapus");
    }
  }

  const exportBtn = (
    <button type="button" onClick={exportPdf} disabled={exporting || !rec} data-testid="dka-export-pdf" className="flex h-10 w-10 items-center justify-center rounded-md text-blue-400 hover:bg-zinc-800 disabled:opacity-50">
      {exporting ? <Loader2 className="h-5 w-5 animate-spin" /> : <FileDown className="h-5 w-5" />}
    </button>
  );

  return (
    <div className="min-h-screen bg-zinc-950" data-testid="dka-result-page">
      <KhtHeader title="Batch Result" subtitle={rec?.meta.batch_id || (rec ? rec.id.slice(0, 8) : undefined)} backTo="/rating-dka" right={exportBtn} logo="DKA" accent="blue" />
      <div className="mx-auto max-w-3xl px-4 py-6 lg:px-6">
        {isError ? (
          <div className="flex flex-col items-center gap-4 py-24" data-testid="dka-not-found">
            <p className="font-mono text-[13px] text-zinc-500">Batch tidak ditemukan.</p>
            <BlueBtn onClick={() => navigate("/rating-dka")} data-testid="dka-go-home" className="px-6 py-3 text-[13px]">KEMBALI KE DASHBOARD</BlueBtn>
          </div>
        ) : isLoading || !rec ? (
          <div className="flex justify-center py-24"><Loader2 className="h-6 w-6 animate-spin text-blue-400" /></div>
        ) : (
          <div className="flex flex-col gap-4 animate-fade-up">
            <p className="font-mono text-[11px] text-zinc-300" data-testid="dka-result-hint">{rec.samples.length} tabung terdeteksi (kiri → kanan). Koreksi Sample ID &amp; rating jika perlu.</p>
            {rec.samples.map((s) => (
              <SampleEditor key={`${s.index}-${s.sample_id}`} sample={s} colorFor={colorFor} busy={update.isPending} onRating={(code) => changeRating(s.index, code)} onSaveId={(sid) => saveSampleId(s.index, sid)} />
            ))}
            <Card>
              <div className="font-mono text-[11px] tracking-[0.15em] text-blue-400">BATCH INFORMATION</div>
              <div className="mt-1">
                <InfoRow k="Batch ID" v={rec.meta.batch_id || "—"} />
                <InfoRow k="Product" v={rec.meta.product || "—"} />
                <InfoRow k="Operator" v={rec.meta.operator || "—"} />
                <InfoRow k="Condition" v={`${rec.meta.temperature_c}°C · ${rec.meta.duration_hours}h`} />
                <InfoRow k="Analyzed" v={fmtDateTime(rec.created_at)} />
                <InfoRow k="AI Model" v={rec.ai_model} last />
              </div>
            </Card>
            <BlueBtn onClick={exportPdf} disabled={exporting} data-testid="dka-export-report-btn" className="h-13 py-4 text-sm">
              <FileDown className="h-4 w-4" />EXPORT PDF BATCH REPORT
            </BlueBtn>
            <button type="button" onClick={onDelete} disabled={del.isPending} data-testid="dka-delete-test" className="flex items-center justify-center gap-2 py-3 font-mono text-xs text-red-500 hover:text-red-400">
              <Trash2 className="h-4 w-4" />Hapus batch ini
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
