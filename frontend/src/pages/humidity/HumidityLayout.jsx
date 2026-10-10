import React from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { Gauge, PlusCircle, History, TrendingUp, Grid3X3 } from "lucide-react";
import { KhtHeader } from "@/components/kht/ui";

export const HUMIDITY_TABS = [
  { to: "/humidity-cabinet", label: "Dashboard", icon: Gauge, end: true, title: "Humidity Cabinet Test ASTM D1748", subtitle: "Whole-Image 100-Box Inspection" },
  { to: "/humidity-cabinet/new", label: "New Inspection", icon: PlusCircle, title: "New Inspection", subtitle: "ASTM D1748 AI Vision · Seluruh Gambar" },
  { to: "/humidity-cabinet/history", label: "History", icon: History, title: "Inspection History", subtitle: "Humidity cabinet records" },
  { to: "/humidity-cabinet/trend", label: "Trend", icon: TrendingUp, title: "Analytics & Trend", subtitle: "Rusted boxes over time" },
  { to: "/humidity-cabinet/grid-scale", label: "100-Grid Scale", icon: Grid3X3, title: "100-Grid Scale Standard", subtitle: "ASTM D1748 counting reference" },
];

export default function HumidityLayout() {
  const { pathname } = useLocation();
  const active = HUMIDITY_TABS.find((tab) => (tab.end ? pathname === tab.to : pathname.startsWith(tab.to))) || HUMIDITY_TABS[0];
  return (
    <div className="flex min-h-screen flex-col bg-zinc-950" data-testid="humidity-module">
      <KhtHeader title={active.title} subtitle={active.subtitle} logo="HC" accent="amber" />
      <nav className="sticky top-0 z-20 flex overflow-x-auto border-b border-zinc-700 bg-zinc-900/95 backdrop-blur" data-testid="humidity-tabs">
        {HUMIDITY_TABS.map((tab) => (
          <NavLink key={tab.to} to={tab.to} end={tab.end} data-testid={`humidity-tab-${tab.label.toLowerCase().replaceAll(" ", "-")}`} className={({ isActive }) => `relative flex min-w-[120px] flex-1 items-center justify-center gap-2 px-3 py-3 font-mono text-[10px] font-medium tracking-wider transition-colors ${isActive ? "text-amber-400" : "text-zinc-500 hover:text-zinc-200"}`}>
            {({ isActive }) => <><tab.icon className="h-4 w-4" /><span className="hidden sm:inline">{tab.label.toUpperCase()}</span><span className={`absolute bottom-0 left-1/4 right-1/4 h-0.5 rounded-t bg-amber-500 transition-opacity ${isActive ? "opacity-100" : "opacity-0"}`} /></>}
          </NavLink>
        ))}
      </nav>
      <div className="mx-auto w-full max-w-4xl flex-1 px-4 py-6 lg:px-6"><Outlet /></div>
    </div>
  );
}
