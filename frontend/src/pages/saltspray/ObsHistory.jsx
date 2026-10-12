import React, { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Archive, CalendarClock, ChevronRight, FlaskConical, Layers, Loader2, Search, Timer, Trophy, User } from "lucide-react";
import { fileUrl } from "@/lib/saltspray/api";
import { fmtDateTime } from "@/lib/kht/format";
import { fmtHour } from "@/lib/saltspray/obsReport";
import { fmtStart, SAMPLE_COLORS, useSeriesList } from "@/lib/saltspray/series";

function Stat({ icon: Icon, label, value, accent = "text-amber-400", testId }) {
  return (
    <div className="relative overflow-hidden rounded-xl border border-zinc-700 bg-gradient-to-br from-zinc-900 to-zinc-950 p-4" data-testid={testId}>
      <Icon className={`absolute -right-2 -top-2 h-16 w-16 opacity-10 ${accent}`} />
      <div className="font-mono text-[9px] tracking-[0.2em] text-zinc-500">{label}</div>
      <div className={`mt-1 font-mono text-2xl font-bold ${accent}`}>{value}</div>
    </div>
  );
}

export function SeriesStatus({ s, big }) {
  return s.all_reached ? (
    <span className={`inline-flex items-center gap-1 rounded-full bg-red-500/15 font-mono font-bold tracking-wider text-red-400 ring-1 ring-red-500/40 ${big ? "px-3 py-1 text-[11px]" : "px-2 py-0.5 text-[9px]"}`}><Trophy className="h-3 w-3" />100% TERCAPAI</span>
  ) : (
    <span className={`inline-flex items-center gap-1 rounded-full bg-orange-500/15 font-mono font-bold tracking-wider text-orange-300 ring-1 ring-orange-500/40 ${big ? "px-3 py-1 text-[11px]" : "px-2 py-0.5 text-[9px]"}`}>DIHENTIKAN</span>
  );
}

export const seriesDuration = (s) => (s.all_reached ? `${fmtHour(s.duration_hours)} Jam` : s.max_hours != null ? `${fmtHour(s.max_hours)} Jam*` : "–");

