export const MODULES = {
  khtt: {
    slug: "khtt",
    title: "K-HTT Analyst",
    short: "K-HTT",
    description:
      "Komatsu Hot Tube Tester — AI Vision rating endapan 0–10 (Nikko Color Scale) untuk oli & pelumas.",
    ratingOptions: ["Excellent", "Good", "Fair", "Poor", "Reject"],
    ratingLabel: "Overall Rating",
    parameters: [
      { key: "appearance", label: "Appearance", unit: "", type: "text" },
      { key: "color", label: "Color (ASTM D1500)", unit: "", type: "text" },
      { key: "water_content", label: "Water Content", unit: "% vol", type: "number" },
      { key: "sediment", label: "Sediment", unit: "% wt", type: "number" },
      { key: "total_acid_number", label: "Total Acid Number", unit: "mg KOH/g", type: "number" },
      { key: "kinematic_viscosity", label: "Kinematic Viscosity @40°C", unit: "cSt", type: "number" },
      { key: "flash_point", label: "Flash Point", unit: "°C", type: "number" },
      { key: "thermal_stability", label: "Thermal Stability Index", unit: "", type: "text" },
    ],
  },
  "copper-strip": {
    slug: "copper-strip",
    title: "Copper Strip ASTM D130",
    short: "Copper Strip",
    description:
      "Uji korosi bilah tembaga (copper strip corrosion) dengan AI Vision — klasifikasi ASTM D130 / IP 154 (1a–4c), status CLEAR/TARNISH & export PDF.",
    ratingOptions: ["0", "1a", "1b", "2a", "2b", "2c", "2d", "3a", "3b", "3c", "4a", "4b", "4c"],
    ratingLabel: "Classification (ASTM D130)",
    parameters: [
      { key: "test_temperature", label: "Test Temperature", unit: "°C", type: "number" },
      { key: "test_duration", label: "Test Duration", unit: "hours", type: "number" },
      { key: "strip_appearance", label: "Strip Appearance", unit: "", type: "text" },
      { key: "tarnish_level", label: "Tarnish Level", unit: "", type: "text" },
      { key: "bath_medium", label: "Bath Medium", unit: "", type: "text" },
    ],
  },
  "rating-dka": {
    slug: "rating-dka",
    title: "Rating DKA",
    short: "Rating DKA",
    description:
      "Analisa batch hingga 4 tabung per foto dengan AI Vision + OCR label — kategori CLEAR · Aspect 1 · Aspect 2 · Aspect 3.",
    ratingOptions: ["A - Sangat Baik", "B - Baik", "C - Cukup", "D - Kurang", "E - Buruk"],
    ratingLabel: "DKA Rating",
    parameters: [
      { key: "deposit_level", label: "Deposit Level", unit: "merit", type: "number" },
      { key: "carbon_residue", label: "Carbon Residue", unit: "% wt", type: "number" },
      { key: "oxidation_stability", label: "Oxidation Stability", unit: "min", type: "number" },
      { key: "sludge_content", label: "Sludge Content", unit: "mg/100ml", type: "number" },
      { key: "varnish_rating", label: "Varnish Rating", unit: "merit", type: "number" },
      { key: "color_change", label: "Color Change", unit: "", type: "text" },
    ],
  },
  htcbt: {
    slug: "htcbt",
    title: "HTCBT-ASTM D6594",
    short: "HTCBT",
    description:
      "High Temperature Corrosion Bench Test — OCR label tulisan tangan (AI Vision) + Smart Timer countdown 168 jam / 312 jam dengan monitoring real-time.",
    ratingOptions: ["Pass", "Fail"],
    ratingLabel: "Result",
    parameters: [],
  },
  "dka-cec": {
    slug: "dka-cec",
    title: "DKA-CEC L-48-A-00",
    short: "DKA-CEC",
    description:
      "CEC L-48-A-00 oxidation test — OCR label tulisan tangan (AI Vision) membaca Sample ID, suhu & operator + Smart Timer countdown 192 jam @ 150/160/180°C.",
    ratingOptions: ["Pass", "Fail"],
    ratingLabel: "Result",
    parameters: [],
  },
  "rust-preventing": {
    slug: "rust-preventing",
    title: "Rust Preventing ASTM D1748",
    short: "ASTM D1748",
    description:
      "Inspeksi metal panel dengan measuring plate 100 kotak — AI Vision menghitung kotak berkarat pada area tengah 50 × 50 mm dan memberi Grade A–E.",
    ratingOptions: ["Grade A", "Grade B", "Grade C", "Grade D", "Grade E"],
    ratingLabel: "Rust Rating",
    parameters: [],
  },
  "humidity-cabinet": {
    slug: "humidity-cabinet",
    title: "Humidity Cabinet Test ASTM D1748",
    short: "Humidity D1748",
    description:
      "Inspeksi spesimen humidity cabinet dengan metode seluruh gambar — AI Vision membagi seluruh foto menjadi 100 kotak (10 × 10) dan menghitung kotak berkarat untuk Grade A–E.",
    ratingOptions: ["Grade A", "Grade B", "Grade C", "Grade D", "Grade E"],
    ratingLabel: "Rust Rating",
    parameters: [],
  },
  "dip-test": {
    slug: "dip-test",
    title: "DIP TEST In House Method",
    short: "DIP TEST",
    description:
      "Inspeksi spesimen DIP TEST (metode in-house) dengan metode seluruh gambar — AI Vision membagi seluruh foto menjadi 100 kotak (10 × 10) dan menghitung kotak berkarat untuk Grade A–E.",
    ratingOptions: ["Grade A", "Grade B", "Grade C", "Grade D", "Grade E"],
    ratingLabel: "Rust Rating",
    parameters: [],
  },
  "salt-spray": {
    slug: "salt-spray",
    title: "Salt Spray ASTM B117",
    short: "ASTM B117",
    description:
      "Inspeksi panel uji salt spray (kabut garam) dengan measuring plate 100 kotak — AI Vision menghitung kotak berkarat pada active zone 50 × 50 mm dan memberi Grade A–E.",
    ratingOptions: ["Grade A", "Grade B", "Grade C", "Grade D", "Grade E"],
    ratingLabel: "Rust Rating",
    parameters: [],
  },
};

export const MODULE_LIST = Object.values(MODULES);
