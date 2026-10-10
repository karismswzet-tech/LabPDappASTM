import { fileUrl, imageToDataUri } from "@/lib/kht/api";
import { fmtDate, fmtDateTime } from "@/lib/kht/format";
import { gradeSpecFor, renderCalcFigure, renderOverlay } from "@/lib/rust/figure";

export { printHtmlOnWeb } from "@/lib/kht/pdf";

const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const cnt = (boxes) => (boxes || []).filter(Boolean).length;

const styles = `
  @page { margin: 0; size: A4; }
  * { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-family: -apple-system, Helvetica, Arial, sans-serif; color: #0A1420; margin: 0; }
  .page { padding: 32px 30px; page-break-after: always; }
  .page:last-child { page-break-after: auto; }
  h1 { margin: 0; font-size: 21px; }
  h2 { font-size: 13px; letter-spacing: .8px; margin: 16px 0 6px; color: #0A1420; text-transform: uppercase; }
  .sub { color: #b45309; font-size: 10.5px; letter-spacing: 1.2px; font-weight: 700; }
  .head { display:flex; justify-content:space-between; align-items:flex-end; border-bottom:2px solid #0A1420; padding-bottom:8px; }
  .badge { display:inline-block; padding:3px 10px; border-radius:4px; color:#fff; font-weight:700; font-size:11px; }
  .verdicts { display:grid; grid-template-columns: repeat(3,1fr); gap:10px; margin-top:12px; }
  .verdict { border:1px solid #e5e7eb; border-radius:8px; padding:10px; }
  .verdict .k { font-size:9px; letter-spacing:1px; color:#64748b; font-weight:700; text-transform:uppercase; }
  .verdict .g { font-size:34px; font-weight:800; line-height:1.1; margin-top:4px; }
  .verdict .n { font-size:12px; font-weight:700; }
  .verdict .s { font-size:10px; color:#475569; margin-top:2px; }
  .photo { text-align:center; margin-top:10px; }
  .photo img { max-width:100%; max-height:300px; border-radius:6px; border:1px solid #e5e7eb; object-fit:contain; }
  .fig { margin-top:8px; text-align:center; }
  .fig img { max-width:100%; border:1px solid #e5e7eb; border-radius:6px; }
  .caption { color:#64748b; font-size:9.5px; margin-top:3px; }
  .card { border:1px solid #e5e7eb; border-radius:8px; padding:10px 12px; margin-top:10px; }
  .card b { font-size:11px; letter-spacing:.5px; }
  .card p { margin:4px 0 0; font-size:11px; color:#374151; line-height:1.5; }
  table.t { width:100%; border-collapse:collapse; margin-top:6px; }
  table.t th { background:#0A1420; color:#fff; font-size:9.5px; letter-spacing:.5px; padding:6px; text-align:left; text-transform:uppercase; }
  table.t td { padding:6px; border-bottom:1px solid #e5e7eb; font-size:11px; }
  .meta { display:grid; grid-template-columns:1fr 1fr; gap:2px 16px; }
  .meta div { font-size:11px; padding:4px 0; border-bottom:1px solid #eef2f7; }
  .meta span { color:#64748b; margin-right:6px; }
  .sign { display:grid; grid-template-columns:1fr 1fr; gap:30px; margin-top:26px; font-size:11px; }
  .sign div { border-top:1px solid #0A1420; padding-top:4px; text-align:center; margin-top:44px; }
  .cover-hero { background: linear-gradient(135deg,#0A1420 0%, #3A2A10 70%); color:#fff; padding:26px; border-radius:12px; }
  .cover-hero .brand { color:#F59E0B; font-size:12px; letter-spacing:2px; font-weight:700; }
  .cover-hero h1 { color:#fff; font-size:25px; margin-top:6px; }
  .stat-row { display:grid; grid-template-columns:repeat(5,1fr); gap:8px; margin-top:16px; }
  .stat-cell { background:#F1F5F9; border-radius:8px; padding:10px; text-align:center; }
  .stat-cell .k { font-size:9px; color:#64748b; letter-spacing:1px; }
  .stat-cell .v { font-size:20px; font-weight:800; margin-top:3px; }
`;

const wrap = (title, body) => `<!DOCTYPE html><html><head><meta charset="utf-8"/><title>${esc(title)}</title><style>${styles}</style></head><body>${body}</body></html>`;
const gradeTxtColor = (c) => (c === "#FBBF24" ? "#B45309" : c);

