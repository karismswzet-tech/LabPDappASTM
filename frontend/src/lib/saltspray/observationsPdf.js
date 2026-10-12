import { fileUrl, imageToDataUri } from "@/lib/kht/api";
import { buildReport, durationText, fmtHour, HEADER_DEFAULTS } from "@/lib/saltspray/obsReport";

export { printHtmlOnWeb } from "@/lib/kht/pdf";

const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const styles = `
  /* margin 0 hides the browser's URL/date/page-number header & footer; spacing comes from .pp spacer rows */
  @page { margin: 0; size: A4; }
  html, body { margin: 0; padding: 0; }
  table.pp { width: 100%; border-collapse: collapse; }
  table.pp > thead td, table.pp > tfoot td { height: 11mm; padding: 0; }
  table.pp > tbody > tr > td { padding: 0 11mm; vertical-align: top; }
  .gal { display: grid; gap: 3mm 4mm; }
  .gcell { break-inside: avoid; min-width: 0; text-align: center; }
  .gcell .gt { font-size: 10.5px; font-weight: 700; text-align: left; margin-bottom: 1mm; }
  .gcell img { width: 100%; object-fit: contain; display: block; border: 1px solid #d4d4d8; background: #fafafa; }
  .gcell .gc { font-size: 8.5px; color: #333; text-align: left; margin-top: 1mm; line-height: 1.3; }
  .gal-page { break-before: page; }
  * { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-family: -apple-system, Helvetica, Arial, sans-serif; color: #111; margin: 0; }
  .doc-title { font-size: 15px; font-weight: 700; margin-bottom: 4px; }
  .doc-sub { font-size: 10px; color: #555; margin-bottom: 12px; }
  .card { break-inside: avoid; margin-bottom: 22px; border-top: 1px solid #ddd; padding-top: 10px; }
  .title { font-size: 13px; font-weight: 600; margin: 0 0 6px; }
  .photo { max-width: 100%; max-height: 200px; display: block; margin: 0 auto 8px; border: 1px solid #d4d4d8; }
  .row { display: flex; gap: 6px; align-items: flex-start; }
  .cell { flex: 1 1 0; min-width: 0; }
  .cell img { width: 100%; height: auto; display: block; border: 1px solid #d4d4d8; }
  .cap { font-size: 10px; margin-top: 3px; line-height: 1.35; }
  .cap b { font-size: 11px; }
  .badge { display: inline-block; padding: 0 5px; border-radius: 3px; color: #111; font-weight: 700; }
  .sec { font-size: 12px; font-weight: 700; margin: 10px 0 6px; letter-spacing: .04em; }
  table.hdr { width: 100%; border-collapse: collapse; font-size: 10.5px; margin-bottom: 10px; }
  table.hdr td { border: 1px solid #bbb; padding: 4px 6px; vertical-align: top; }
  table.hdr td.k { background: #f4f4f5; font-weight: 600; width: 22%; }
  table.rep { width: 100%; border-collapse: collapse; font-size: 9.5px; margin-bottom: 16px; }
  table.rep th, table.rep td { border: 1px solid #999; padding: 3px 2px; text-align: center; }
  table.rep th { background: #e4e4e7; }
  table.rep td.s { text-align: left; font-weight: 700; padding-left: 5px; white-space: nowrap; }
  table.rep td.r { color: #DC2626; font-weight: 700; }
  .page-break { break-before: page; }
`;

