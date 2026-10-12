import { fileUrl, imageToDataUri } from "@/lib/kht/api";
import { FULL_CORNERS, gradeSpecFor, renderOverlay } from "@/lib/saltspray/figure";
import { buildReport, durationText, fmtHour, HEADER_DEFAULTS } from "@/lib/saltspray/obsReport";

export { printHtmlOnWeb } from "@/lib/kht/pdf";

const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const styles = `
  @page { margin: 12mm 10mm; size: A4; }
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

async function plateFigure(p) {
  if (!p.crop_path) return null;
  try {
    const n = (p.grid_boxes || []).filter(Boolean).length;
    const { dataUrl } = await renderOverlay(fileUrl(p.crop_path, 1000), FULL_CORNERS, p.grid_boxes, { method: "full", maxW: 700, label: p.code || `Sample ${p.index}` });
    return { dataUrl, n };
  } catch {
    return null;
  }
}

export async function buildObservationsHtml(cards, header = {}, report = null) {
  const rep = report || buildReport(cards);
  const sorted = [...cards].sort((a, b) => (a.hours ?? 0) - (b.hours ?? 0) || (a.seq || 0) - (b.seq || 0));
  const blocks = [];
  for (const c of sorted) {
    let photo = null;
    if (c.photo_path) { try { photo = await imageToDataUri(fileUrl(c.photo_path, 1400)); } catch { /* skip */ } }
    const cells = [];
    for (const p of c.plates || []) {
      const fig = await plateFigure(p);
      const n = (p.grid_boxes || []).filter(Boolean).length;
      const spec = gradeSpecFor(n);
      cells.push(`<div class="cell">${fig ? `<img src="${esc(fig.dataUrl)}" alt="${esc(p.code)}"/>` : ""}
        <div class="cap"><b>Sample ${p.index}: ${esc(p.code)}</b><br/>${n}/100 kotak berkarat · <span class="badge" style="background:${spec.color}">Grade ${spec.g}</span><br/>${esc(spec.label)}${p.edited ? " · dikoreksi inspector" : ""}</div></div>`);
    }
    blocks.push(`<div class="card">
      <div class="title">${esc(c.seq)}. Pengamatan ${esc(c.duration_label)}</div>
      ${photo ? `<img class="photo" src="${esc(photo)}" alt="foto 4 plat"/>` : ""}
      <div class="row">${cells.join("")}</div>
    </div>`);
  }
  return wrap("Salt Spray — Kartu Pengamatan", `<div class="doc-title">Salt Spray ASTM B117 — Kartu Pengamatan</div><div class="doc-sub">Metode Seluruh Gambar: tiap plat = active zone, dibagi rata 10×10. Kotak merah bernomor = kotak berkarat.</div>${headerHtml(header, rep)}${reportHtml(rep)}<div class="page-break"></div><div class="sec">KARTU PENGAMATAN</div>${blocks.join("")}`);
}
