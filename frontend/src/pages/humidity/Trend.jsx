import React from "react";
import { Link } from "react-router-dom";
import { Loader2, TrendingUp } from "lucide-react";
import { useHumidityTrend, HUM_GRADES } from "@/lib/humidity/api";
import { Card } from "@/components/kht/ui";
import { fmtDate } from "@/lib/kht/format";

export default function HumidityTrend() {
  const { data, isLoading } = useHumidityTrend(); const points = data || []; const max = Math.max(1, ...points.map((p) => p.rusted_box_count));
  if (isLoading) return <div className="flex justify-center py-16"><Loader2 className="h-6 w-6 animate-spin text-amber-400" /></div>;
  if (!points.length) return <div className="py-16 text-center font-mono text-xs text-zinc-500" data-testid="humidity-trend-empty">Data belum cukup untuk tren.</div>;
  return <div className="flex flex-col gap-4 animate-fade-up" data-testid="humidity-trend"><Card><div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.15em] text-amber-400"><TrendingUp className="h-4 w-4" /> RUSTED BOX TREND / 100</div><div className="mt-5 flex h-44 items-end gap-2 border-b border-l border-zinc-700 px-2 pb-0">{points.map((p) => <div key={p.id} className="group flex flex-1 flex-col items-center justify-end gap-1"><span className="font-mono text-[9px] text-zinc-400 opacity-0 transition-opacity group-hover:opacity-100">{p.rusted_box_count}</span><div className="w-full max-w-10 rounded-t bg-amber-500 transition-all" style={{ height: `${Math.max(5, (p.rusted_box_count / max) * 130)}px` }} title={`${p.rusted_box_count} kotak`} /></div>)}</div><div className="mt-2 flex justify-between font-mono text-[9px] text-zinc-500"><span>AWAL</span><span>TERBARU</span></div></Card><Card><div className="font-mono text-[11px] tracking-[0.15em] text-amber-400">DATA POINTS</div><div className="mt-2">{points.slice().reverse().map((p, index) => <Link key={p.id} to={`/humidity-cabinet/result/${p.id}`} data-testid={`humidity-trend-point-${p.id}`} className={`flex items-center gap-3 py-3 hover:bg-zinc-800/40 ${index ? "border-t border-zinc-700" : ""}`}><div className="flex-1"><div className="font-mono text-[13px] font-bold text-zinc-50">{p.sample_id || "—"}</div><div className="font-mono text-[10px] text-zinc-500">{fmtDate(p.created_at)}</div></div><span className="font-mono text-sm font-bold" style={{ color: HUM_GRADES[p.grade]?.color }}>{p.rusted_box_count}/100 · Grade {p.grade}</span></Link>)}</div></Card></div>;
}
