import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Archive, CheckCircle2, Loader2, Trophy, X } from "lucide-react";
import { toast } from "sonner";
import { useCompleteSeries } from "@/lib/saltspray/series";
import { fmtHour } from "@/lib/saltspray/obsReport";

export function Modal({ open, onClose, children, testId, wide }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") onClose?.(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm" onClick={onClose} data-testid={testId}>
      <div className={`relative max-h-[92vh] w-full overflow-y-auto rounded-2xl border border-zinc-700 bg-zinc-900 p-5 shadow-2xl shadow-black/60 ${wide ? "max-w-5xl" : "max-w-lg"}`} onClick={(e) => e.stopPropagation()}>
        <button type="button" onClick={onClose} className="absolute right-3 top-3 rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-white" data-testid={`${testId}-close`}><X className="h-4 w-4" /></button>
        {children}
      </div>
    </div>,
    document.body,
  );
}

export const latestPct = (row) => {
  for (let i = row.cells.length - 1; i >= 0; i -= 1) if (row.cells[i]) return row.cells[i].value;
  return 0;
};

function SampleBars({ report }) {
  return (
    <div className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
      {report.rows.map((r) => {
        const v = latestPct(r);
        return (
          <div key={r.code} className="min-w-0" data-testid={`series-bar-${r.code}`}>
            <div className="flex justify-between gap-2 font-mono text-[10px]"><span className="truncate text-zinc-300">{r.code}</span><span className={v >= 100 ? "font-bold text-red-400" : "text-zinc-400"}>{v}%</span></div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-zinc-800">
              <div className={`h-full rounded-full transition-all duration-700 ${v >= 100 ? "bg-gradient-to-r from-red-600 to-red-400" : "bg-gradient-to-r from-amber-600 to-amber-400"}`} style={{ width: `${Math.max(2, v)}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function SeriesCompletePanel({ report, cardCount }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const complete = useCompleteSeries();
  const navigate = useNavigate();
  if (!cardCount || !report.rows.length) return null;
  const done = report.allReached;
  const pending = report.rows.filter((r) => latestPct(r) < 100);
  const reachedCount = report.rows.length - pending.length;

  async function confirm() {
    try {
      const s = await complete.mutateAsync({ force: !done, note });
      setOpen(false);
      setNote("");
      toast.success(`Seri #${s.number} tersimpan di History Pengamatan. Kartu Pengamatan siap untuk uji baru.`, {
        action: { label: "Lihat", onClick: () => navigate(`/salt-spray/observation-history/${s.id}`) },
      });
    } catch (e) { toast.error(String(e?.message || "Gagal mengarsipkan").slice(0, 160)); }
  }

  return (
    <>
      {done ? (
        <section className="relative overflow-hidden rounded-xl border border-red-500/50 bg-gradient-to-br from-red-950/80 via-zinc-900 to-amber-950/40 p-5" data-testid="series-complete-banner">
          <div className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-red-500/20 blur-3xl" />
          <div className="relative flex flex-wrap items-center gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-red-500/20 ring-1 ring-red-500/50"><Trophy className="h-6 w-6 text-red-400" /></div>
            <div className="min-w-0 flex-1">
              <div className="font-mono text-[10px] tracking-[0.2em] text-red-300">UJI SELESAI</div>
              <div className="text-lg font-bold text-white">Semua sample mencapai 100% korosi</div>
              <div className="font-mono text-xs text-zinc-300">Duration <b className="text-red-400">{fmtHour(report.doneHour)} Jam</b> · {report.rows.length} sample · {cardCount} kartu</div>
            </div>
            <button type="button" onClick={() => setOpen(true)} data-testid="series-complete-btn" className="flex items-center gap-2 rounded-lg bg-gradient-to-r from-red-600 to-amber-500 px-5 py-3 font-mono text-xs font-bold tracking-widest text-white shadow-lg shadow-red-900/40 transition hover:brightness-110"><Archive className="h-4 w-4" />SELESAIKAN & SIMPAN KE HISTORY</button>
          </div>
        </section>
      ) : (
        <section className="rounded-xl border border-zinc-700 bg-zinc-900 p-5" data-testid="series-progress">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="font-mono text-[11px] tracking-[0.15em] text-amber-400">PROGRESS SERI</span>
            <span className="font-mono text-[10px] text-zinc-500">{reachedCount}/{report.rows.length} sample sudah 100%</span>
            <button type="button" onClick={() => setOpen(true)} data-testid="series-stop-btn" className="ml-auto flex items-center gap-1.5 rounded-md border border-zinc-600 px-3 py-1.5 font-mono text-[11px] text-zinc-300 hover:border-orange-500/60 hover:text-orange-300"><Archive className="h-3.5 w-3.5" />Hentikan & Arsipkan Seri</button>
          </div>
          <SampleBars report={report} />
        </section>
      )}

      <Modal open={open} onClose={() => !complete.isPending && setOpen(false)} testId="series-confirm">
        <div className="flex items-center gap-3">
          {done ? <CheckCircle2 className="h-7 w-7 text-emerald-400" /> : <AlertTriangle className="h-7 w-7 text-orange-400" />}
          <div>
            <div className="text-base font-bold text-white">{done ? "Simpan seri ke History?" : "Belum semua sample 100%"}</div>
            <div className="font-mono text-[11px] text-zinc-400">Header, tabel report & semua foto kartu akan diarsipkan.</div>
          </div>
        </div>
        {!done && (
          <div className="mt-4 rounded-lg border border-orange-500/40 bg-orange-500/10 p-3" data-testid="series-confirm-warning">
            <div className="font-mono text-[11px] font-bold text-orange-300">Uji akan dicatat sebagai DIHENTIKAN. Sample yang belum 100%:</div>
            <ul className="mt-2 space-y-1">{pending.map((r) => <li key={r.code} className="flex justify-between font-mono text-[11px] text-zinc-200"><span>{r.code}</span><span className="text-orange-300">{latestPct(r)}%</span></li>)}</ul>
          </div>
        )}
        <div className="mt-4 grid grid-cols-3 gap-2 text-center">
          {[["Sample", report.rows.length], ["Kartu", cardCount], ["Duration", done ? `${fmtHour(report.doneHour)} Jam` : "–"]].map(([k, v]) => (
            <div key={k} className="rounded-lg border border-zinc-700 bg-zinc-950 p-2"><div className="font-mono text-[9px] tracking-widest text-zinc-500">{k.toUpperCase()}</div><div className="font-mono text-sm font-bold text-white">{v}</div></div>
          ))}
        </div>
        <label className="mt-4 flex flex-col gap-1"><span className="font-mono text-[10px] text-zinc-400">Catatan (opsional)</span>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder={done ? "mis. hasil sesuai spesifikasi" : "alasan uji dihentikan"} className="rounded-md border border-zinc-700 bg-zinc-950 p-2 font-mono text-xs text-zinc-100 outline-none focus:border-amber-500" data-testid="series-confirm-note" /></label>
        <p className="mt-3 font-mono text-[10px] leading-4 text-zinc-500">Setelah disimpan, Kartu Pengamatan dikosongkan. Kondisi chamber (posisi, pressure, water, temperatur, pH) dibawa ke seri baru; Operator, Jam & Tanggal Mulai dan Plat Grinding dikosongkan.</p>
        <div className="mt-4 flex gap-2">
          <button type="button" onClick={() => setOpen(false)} disabled={complete.isPending} className="flex-1 rounded-md border border-zinc-700 py-2.5 font-mono text-xs text-zinc-300 hover:bg-zinc-800" data-testid="series-confirm-cancel">BATAL</button>
          <button type="button" onClick={confirm} disabled={complete.isPending} data-testid="series-confirm-ok" className={`flex flex-[2] items-center justify-center gap-2 rounded-md py-2.5 font-mono text-xs font-bold tracking-widest text-white disabled:opacity-60 ${done ? "bg-gradient-to-r from-red-600 to-amber-500" : "bg-orange-600 hover:bg-orange-500"}`}>
            {complete.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Archive className="h-4 w-4" />}{done ? "SIMPAN KE HISTORY" : "TETAP ARSIPKAN"}
          </button>
        </div>
      </Modal>
    </>
  );
}
