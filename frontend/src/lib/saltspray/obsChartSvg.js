import { fmtHour } from "@/lib/saltspray/obsReport";

// Print-friendly (dark enough on white paper) palette, same order as SAMPLE_COLORS.
export const PRINT_COLORS = ["#D97706", "#0891B2", "#7C3AED", "#059669", "#DB2777", "#2563EB", "#EA580C", "#65A30D"];

const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// Static SVG version of RustProgressChart (% kotak berkarat vs jam) for the PDF export.
export function progressChartHtml(report, colors = PRINT_COLORS) {
  const { cols, rows } = report;
  if (!rows.length || !cols.length) return "";
  const W = 760, H = 290, L = 44, R = 14, T = 12, B = 34;
  const pw = W - L - R, ph = H - T - B;
  const x = (i) => L + (cols.length === 1 ? pw / 2 : (i * pw) / (cols.length - 1));
  const y = (v) => T + ph - (Math.max(0, Math.min(100, v)) / 100) * ph;

  const grid = [0, 25, 50, 75, 100].map((v) => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#d4d4d8" stroke-dasharray="3 3"/><text x="${L - 6}" y="${y(v) + 3}" font-size="10" text-anchor="end" fill="#444">${v}%</text>`).join("");
  const xt = cols.map((h, i) => `<line x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${T + ph}" stroke="#ececee"/><text x="${x(i)}" y="${T + ph + 14}" font-size="10" text-anchor="middle" fill="#444">${fmtHour(h)}</text>`).join("");
  const ref = `<line x1="${L}" x2="${W - R}" y1="${y(100)}" y2="${y(100)}" stroke="#ef4444" stroke-width="1.2" stroke-dasharray="5 4"/>`;
  const axes = `<line x1="${L}" x2="${L}" y1="${T}" y2="${T + ph}" stroke="#888"/><line x1="${L}" x2="${W - R}" y1="${T + ph}" y2="${T + ph}" stroke="#888"/>`;
  const xlabel = `<text x="${L + pw / 2}" y="${H - 4}" font-size="10" text-anchor="middle" fill="#333">Jam</text>`;

  const lines = rows.map((r, ri) => {
    const c = colors[ri % colors.length];
    const pts = r.cells.map((cell, i) => (cell ? [x(i), y(cell.value)] : null)).filter(Boolean); // connectNulls
    if (!pts.length) return "";
    const poly = pts.length > 1 ? `<polyline fill="none" stroke="${c}" stroke-width="2" stroke-linejoin="round" points="${pts.map((p) => p.join(",")).join(" ")}"/>` : "";
    return poly + pts.map(([px, py]) => `<circle cx="${px}" cy="${py}" r="3" fill="#fff" stroke="${c}" stroke-width="1.6"/>`).join("");
  }).join("");

  const legend = rows.map((r, ri) => `<span class="lg"><i style="background:${colors[ri % colors.length]}"></i>${esc(r.code)}</span>`).join("");
  return `<div class="chart"><div class="sec">KURVA PROGRESS KOROSI · % vs JAM</div><svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet" style="display:block;max-height:78mm" font-family="Helvetica, Arial, sans-serif">${grid}${xt}${axes}${ref}${lines}${xlabel}</svg><div class="legend">${legend}</div></div>`;
}
