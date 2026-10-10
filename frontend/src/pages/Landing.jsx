import React from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  FlaskConical,
  Beaker,
  Gauge,
  Timer,
  Hourglass,
  ArrowRight,
  LogIn,
  Hexagon,
  ShieldCheck,
  ShieldAlert,
  CloudDrizzle,
  Droplets,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { MODULE_LIST } from "@/config/modules";
import heroLab from "@/assets/hero-lab.png";
import mottoBanner from "@/assets/motto-banner.jpg";

const HERO_IMG = heroLab;

const MODULE_ICONS = { khtt: FlaskConical, "copper-strip": Beaker, "rating-dka": Gauge, htcbt: Timer, "dka-cec": Hourglass, "rust-preventing": ShieldAlert, "salt-spray": CloudDrizzle, "humidity-cabinet": Droplets };

const EXPERTISE = [
  {
    emoji: "🔬",
    title: "Lubricant Testing",
    desc: "Pengujian berbagai karakteristik fisik dan kimia pelumas untuk memastikan kesesuaian terhadap spesifikasi dan standar yang berlaku.",
  },
  {
    emoji: "⚙️",
    title: "Performance Testing",
    desc: "Evaluasi performa pelumas melalui berbagai pengujian simulasi dan performance test untuk mengetahui kemampuan pelumas dalam melindungi dan mendukung kinerja mesin.",
  },
  {
    emoji: "🧪",
    title: "Product Development",
    desc: "Mendukung proses formulasi dan pengembangan produk melalui data hasil pengujian laboratorium yang akurat dan dapat dipertanggungjawabkan.",
  },
  {
    emoji: "📊",
    title: "Data & Analysis",
    desc: "Menghasilkan data pengujian yang terukur sebagai dasar pengambilan keputusan dalam pengembangan dan peningkatan kualitas produk.",
  },
  {
    emoji: "🚀",
    title: "Innovation & Automation",
    desc: "Mengembangkan teknologi otomasi dan digitalisasi laboratorium untuk meningkatkan efisiensi, akurasi, traceability, dan produktivitas pengujian.",
  },
];

const fade = {
  hidden: { opacity: 0, y: 20 },
  show: (i) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, delay: i * 0.07, ease: "easeOut" },
  }),
};

