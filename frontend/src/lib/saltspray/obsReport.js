// Builds the Salt Spray report table (rows = sample codes, columns = observation hours)
// from the AI Vision results stored in the Kartu Pengamatan cards.

export const REPORT_HOURS = [0, 1, 2, 3, 4, 5, 6, 24, 48, 72, 96, 120, 144, 168, 192];
const LAST_BASE = 192;

export const HEADER_DEFAULTS = {
  operator: "",
  start_time: "",
  start_date: "",
  specimen_position: "15°-30°",
  pressure: "13 psi",
  water: "10 L Aquadest + 530 gr NaCl 5%",
  chamber_temp_min: "35.1",
  chamber_temp_max: "36.7",
  saturated_air_temp: "46°C",
  ph: "6.5 - 7.2 di suhu 35°C",
  plate_grinding: false,
  plate_grinding_note: "",
};

const cardHours = (c) => {
  if (c.hours !== null && c.hours !== undefined && c.hours !== "") return Number(c.hours);
  const m = String(c.duration_label || "").match(/(\d+(?:[.,]\d+)?)/);
  return m ? Number(m[1].replace(",", ".")) : null;
};

export const fmtHour = (h) => (Number.isInteger(h) ? String(h) : String(Math.round(h * 100) / 100));

const pctOf = (plate) => {
  const n = (plate.grid_boxes || []).filter(Boolean).length;
  return Math.max(0, Math.min(100, n));
};

export function buildReport(cards) {
  const valid = (cards || [])
    .map((c) => ({ c, h: cardHours(c) }))
    .filter((x) => x.h !== null && !Number.isNaN(x.h))
    .sort((a, b) => a.h - b.h || (a.c.seq || 0) - (b.c.seq || 0));

  const samples = [];
  const data = {}; // code -> { hour: pct }
  const alias = {};
  valid.forEach(({ c, h }) => {
    (c.plates || []).forEach((p) => {
      const raw = String(p.code || "").trim().replace(/\s+/g, " ");
      if (!raw) return;
      const key = raw.toUpperCase(); // same code with different casing/spacing = same sample
      if (!alias[key]) { alias[key] = raw; data[raw] = {}; samples.push(raw); }
      data[alias[key]][h] = pctOf(p); // later card at the same hour wins
    });
  });

  const reach = {};
  samples.forEach((code) => {
    const hs = Object.keys(data[code]).map(Number).sort((a, b) => a - b);
    const hit = hs.find((h) => data[code][h] >= 100);
    reach[code] = hit === undefined ? null : hit;
  });
  const allReached = samples.length > 0 && samples.every((code) => reach[code] !== null);
  const doneHour = allReached ? Math.max(...samples.map((code) => reach[code])) : null;
  const observed = [...new Set(valid.map((x) => x.h))];
  const maxObserved = observed.length ? Math.max(...observed) : 0;

  let cols;
  if (allReached) {
    cols = REPORT_HOURS.filter((h) => h <= doneHour);
  } else {
    cols = [...REPORT_HOURS];
    for (let h = LAST_BASE + 24; h - 24 < maxObserved; h += 24) cols.push(h); // +24h until the last observation
  }
  observed.forEach((h) => { if (!cols.includes(h) && (!allReached || h <= doneHour)) cols.push(h); });
  cols.sort((a, b) => a - b);

  const rows = samples.map((code, i) => ({
    no: i + 1,
    code,
    cells: cols.map((h) => {
      if (data[code][h] !== undefined) return { value: data[code][h], auto: false };
      if (reach[code] !== null && h > reach[code]) return { value: 100, auto: true };
      return null;
    }),
  }));

  return { cols, rows, allReached, doneHour, samples };
}

export const durationText = (report) => (report.allReached ? `${fmtHour(report.doneHour)} Jam` : "Belum tercapai (belum semua sample 100%)");

export function nextReportHour(cards) {
  const hs = (cards || []).map(cardHours).filter((h) => h !== null && !Number.isNaN(h));
  if (!hs.length) return 0;
  const max = Math.max(...hs);
  return REPORT_HOURS.find((h) => h > max) ?? max + 24;
}