function verdictCard(key, n, extra, testId) {
  if (n === null || n === undefined) {
    return `<div class="verdict" data-testid="${testId}"><div class="k">${esc(key)}</div><div class="g" style="color:#94A3B8">—</div><div class="n">Belum diisi</div><div class="s">${esc(extra || "")}</div></div>`;
  }
  const s = gradeSpecFor(n);
  return `<div class="verdict" style="border-color:${s.color}88;background:${s.color}10" data-testid="${testId}"><div class="k">${esc(key)}</div><div class="g" style="color:${gradeTxtColor(s.color)}">Grade ${s.g}</div><div class="n">${n} / 100 kotak berkarat</div><div class="s">${esc(s.status)} · ${esc(s.label)}${extra ? `<br/>${esc(extra)}` : ""}</div></div>`;
}

async function diptestFigures(photo, rec) {
  const boxes = rec.grid_boxes || [];
  const label = "PENILAIAN INSPECTOR";
  let overlayFull = null;
  try {
    const full = await renderOverlay(photo, rec.grid_corners, boxes, { zoom: false, maxW: 1400, method: "full", label });
    overlayFull = full.dataUrl;
  } catch { /* photo could not be drawn */ }
  return { overlayFull, calc: renderCalcFigure(boxes, { method: "full", title: "PERHITUNGAN · ASTM D1748 · DIP TEST · SELURUH GAMBAR · PENILAIAN INSPECTOR" }) };
}

export async function prepareDipAssets(rec) {
  const url = fileUrl(rec.image_path, 1600);
  const photo = (await imageToDataUri(url)) || url;
  return { photo, ...(await diptestFigures(photo, rec)) };
}

function overlayBlock(F) {
  if (!F.overlayFull) return `<div class="caption">Overlay tidak dapat dibuat untuk foto ini.</div>`;
  return `<div class="fig"><img src="${esc(F.overlayFull)}" alt="overlay seluruh gambar" style="max-height:360px"/><div class="caption">Metode Seluruh Gambar: seluruh foto = active zone, dibagi rata 10×10 (tiap kotak 10% lebar × 10% tinggi). Kotak merah bernomor = kotak berkarat (penilaian inspector).</div></div>`;
}