export default function Landing() {
  const navigate = useNavigate();

  return (
    <div data-testid="landing-page" className="min-h-screen bg-zinc-950 text-zinc-50">
      {/* Top navigation */}
      <header className="sticky top-0 z-40 border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur">
        <div className="relative mx-auto flex max-w-7xl items-center justify-between px-6 py-4 lg:px-10">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-md bg-amber-500">
              <Hexagon className="h-5 w-5 text-zinc-950" strokeWidth={2.5} />
            </div>
            <div className="leading-tight">
              <div className="font-heading text-sm font-bold tracking-tight text-zinc-50">
                Laboratorium
              </div>
              <div className="text-[10px] font-medium uppercase tracking-[0.22em] text-amber-500">
                Product Development
              </div>
            </div>
          </div>
          <div className="pointer-events-none absolute left-1/2 hidden max-w-2xl -translate-x-1/2 px-4 text-center lg:block">
            <p className="text-xs font-medium italic tracking-wide text-zinc-300 xl:text-sm">
              Dari Pengujian, Lahir Inovasi.{" "}
              <span className="text-amber-400">Dari Inovasi, Tercipta Pelumas Berkualitas.</span>
            </p>
          </div>
          <Button
            data-testid="nav-signin-btn"
            onClick={() => navigate("/login")}
            className="rounded-md bg-amber-500 font-medium text-zinc-950 hover:bg-amber-400"
          >
            <LogIn className="mr-2 h-4 w-4" /> Masuk
          </Button>
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden border-b border-zinc-800">
        <div
          className="absolute inset-0 opacity-[0.16]"
          style={{ backgroundImage: `url('${HERO_IMG}')`, backgroundSize: "cover", backgroundPosition: "center" }}
        />
        <div className="absolute inset-0 bg-gradient-to-b from-zinc-950/85 via-zinc-950/80 to-zinc-950" />
        <div
          className="absolute inset-0 opacity-[0.04]"
          style={{
            backgroundImage:
              "linear-gradient(#71717a 1px, transparent 1px), linear-gradient(90deg, #71717a 1px, transparent 1px)",
            backgroundSize: "48px 48px",
          }}
        />

        <div className="relative mx-auto grid max-w-7xl items-center gap-12 px-6 py-20 lg:grid-cols-2 lg:px-10 lg:py-28">
          <div>
            <motion.div
              initial="hidden"
              animate="show"
              variants={fade}
              custom={0}
              className="inline-flex max-w-full flex-wrap items-center gap-2 rounded-full border border-zinc-800 bg-zinc-900/70 px-4 py-1.5 text-[11px] font-medium tracking-wide text-zinc-400"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
              Engine Lubricant Testing • Performance Testing • Product Development • Quality Assurance
            </motion.div>

            <motion.h1
              initial="hidden"
              animate="show"
              variants={fade}
              custom={1}
              className="font-heading mt-6 text-4xl font-bold leading-[1.08] tracking-tight text-zinc-50 lg:text-5xl"
            >
              Laboratorium <span className="text-amber-500">Product Development</span>
            </motion.h1>

            <motion.p
              initial="hidden"
              animate="show"
              variants={fade}
              custom={2}
              className="mt-5 max-w-xl text-base leading-relaxed text-zinc-300"
            >
              Laboratorium Product Development menghadirkan pengujian dan evaluasi performa
              pelumas secara komprehensif untuk memastikan setiap formulasi memenuhi standar
              kualitas, keandalan, dan kebutuhan aplikasi mesin.
            </motion.p>

            <motion.p
              initial="hidden"
              animate="show"
              variants={fade}
              custom={3}
              className="mt-4 max-w-xl text-sm font-medium italic leading-relaxed text-amber-400/90"
            >
              Menguji dengan presisi. Mengembangkan dengan inovasi. Menghasilkan pelumas berkualitas.
            </motion.p>
          </div>

          <motion.div
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.6, ease: "easeOut" }}
            className="relative hidden lg:block"
          >
            <div className="overflow-hidden rounded-2xl border border-zinc-800 shadow-2xl shadow-black/40">
              <img src={HERO_IMG} alt="Instrumen uji laboratorium pelumas (DSC analyzer)" className="h-[420px] w-full object-cover" />
            </div>
            <div className="pointer-events-none absolute -inset-2 -z-10 rounded-3xl bg-amber-500/10 blur-2xl" />
          </motion.div>
        </div>
      </section>

      {/* Motto banner */}
      <section className="relative overflow-hidden border-b border-zinc-800 bg-zinc-950">
        <div className="pointer-events-none absolute left-1/2 top-1/2 h-[420px] w-[720px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-amber-500/10 blur-3xl" />
        <div className="relative mx-auto max-w-6xl px-4 py-14 sm:px-6 lg:px-10 lg:py-20">
          <motion.div
            initial={{ opacity: 0, y: 24 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ duration: 0.6, ease: "easeOut" }}
            className="group relative overflow-hidden rounded-2xl border border-zinc-800 shadow-2xl shadow-black/50"
          >
            <img
              src={mottoBanner}
              alt="TEST • ANALYZE • INNOVATE • PERFORM — Mengembangkan pelumas berkualitas melalui pengujian yang akurat, analisis data yang terukur, dan performance testing yang komprehensif. Driving Lubricant Innovation Through Science & Technology."
              className="w-full object-cover transition-transform duration-700 group-hover:scale-[1.02]"
            />
            <div className="pointer-events-none absolute inset-0 ring-1 ring-inset ring-white/5" />
          </motion.div>
        </div>
      </section>

      {/* Our Expertise */}
      <section className="mx-auto max-w-7xl px-6 py-20 lg:px-10">
        <div className="mb-10 text-center">
          <div className="text-[11px] font-semibold uppercase tracking-[0.25em] text-amber-500">
            Our Expertise
          </div>
          <h2 className="font-heading mt-2 text-2xl font-bold tracking-tight text-zinc-50 lg:text-3xl">
            Kompetensi Pengujian &amp; Pengembangan
          </h2>
        </div>

        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {EXPERTISE.map((e, i) => (
            <motion.div
              key={e.title}
              initial="hidden"
              whileInView="show"
              viewport={{ once: true }}
              variants={fade}
              custom={i}
              data-testid={`expertise-card-${i}`}
              className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-6 transition-colors duration-200 hover:border-amber-500/40 hover:bg-zinc-900/70"
            >
              <div className="text-3xl">{e.emoji}</div>
              <h3 className="font-heading mt-4 text-lg font-semibold tracking-tight text-zinc-50">
                {e.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-zinc-400">{e.desc}</p>
            </motion.div>
          ))}

          {/* Quote card fills the 6th slot on lg */}
          <motion.div
            initial="hidden"
            whileInView="show"
            viewport={{ once: true }}
            variants={fade}
            custom={EXPERTISE.length}
            className="flex flex-col justify-center rounded-xl border border-amber-500/30 bg-gradient-to-br from-amber-500/10 to-zinc-900/40 p-6"
          >
            <p className="font-heading text-lg font-semibold leading-relaxed text-amber-300">
              “Dari Pengujian, Lahir Inovasi. Dari Inovasi, Tercipta Pelumas Berkualitas.”
            </p>
          </motion.div>
        </div>
      </section>

      {/* Testing modules */}
      <section className="border-t border-zinc-800 bg-zinc-900/30">
        <div className="mx-auto max-w-7xl px-6 py-20 lg:px-10">
          <div className="mb-10 flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
            <div>
              <div className="text-[11px] font-semibold uppercase tracking-[0.25em] text-amber-500">
                Laboratory Modules
              </div>
              <h2 className="font-heading mt-2 text-2xl font-bold tracking-tight text-zinc-50 lg:text-3xl">
                Tools Pengujian Pelumas
              </h2>
              <p className="mt-2 max-w-2xl text-sm text-zinc-400">
                Pilih modul pengujian. Anda akan diminta masuk (Sign In) terlebih dahulu sebelum
                mengakses halaman pengujian.
              </p>
            </div>
          </div>

          <div className="grid gap-6 md:grid-cols-3">
            {MODULE_LIST.map((m, i) => {
              const Icon = MODULE_ICONS[m.slug] || FlaskConical;
              return (
                <motion.button
                  key={m.slug}
                  initial="hidden"
                  whileInView="show"
                  viewport={{ once: true }}
                  variants={fade}
                  custom={i}
                  data-testid={`module-card-${m.slug}`}
                  onClick={() => navigate(`/${m.slug}`)}
                  className="group flex flex-col rounded-xl border border-zinc-800 bg-zinc-950/60 p-6 text-left transition-colors duration-200 hover:border-amber-500/40 hover:bg-zinc-900/70"
                >
                  <div className="flex h-11 w-11 items-center justify-center rounded-md border border-zinc-800 bg-zinc-950 text-amber-500 transition-colors duration-200 group-hover:border-amber-500/40">
                    <Icon className="h-5 w-5" />
                  </div>
                  <h3 className="font-heading mt-5 text-lg font-semibold tracking-tight text-zinc-50">
                    {m.title}
                  </h3>
                  <p className="mt-2 flex-1 text-sm leading-relaxed text-zinc-400">
                    {m.description}
                  </p>
                  <div className="mt-5 flex items-center gap-2 text-sm font-medium text-amber-500">
                    <ShieldCheck className="h-4 w-4" />
                    Sign In &amp; Mulai
                    <ArrowRight className="h-4 w-4 transition-transform duration-200 group-hover:translate-x-1" />
                  </div>
                </motion.button>
              );
            })}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-zinc-800 bg-zinc-950">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-6 py-8 sm:flex-row lg:px-10">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded bg-amber-500">
              <Hexagon className="h-5 w-5 text-zinc-950" strokeWidth={2.5} />
            </div>
            <div className="text-sm font-semibold text-zinc-200">Laboratorium Product Development</div>
          </div>
          <div className="text-xs text-zinc-500">
            © {new Date().getFullYear()} Laboratorium Product Development · Authorized personnel only
          </div>
        </div>
      </footer>
    </div>
  );
}