export default function ObsHistory() {
  const { data, isLoading } = useSeriesList();
  const [q, setQ] = useState("");
  const list = useMemo(() => data || [], [data]);
  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return list;
    return list.filter((s) => [s.header?.operator, s.note, `seri ${s.number}`, ...s.samples.map((x) => x.code)].join(" ").toLowerCase().includes(t));
  }, [list, q]);
  const done = list.filter((s) => s.all_reached);
  const avg = done.length ? Math.round(done.reduce((a, s) => a + (s.duration_hours || 0), 0) / done.length) : null;
  const totalSamples = list.reduce((a, s) => a + s.samples.length, 0);

  if (isLoading) return <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-amber-400" /></div>;

  return (
    <div className="flex flex-col gap-4 pb-16 animate-fade-up" data-testid="obs-history">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat icon={Archive} label="TOTAL SERI" value={list.length} testId="obs-history-stat-total" />
        <Stat icon={FlaskConical} label="TOTAL SAMPLE" value={totalSamples} accent="text-cyan-400" testId="obs-history-stat-samples" />
        <Stat icon={Trophy} label="100% / DIHENTIKAN" value={`${done.length} / ${list.length - done.length}`} accent="text-red-400" testId="obs-history-stat-done" />
        <Stat icon={Timer} label="RATA-RATA DURATION" value={avg != null ? `${avg} Jam` : "–"} accent="text-emerald-400" testId="obs-history-stat-avg" />
      </div>

      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cari kode sample, operator, catatan…" className="h-11 w-full rounded-lg border border-zinc-700 bg-zinc-900 pl-10 pr-3 font-mono text-sm text-zinc-100 outline-none placeholder:text-zinc-600 focus:border-amber-500" data-testid="obs-history-search" />
      </div>

      {list.length === 0 ? (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-zinc-700 py-16 text-center" data-testid="obs-history-empty">
          <Archive className="h-10 w-10 text-zinc-600" />
          <div className="font-mono text-xs text-zinc-500">Belum ada seri di history.<br />Seri tersimpan setelah klik «Selesaikan & Simpan ke History» di Kartu Pengamatan.</div>
          <Link to="/salt-spray/observations" className="rounded-md border border-amber-500/60 px-4 py-2 font-mono text-xs text-amber-400 hover:bg-amber-500/10">Ke Kartu Pengamatan</Link>
        </div>
      ) : filtered.length === 0 ? (
        <div className="py-10 text-center font-mono text-xs text-zinc-500" data-testid="obs-history-noresult">Tidak ada seri yang cocok dengan «{q}».</div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((s) => (
            <Link key={s.id} to={`/salt-spray/observation-history/${s.id}`} data-testid={`obs-series-${s.id}`} className="group overflow-hidden rounded-xl border border-zinc-700 bg-zinc-900 transition hover:-translate-y-0.5 hover:border-amber-500/60 hover:shadow-xl hover:shadow-amber-900/20">
              <div className="relative h-36 overflow-hidden bg-zinc-950">
                {s.cover_photo_path && <img src={fileUrl(s.cover_photo_path, 900)} alt="cover" className="h-full w-full object-cover opacity-80 transition duration-500 group-hover:scale-105 group-hover:opacity-100" />}
                <div className="absolute inset-0 bg-gradient-to-t from-zinc-900 via-zinc-900/30 to-transparent" />
                <div className="absolute left-3 top-3 rounded-md bg-zinc-950/80 px-2 py-1 font-mono text-[11px] font-bold tracking-widest text-amber-400 ring-1 ring-amber-500/40">SERI #{s.number}</div>
                <div className="absolute right-3 top-3"><SeriesStatus s={s} /></div>
                <div className="absolute bottom-2 left-3 right-3 flex items-end justify-between">
                  <div><div className="font-mono text-[9px] tracking-widest text-zinc-400">DURATION</div><div className={`font-mono text-2xl font-bold ${s.all_reached ? "text-red-400" : "text-orange-300"}`}>{seriesDuration(s)}</div></div>
                  <ChevronRight className="h-5 w-5 text-zinc-400 transition group-hover:translate-x-1 group-hover:text-amber-400" />
                </div>
              </div>
              <div className="flex flex-col gap-2 p-4">
                <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-zinc-300">
                  <span className="flex items-center gap-1"><CalendarClock className="h-3.5 w-3.5 text-zinc-500" />{fmtStart(s.header)}</span>
                  <span className="flex items-center gap-1"><User className="h-3.5 w-3.5 text-zinc-500" />{s.header?.operator || "-"}</span>
                  <span className="flex items-center gap-1"><Layers className="h-3.5 w-3.5 text-zinc-500" />{s.card_count} kartu</span>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {s.samples.map((x, i) => (
                    <span key={x.code} className="inline-flex items-center gap-1 rounded border border-zinc-700 bg-zinc-950 px-1.5 py-0.5 font-mono text-[10px] text-zinc-200">
                      <span className="h-1.5 w-1.5 rounded-full" style={{ background: SAMPLE_COLORS[i % SAMPLE_COLORS.length] }} />{x.code}
                      <span className={x.last_pct >= 100 ? "font-bold text-red-400" : "text-orange-300"}>{Math.round(x.last_pct)}%</span>
                    </span>
                  ))}
                </div>
                <div className="font-mono text-[10px] text-zinc-500">Diarsipkan {fmtDateTime(s.completed_at)}</div>
              </div>
            </Link>
          ))}
        </div>
      )}
      {list.some((s) => !s.all_reached) && <div className="font-mono text-[10px] text-zinc-600">* jam pengamatan terakhir (uji dihentikan sebelum semua sample 100%)</div>}
    </div>
  );
}