function renderRecordPages(rec, A, index, total) {
  const tag = index && total ? ` · SAMPLE ${index}/${total}` : "";
  const finalN = cnt(rec.grid_boxes);
  const final = gradeSpecFor(finalN);
  const m = rec.meta || {};
  const header = (title) => `
    <div class="head">
      <div><div class="sub">DIP TEST · ASTM D1748${tag}</div><h1>${esc(m.sample_id || "—")} — ${esc(title)}</h1></div>
      <div style="text-align:right"><div style="font-size:10px;color:#64748b">${esc(fmtDateTime(rec.created_at))}</div>
      <div style="margin-top:4px"><span class="badge" style="background:${final.color}">GRADE AKHIR ${final.g}</span></div></div>
    </div>`;

  const page1 = `
  <div class="page" data-testid="diptest-pdf-page-summary">
    ${header("Laporan Inspeksi")}
    <div class="verdicts" style="grid-template-columns:1fr">
      ${verdictCard("Penilaian Inspector", finalN, rec.inspector_name ? `oleh ${rec.inspector_name}` : "", "diptest-pdf-verdict-inspector")}
    </div>
    <h2>Foto Spesimen yang Diunggah</h2>
    <div class="photo"><img src="${esc(A.photo)}" alt="foto spesimen"/><div class="caption">Foto asli inspeksi — ${esc(m.sample_id || "—")} (tanpa overlay)</div></div>
    <h2>Ringkasan Penilaian</h2>
    <table class="t">
      <thead><tr><th>Penilaian</th><th>Kotak berkarat</th><th>Luas</th><th>Grade</th><th>Status</th></tr></thead>
      <tbody>
        <tr data-testid="diptest-pdf-row-inspector"><td>Penilaian Inspector</td><td>${finalN}/100</td><td>${finalN}%</td><td><b>${final.g}</b></td><td>${esc(final.status)}</td></tr>
      </tbody>
    </table>
    <div class="card"><b>Test Information</b><div class="meta" style="margin-top:4px">
      <div><span>Product / Oil</span>${esc(m.product || "—")}</div><div><span>Batch / Lot</span>${esc(m.batch || "—")}</div>
      <div><span>Exposure</span>${esc(m.exposure_hours)}h @ ${esc(m.temperature_c)}&deg;C</div><div><span>Humidity</span>${esc(m.humidity_pct)}% RH</div>
      <div><span>Substrate</span>${esc(m.substrate || "—")}</div><div><span>Operator</span>${esc(m.operator || "—")}</div>
      <div><span>Sebaran karat</span>${esc(rec.rust_spread || "—")}</div><div><span>Remark</span>${esc(m.remark || "—")}</div>
    </div></div>
  </div>`;

  const page2 = `
  <div class="page" data-testid="diptest-pdf-page-calc">
    ${header("Detail Perhitungan · Seluruh Gambar")}
    <h2>1 · Pemetaan grid 100 kotak pada seluruh foto</h2>
    ${overlayBlock(A)}
    <h2>2 · Matriks perhitungan &amp; penentuan grade</h2>
    <div class="fig"><img src="${esc(A.calc)}" alt="perhitungan"/></div>
  </div>`;

  const page3 = `
  <div class="page" data-testid="diptest-pdf-page-notes">
    ${header("Catatan & Pengesahan")}
    <div class="card"><b>Kriteria Grade ASTM D1748 (100 kotak)</b>
      <p>Hasil penilaian inspector: ${finalN}/100 kotak berkarat → Grade ${final.g} (${esc(final.status)})</p>
      <table class="t"><thead><tr><th>Grade</th><th>Kotak berkarat</th><th>Status</th><th>Keterangan</th></tr></thead><tbody>
      ${["A", "B", "C", "D", "E"].map((g) => { const s = gradeSpecFor({ A: 0, B: 1, C: 11, D: 26, E: 51 }[g]); return `<tr style="${s.g === final.g ? "background:#FEF3C7;font-weight:700" : ""}"><td><span class="badge" style="background:${s.color}">${s.g}</span></td><td>${s.min === s.max ? s.min : `${s.min}–${s.max}`}</td><td>${esc(s.status)}</td><td>${esc(s.label)}</td></tr>`; }).join("")}
      </tbody></table></div>
    <div class="sign"><div>Inspector${rec.inspector_name ? ` — ${esc(rec.inspector_name)}` : ""}</div><div>Supervisor / Approver</div></div>
  </div>`;
  return page1 + page2 + page3;
}

export async function buildDipSingleHtml(rec) {
  const assets = await prepareDipAssets(rec);
  return wrap(`ASTM D1748 Dip - ${rec.meta?.sample_id || rec.id}`, renderRecordPages(rec, assets));
}

export async function buildDipCombinedHtml(records) {
  const assets = [];
  for (const r of records) assets.push(await prepareDipAssets(r));
  const total = records.length;
  const finalN = (r) => r.inspector_count ?? cnt(r.grid_boxes);
  const counts = { A: 0, B: 0, C: 0, D: 0, E: 0 };
  records.forEach((r) => { counts[gradeSpecFor(finalN(r)).g] += 1; });
  const rows = records.map((r, i) => {
    const aiN = r.ai_rusted_box_count ?? cnt(r.ai_grid_boxes || r.grid_boxes);
    const f = gradeSpecFor(finalN(r));
    return `<tr><td>#${i + 1}</td><td><img src="${esc(assets[i].photo)}" style="width:54px;height:40px;object-fit:cover;border-radius:4px"/></td><td>${esc(r.meta?.sample_id || "—")}</td><td>${esc(r.meta?.product || "—")}</td><td>${esc(fmtDate(r.created_at))}</td><td>${aiN} · ${gradeSpecFor(aiN).g}</td><td>${cnt(r.grid_boxes)} · ${gradeSpecFor(cnt(r.grid_boxes)).g}</td><td>${r.inspector_count ?? "—"}${r.inspector_count != null ? ` · ${gradeSpecFor(r.inspector_count).g}` : ""}</td><td><span class="badge" style="background:${f.color}">${f.g}</span></td></tr>`;
  }).join("");
  const cover = `
  <div class="page" data-testid="diptest-pdf-cover">
    <div class="cover-hero"><div class="brand">DIP TEST · ASTM D1748</div><h1>Combined DIP TEST Report</h1>
      <div style="color:#CBD5E1;font-size:12px;margin-top:4px">${total} sampel · Dihasilkan ${esc(fmtDateTime(new Date().toISOString()))}</div></div>
    <div class="stat-row">${Object.entries(counts).map(([g, n]) => { const s = gradeSpecFor({ A: 0, B: 1, C: 11, D: 26, E: 51 }[g]); return `<div class="stat-cell"><div class="k">GRADE ${g}</div><div class="v" style="color:${gradeTxtColor(s.color)}">${n}</div></div>`; }).join("")}</div>
    <table class="t" style="margin-top:18px"><thead><tr><th>#</th><th>Foto</th><th>Sample ID</th><th>Product</th><th>Tanggal</th><th>AI Vision</th><th>Koreksi grid</th><th>Manual</th><th>Akhir</th></tr></thead><tbody>${rows}</tbody></table>
    <div class="caption" style="margin-top:6px">Kolom berisi jumlah kotak berkarat · grade. Detail tiap sampel (foto, overlay AI, perhitungan) ada di halaman berikutnya.</div>
  </div>`;
  const pages = records.map((r, i) => renderRecordPages(r, assets[i], i + 1, total)).join("");
  return wrap("ASTM D1748 Dip Combined Report", cover + pages);
}
