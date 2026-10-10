import React from "react";

export const GRADE_COLORS = { A: "#10B981", B: "#34D399", C: "#FBBF24", D: "#F97316", E: "#EF4444" };

export default function HumidityGrid({ boxes = [], onToggle, interactive = false }) {
  const cells = Array.from({ length: 100 }, (_, i) => Boolean(boxes[i]));
  return (
    <div className="rounded-lg border border-zinc-600 bg-zinc-950 p-3" data-testid="humidity-grid">
      <div className="mb-2 flex items-center justify-between font-mono text-[10px] tracking-widest text-zinc-500">
        <span>SELURUH GAMBAR = ACTIVE ZONE</span><span>10 × 10 / 100 BOXES</span>
      </div>
      <div className="grid grid-cols-10 gap-0.5 border border-zinc-600 bg-zinc-700" data-testid="humidity-grid-matrix">
        {cells.map((rusted, index) => (
          <button
            key={`humidity-box-${index}`}
            type="button"
            disabled={!interactive}
            onClick={() => onToggle?.(index)}
            data-testid={`humidity-grid-box-${index + 1}`}
            aria-label={`Kotak ${index + 1}${rusted ? " berkarat" : " bersih"}`}
            className={`aspect-square border text-[8px] font-bold transition-colors ${rusted ? "border-orange-500/60 bg-orange-500 text-zinc-950" : "border-zinc-800 bg-zinc-900 text-zinc-600 hover:bg-zinc-800"} ${interactive ? "cursor-pointer" : "cursor-default"}`}
          >{index + 1}</button>
        ))}
      </div>
      <div className="mt-2 flex items-center justify-between font-mono text-[10px] text-zinc-500"><span>ORANGE = KARAT/KOROSI</span><span>ROW-MAJOR COUNT</span></div>
    </div>
  );
}
