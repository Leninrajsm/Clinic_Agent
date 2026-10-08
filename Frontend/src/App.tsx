import { useQuery } from "@tanstack/react-query";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api/client";
import { IconBeaker, IconChat, IconCross, IconDoc, IconLoop } from "./components/icons";
import ChatPage from "./pages/ChatPage";
import EvalsPage from "./pages/EvalsPage";
import LoopPage from "./pages/LoopPage";
import PoliciesPage from "./pages/PoliciesPage";

const tabs = [
  { to: "/chat", label: "Assistant", icon: IconChat },
  { to: "/evals", label: "Evaluations", icon: IconBeaker },
  { to: "/loop", label: "Improvement", icon: IconLoop },
  { to: "/policies", label: "Policies", icon: IconDoc },
];

function NavItem({ to, label, icon: Icon, dot, compact }: (typeof tabs)[number] & { dot?: boolean; compact?: boolean }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] font-medium transition ${
          isActive ? "bg-white text-brand-900 shadow-sm" : "text-brand-900/70 hover:bg-white/45 hover:text-brand-950"
        } ${compact ? "shrink-0 whitespace-nowrap py-2 text-sm" : ""}`
      }
    >
      <Icon className="h-5 w-5" />
      {label}
      {dot && <span className="ml-auto h-2 w-2 rounded-full bg-amber-500" title="Awaiting your review" />}
    </NavLink>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-3">
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-800 text-white shadow-sm">
        <IconCross className="h-5 w-5" />
      </div>
      <div className="leading-tight">
        <div className="text-[15px] font-bold text-brand-950">Riverside</div>
        <div className="text-xs font-medium text-brand-800/80">Family Clinic</div>
      </div>
    </div>
  );
}

export default function App() {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 15000 });
  const reviewPending = (health.data?.awaiting_review ?? []).length > 0;
  const fullWidth = useLocation().pathname.startsWith("/chat");

  return (
    <div className="min-h-full lg:flex">
      <aside className="hidden bg-brand-300 lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-56 lg:shrink-0 lg:flex-col lg:gap-8 lg:px-4 lg:py-6">
        <div className="px-1"><Brand /></div>
        <nav className="space-y-1">
          {tabs.map((t) => <NavItem key={t.to} {...t} dot={t.to === "/policies" && reviewPending} />)}
        </nav>
      </aside>

      <header className="sticky top-0 z-20 bg-brand-300 px-4 pb-2 pt-3 shadow-sm lg:hidden">
        <Brand />
        <nav className="-mx-1 mt-3 flex gap-1 overflow-x-auto px-1 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {tabs.map((t) => <NavItem key={t.to} {...t} dot={t.to === "/policies" && reviewPending} compact />)}
        </nav>
      </header>

      <main className="min-w-0 flex-1">
        <div className={`px-3 py-4 sm:px-6 lg:px-8 lg:py-6 ${fullWidth ? "" : "mx-auto max-w-6xl lg:py-8"}`}>
          <Routes>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/evals" element={<EvalsPage />} />
            <Route path="/loop" element={<LoopPage />} />
            <Route path="/policies" element={<PoliciesPage />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
