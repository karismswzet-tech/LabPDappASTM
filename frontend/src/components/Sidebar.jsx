import React from "react";
import { NavLink, useLocation } from "react-router-dom";
import { FlaskConical, Beaker, Gauge, Timer, Hexagon, Circle, Palette, LogOut, UserCircle2, Hourglass, ShieldAlert, CloudDrizzle, Droplets } from "lucide-react";
import { MODULE_LIST } from "@/config/modules";
import { KHT_TABS } from "@/pages/kht/KhtLayout";
import { DKA_TABS } from "@/pages/dka/DkaLayout";
import { COPPER_TABS } from "@/pages/copper/CopperLayout";
import { HTCBT_TABS } from "@/pages/htcbt/HtcbtLayout";
import { DKACEC_TABS } from "@/pages/dkacec/DkacecLayout";
import { RUST_TABS } from "@/pages/rust/RustLayout";
import { SALT_TABS } from "@/pages/saltspray/SaltLayout";
import { HUMIDITY_TABS } from "@/pages/humidity/HumidityLayout";
import { useAuth } from "@/context/AuthContext";

const ICONS = {
  khtt: FlaskConical,
  "copper-strip": Beaker,
  "rating-dka": Gauge,
  htcbt: Timer,
  "dka-cec": Hourglass,
  "rust-preventing": ShieldAlert,
  "salt-spray": CloudDrizzle,
  "humidity-cabinet": Droplets,
};

const SUBNAV = {
  khtt: { tabs: [...KHT_TABS, { to: "/khtt/color-scale", label: "Color Scale", icon: Palette }], active: "text-amber-500" },
  "copper-strip": { tabs: [...COPPER_TABS, { to: "/copper-strip/scale", label: "ASTM D130", icon: Palette }], active: "text-amber-400" },
  "rating-dka": { tabs: [...DKA_TABS, { to: "/rating-dka/scale", label: "DKA Standard", icon: Palette }], active: "text-blue-400" },
  htcbt: { tabs: HTCBT_TABS, active: "text-amber-400" },
  "dka-cec": { tabs: DKACEC_TABS, active: "text-blue-400" },
  "rust-preventing": { tabs: RUST_TABS, active: "text-amber-400" },
  "salt-spray": { tabs: SALT_TABS, active: "text-amber-400" },
  "humidity-cabinet": { tabs: HUMIDITY_TABS, active: "text-amber-400" },
};

const SubNav = ({ slug }) => (
  <div className="ml-6 mt-1 flex flex-col gap-0.5 border-l border-zinc-700 pl-3" data-testid={`sidebar-${slug}-subnav`}>
    {SUBNAV[slug].tabs.map((t) => (
      <NavLink
        key={t.to}
        to={t.to}
        end={t.end}
        data-testid={`sidebar-${slug}-${t.label.toLowerCase().replace(" ", "-")}`}
        className={({ isActive }) =>
          `flex items-center gap-2 rounded px-2 py-1.5 font-mono text-[11px] transition-colors ${isActive ? SUBNAV[slug].active : "text-zinc-500 hover:text-zinc-200"}`
        }
      >
        <t.icon className="h-3.5 w-3.5" />
        {t.label}
      </NavLink>
    ))}
  </div>
);

export const Sidebar = () => {
  const { pathname } = useLocation();
  const { user, logout } = useAuth();
  return (
    <aside
      data-testid="app-sidebar"
      className="fixed left-0 top-0 z-30 hidden h-screen w-72 flex-col border-r border-zinc-800 bg-zinc-900 lg:flex"
    >
      <NavLink
        to="/"
        data-testid="sidebar-brand"
        className="flex items-center gap-3 border-b border-zinc-800 px-6 py-6 transition-colors hover:bg-zinc-800/40"
      >
        <div className="relative flex h-10 w-10 items-center justify-center rounded-md bg-amber-500">
          <Hexagon className="h-6 w-6 text-zinc-950" strokeWidth={2.5} />
        </div>
        <div className="leading-tight">
          <div className="font-heading text-lg font-bold tracking-tight text-zinc-50">
            Laboratorium
          </div>
          <div className="text-[10px] font-medium uppercase tracking-[0.25em] text-amber-500">
            Product Development
          </div>
        </div>
      </NavLink>

      <div className="px-4 py-6">
        <div className="mb-3 px-3 text-[10px] font-semibold uppercase tracking-[0.2em] text-zinc-500">
          Laboratory Tools
        </div>
        <nav className="flex flex-col gap-1">
          {MODULE_LIST.map((m) => {
            const Icon = ICONS[m.slug] || Circle;
            return (
              <React.Fragment key={m.slug}>
              <NavLink
                to={`/${m.slug}`}
                data-testid={`nav-${m.slug}`}
                className={({ isActive }) =>
                  `group relative flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors duration-200 ${
                    isActive
                      ? "bg-zinc-800/70 text-zinc-50"
                      : "text-zinc-400 hover:bg-zinc-800/40 hover:text-zinc-100"
                  }`
                }
              >
                {({ isActive }) => (
                  <>
                    <span
                      className={`absolute left-0 top-1/2 h-6 w-[3px] -translate-y-1/2 rounded-r bg-amber-500 transition-opacity duration-200 ${
                        isActive ? "opacity-100" : "opacity-0"
                      }`}
                    />
                    <Icon
                      className={`h-4 w-4 ${
                        isActive ? "text-amber-500" : "text-zinc-500 group-hover:text-zinc-300"
                      }`}
                    />
                    <span className="font-medium">{m.title}</span>
                  </>
                )}
              </NavLink>
              {SUBNAV[m.slug] && pathname.startsWith(`/${m.slug}`) && <SubNav slug={m.slug} />}
              </React.Fragment>
            );
          })}
        </nav>
      </div>

      <div className="mt-auto border-t border-zinc-800 px-4 py-4">
        <div className="mb-3 flex items-center gap-2 rounded-md bg-zinc-800/60 px-3 py-2">
          <UserCircle2 className="h-6 w-6 text-cyan-400" />
          <div className="min-w-0 flex-1">
            <div className="truncate font-mono text-[12px] font-bold text-zinc-100" data-testid="sidebar-username">{user?.username || "admin"}</div>
            <div className="font-mono text-[9px] uppercase tracking-widest text-zinc-500">Administrator</div>
          </div>
        </div>
        <button
          type="button"
          onClick={logout}
          data-testid="logout-button"
          className="flex w-full items-center justify-center gap-2 rounded-md border border-zinc-700 bg-zinc-800 py-2.5 font-mono text-[12px] font-bold tracking-widest text-red-400 transition-colors hover:border-red-500/50 hover:bg-red-500/10"
        >
          <LogOut className="h-4 w-4" /> LOGOUT
        </button>
        <div className="mt-3 text-[10px] uppercase tracking-[0.2em] text-zinc-600">
          v1.0 · Lab Suite
        </div>
        <div className="mt-1 text-xs text-zinc-500">
          © {new Date().getFullYear()} Lab Product Development
        </div>
      </div>
    </aside>
  );
};