function headerHtml(h, report) {
  const v = { ...HEADER_DEFAULTS, ...(h || {}) };
  const temp = v.chamber_temp_min || v.chamber_temp_max ? `${esc(v.chamber_temp_min)}°C - ${esc(v.chamber_temp_max)}°C` : "-";
  const grind = `${v.plate_grinding ? "Ya" : "Tidak"}${v.plate_grinding_note ? ` — ${esc(v.plate_grinding_note)}` : ""}`;
  const start = [v.start_time, v.start_date ? new Date(`${v.start_date}T00:00:00`).toLocaleDateString("id-ID", { day: "2-digit", month: "long", year: "numeric" }) : ""].filter(Boolean).join(", ") || "-";
  const rows = [
    ["Nama Operator", esc(v.operator) || "-", "Jam & Tanggal Mulai", esc(start)],
    ["Posisi Specimen", esc(v.specimen_position), "Temperatur Chamber", temp],
    ["Pressure Penguapan", esc(v.pressure), "Temperatur Saturated Air", esc(v.saturated_air_temp)],
    ["Kandungan Water", esc(v.water), "Duration", `<b style="color:${report.allReached ? "#DC2626" : "#111"}">${esc(durationText(report))}</b>`],
    ["pH", esc(v.ph), "Plat Grinding", grind],
  ];
  return `<div class="sec">DATA PENGUJIAN</div><table class="hdr">${rows.map((r) => `<tr><td class="k">${r[0]}</td><td>${r[1]}</td><td class="k">${r[2]}</td><td>${r[3]}</td></tr>`).join("")}</table>`;
}

function reportHtml(report) {
  const { cols, rows } = report;
  if (!rows.length) return `<div class="sec">TABEL REPORT</div><div class="cap">Belum ada data.</div>`;
  const head = `<tr><th rowspan="2">No</th><th rowspan="2">Sample</th><th colspan="${cols.length}">Hours</th></tr><tr>${cols.map((h) => `<th>${fmtHour(h)}</th>`).join("")}</tr>`;
  const body = rows.map((r) => `<tr><td>${r.no}</td><td class="s">${esc(r.code)}</td>${r.cells.map((c) => (c ? `<td class="${c.value >= 100 ? "r" : ""}">${c.value}%</td>` : "<td>–</td>")).join("")}</tr>`).join("");
  return `<div class="sec">TABEL REPORT · % KOTAK BERKARAT</div><table class="rep">${head}${body}</table>`;
}

const wrap = (title, body) => `<!DOCTYPE html><html><head><meta charset="utf-8"/><title>${esc(title)}</title><style>${styles}</style></head><body>${body}</body></html>`;

function galleryLayout(n) {
  const cols = n <= 2 ? 1 : n <= 6 ? 2 : 3;
  const rows = Math.max(1, Math.ceil(n / cols));
  // A4 297mm - 22mm page spacing - 10mm section title; reserve ~12mm per row for caption + gaps
  const imgH = Math.max(28, Math.floor((297 - 22 - 10) / rows - 12));
  return { cols, imgH };
}

export async function buildObservationsHtml(cards, header = {}, report = null) {
  const rep = report || buildReport(cards);
  const sorted = [...cards].sort((a, b) => (a.hours ?? 0) - (b.hours ?? 0) || (a.seq || 0) - (b.seq || 0));
  const { cols, imgH } = galleryLayout(sorted.length);
  const cells = [];
  for (const c of sorted) {
    let photo = null;
    if (c.photo_path) { try { photo = await imageToDataUri(fileUrl(c.photo_path, 1400)); } catch { /* skip */ } }
    const codes = (c.plates || []).map((p) => `${p.index}: ${esc(p.code)}`).join(" · ");
    cells.push(`<div class="gcell">
      <div class="gt">${esc(c.seq)}. Pengamatan ${esc(c.duration_label)}</div>
      ${photo ? `<img src="${esc(photo)}" style="max-height:${imgH}mm" alt="foto 4 plat"/>` : `<div class="gc">tanpa foto</div>`}
      ${codes ? `<div class="gc">${codes}</div>` : ""}
    </div>`);
  }
  const page1 = `<div class="doc-title">Salt Spray ASTM B117 — Kartu Pengamatan</div><div class="doc-sub">Metode Seluruh Gambar: tiap plat = active zone, dibagi rata 10×10.</div>${headerHtml(header, rep)}${reportHtml(rep)}`;
  const gallery = cells.length ? `<div class="gal-page"><div class="sec">FOTO KARTU PENGAMATAN</div><div class="gal" style="grid-template-columns:repeat(${cols},minmax(0,1fr))">${cells.join("")}</div></div>` : "";
  const body = `<table class="pp"><thead><tr><td></td></tr></thead><tfoot><tr><td></td></tr></tfoot><tbody><tr><td>${page1}${gallery}</td></tr></tbody></table>`;
  return wrap("Salt Spray — Kartu Pengamatan", body);
}
