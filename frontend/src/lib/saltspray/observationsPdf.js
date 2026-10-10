import { fileUrl, imageToDataUri } from "@/lib/kht/api";
import { obsGroupLabel } from "@/lib/saltspray/observations";

export { printHtmlOnWeb } from "@/lib/kht/pdf";

const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const styles = `
  @page { margin: 14mm 12mm; size: A4; }
  * { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { font-family: -apple-system, Helvetica, Arial, sans-serif; color: #111; margin: 0; }
  .doc-title { font-size: 15px; font-weight: 700; margin-bottom: 10px; }
  .wrap { column-count: 2; column-gap: 26px; }
  .card { break-inside: avoid; margin-bottom: 20px; }
  .title { font-size: 13px; font-weight: 600; margin: 0 0 6px; }
  .label { font-size: 10.5px; margin: 8px 0 4px; line-height: 1.4; }
  .row { display: flex; gap: 3px; align-items: flex-start; }
  .cell { flex: 1 1 0; min-width: 0; }
  .cell img { width: 100%; height: auto; display: block; border: 1px solid #d4d4d8; }
  .cell.empty { border: 1px dashed #c4c4c4; height: 120px; display: flex; align-items: center; justify-content: center; color: #9ca3af; font-size: 10px; }
`;

const wrap = (title, body) => `<!DOCTYPE html><html><head><meta charset="utf-8"/><title>${esc(title)}</title><style>${styles}</style></head><body>${body}</body></html>`;

async function loadGroup(list) {
  const out = [];
  for (const s of list) {
    let dataUri = null;
    if (s.photo_path) {
      try { dataUri = await imageToDataUri(fileUrl(s.photo_path, 1000)); } catch { /* keep null */ }
    }
    out.push({ ...s, dataUri });
  }
  return out;
}

function groupHtml(prefix, list) {
  if (!list.length) return "";
  const label = esc(obsGroupLabel(prefix, list));
  const imgs = list.map((s) => (s.dataUri
    ? `<div class="cell"><img src="${esc(s.dataUri)}" alt="${esc(s.code)}"/></div>`
    : `<div class="cell empty">tanpa foto</div>`)).join("");
  return `<div class="label">${label}</div><div class="row">${imgs}</div>`;
}

export async function buildObservationsHtml(cards) {
  const sorted = [...cards].sort((a, b) => (a.seq || 0) - (b.seq || 0));
  const assets = [];
  for (const c of sorted) {
    const samples = c.samples || [];
    assets.push({
      S: await loadGroup(samples.filter((s) => s.type === "S")),
      D: await loadGroup(samples.filter((s) => s.type === "D")),
    });
  }
  const blocks = sorted.map((c, i) => `
    <div class="card">
      <div class="title">${c.seq}. Pengamatan ${esc(c.duration_label)}</div>
      ${groupHtml(c.prefix, assets[i].S)}
      ${groupHtml(c.prefix, assets[i].D)}
    </div>`).join("");
  return wrap("Salt Spray — Kartu Pengamatan", `<div class="doc-title">Salt Spray ASTM B117 — Kartu Pengamatan</div><div class="wrap">${blocks}</div>`);
}
