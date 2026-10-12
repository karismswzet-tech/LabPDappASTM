import React, { useEffect, useState } from "react";
import { FileSpreadsheet, Loader2, Save, Timer } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/kht/ui";
import { useObsHeader, useSaveObsHeader } from "@/lib/saltspray/observations";
import { durationText, fmtHour, HEADER_DEFAULTS } from "@/lib/saltspray/obsReport";

const inputCls = "h-10 w-full rounded-md border border-zinc-700 bg-zinc-900 px-3 font-mono text-sm text-zinc-50 outline-none placeholder:text-zinc-600 focus:border-amber-500";

const Field = ({ label, children, wide }) => (
  <label className={`flex flex-col gap-1 ${wide ? "sm:col-span-2" : ""}`}>
    <span className="font-mono text-[10px] tracking-wider text-zinc-400">{label}</span>
    {children}
  </label>
);

export function ObsHeaderForm({ report }) {
  const { data, isLoading } = useObsHeader();
  const save = useSaveObsHeader();
  const [f, setF] = useState(HEADER_DEFAULTS);
  useEffect(() => { if (data) setF({ ...HEADER_DEFAULTS, ...data }); }, [data]);
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const txt = (k, testId, placeholder) => <input value={f[k] ?? ""} onChange={set(k)} placeholder={placeholder || HEADER_DEFAULTS[k]} className={inputCls} data-testid={testId} />;

  async function submit() {
    try { await save.mutateAsync(f); toast.success("Header data pengujian tersimpan."); }
    catch (e) { toast.error(String(e?.message || "Gagal menyimpan header").slice(0, 120)); }
  }

  return (
    <Card data-testid="obs-header">
      <div className="mb-3 flex items-center gap-2 font-mono text-[11px] tracking-[0.15em] text-amber-400"><FileSpreadsheet className="h-4 w-4" />DATA PENGUJIAN</div>
      {isLoading ? <div className="flex justify-center py-6"><Loader2 className="h-5 w-5 animate-spin text-amber-400" /></div> : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Nama Operator">{txt("operator", "obs-h-operator", "Nama operator")}</Field>
          <Field label="Jam & Tanggal Mulai">
            <div className="flex items-center gap-2">
              <input type="time" value={f.start_time ?? ""} onChange={set("start_time")} className={`${inputCls} w-36 [color-scheme:dark]`} data-testid="obs-h-start-time" />
              <input type="date" value={f.start_date ?? ""} onChange={set("start_date")} className={`${inputCls} [color-scheme:dark]`} data-testid="obs-h-start-date" />
            </div>
          </Field>
          <Field label="Posisi Specimen">{txt("specimen_position", "obs-h-position")}</Field>
          <Field label="Pressure Penguapan">{txt("pressure", "obs-h-pressure")}</Field>
          <Field label="Kandungan Water">{txt("water", "obs-h-water")}</Field>
          <Field label="Temperatur Chamber (°C)">
            <div className="flex items-center gap-2">
              <input type="number" step="0.1" value={f.chamber_temp_min ?? ""} onChange={set("chamber_temp_min")} placeholder="35.1" className={inputCls} data-testid="obs-h-temp-min" />
              <span className="font-mono text-xs text-zinc-400">–</span>
              <input type="number" step="0.1" value={f.chamber_temp_max ?? ""} onChange={set("chamber_temp_max")} placeholder="36.7" className={inputCls} data-testid="obs-h-temp-max" />
            </div>
          </Field>
          <Field label="Temperatur Saturated Air">{txt("saturated_air_temp", "obs-h-sat-temp")}</Field>
          <Field label="Duration (otomatis)">
            <div className={`flex h-10 items-center gap-2 rounded-md border px-3 font-mono text-sm ${report.allReached ? "border-red-500/60 bg-red-500/10 text-red-400" : "border-zinc-700 bg-zinc-950 text-zinc-400"}`} data-testid="obs-h-duration"><Timer className="h-4 w-4" />{durationText(report)}</div>
          </Field>
          <Field label="pH">{txt("ph", "obs-h-ph")}</Field>
          <Field label="Plat Grinding" wide>
            <div className="flex items-center gap-3">
              <label className="flex shrink-0 cursor-pointer items-center gap-2 font-mono text-xs text-zinc-200">
                <input type="checkbox" checked={!!f.plate_grinding} onChange={set("plate_grinding")} className="h-4 w-4 accent-amber-500" data-testid="obs-h-grinding" />Ya, digrinding
              </label>
              <input value={f.plate_grinding_note ?? ""} onChange={set("plate_grinding_note")} placeholder="Keterangan (opsional), mis. amplas grit 240" className={inputCls} data-testid="obs-h-grinding-note" />
            </div>
          </Field>
        </div>
      )}
      <button type="button" onClick={submit} disabled={save.isPending || isLoading} data-testid="obs-h-save" className="mt-4 flex w-full items-center justify-center gap-2 rounded-md bg-amber-500 py-2.5 font-mono text-xs font-bold tracking-widest text-zinc-950 hover:bg-amber-400 disabled:opacity-50"><Save className="h-4 w-4" />{save.isPending ? "MENYIMPAN…" : "SIMPAN HEADER"}</button>
    </Card>
  );
}

export function ObsReportTable({ report }) {
  const { cols, rows } = report;
  return (
    <Card data-testid="obs-report">
      <div className="mb-3 flex flex-wrap items-center gap-2 font-mono text-[11px] tracking-[0.15em] text-amber-400">TABEL REPORT · % KOTAK BERKARAT
        <span className="ml-auto text-[10px] tracking-normal text-zinc-500">otomatis dari AI Vision / koreksi inspector</span></div>
      {rows.length === 0 ? (
        <div className="py-8 text-center font-mono text-xs text-zinc-500" data-testid="obs-report-empty">Belum ada data. Simpan kartu pengamatan dengan Jam Pengamatan dan kode sample.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse font-mono text-xs" data-testid="obs-report-table">
            <thead>
              <tr className="bg-zinc-800 text-zinc-200">
                <th rowSpan={2} className="border border-zinc-600 px-2 py-1.5">No</th>
                <th rowSpan={2} className="sticky left-0 border border-zinc-600 bg-zinc-800 px-2 py-1.5 text-left">Sample</th>
                <th colSpan={cols.length} className="border border-zinc-600 px-2 py-1">Hours</th>
              </tr>
              <tr className="bg-zinc-800/70 text-zinc-300">
                {cols.map((h) => <th key={h} className="min-w-[44px] border border-zinc-600 px-1.5 py-1" data-testid={`obs-report-col-${h}`}>{fmtHour(h)}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.code} className="text-zinc-100" data-testid={`obs-report-row-${r.code}`}>
                  <td className="border border-zinc-700 px-2 py-1.5 text-center">{r.no}</td>
                  <td className="sticky left-0 border border-zinc-700 bg-zinc-900 px-2 py-1.5 font-bold">{r.code}</td>
                  {r.cells.map((c, i) => (
                    <td key={cols[i]} className={`border border-zinc-700 px-1.5 py-1.5 text-center ${c && c.value >= 100 ? "bg-red-500/15 font-bold text-red-500" : ""} ${c?.auto ? "opacity-80" : ""}`} data-testid={`obs-report-cell-${r.code}-${cols[i]}`}>
                      {c ? `${c.value}%` : <span className="text-zinc-600">–</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
