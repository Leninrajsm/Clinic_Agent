import type { ToolEvent } from "../types";
import { IconAlert, IconCheck, IconShield } from "./icons";
import { Empty, humanize } from "./ui";

type R = Record<string, any>;

/** Plain-language summary of one tool call, so the trace reads like an activity feed. */
function describe(e: ToolEvent): string {
  const a = e.args as R, r = e.result as R;
  if (e.denied_by) return `Blocked: ${humanize(e.denied_by)}`;
  if (r.error) return `${humanize(e.tool)} failed: ${String(r.error).slice(0, 90)}`;
  switch (e.tool) {
    case "verify_patient": return r.verified ? `Identity verified (${r.first_name})` : "Identity didn't match";
    case "resolve_date": return `Date understood as ${r.interpretation}`;
    case "find_slots": {
      const what = a.provider_name || a.specialty || "slots";
      return `Searched ${what}, ${a.date_from}${a.date_to && a.date_to !== a.date_from ? ` → ${a.date_to}` : ""}: ${(r.slots ?? []).length} found`;
    }
    case "hold_slot": return `Held: ${r.pending_summary}`;
    case "request_cancellation": return `Prepared: ${r.pending_summary}`;
    case "confirm_pending_action": return `${humanize(String(r.status))}: ${r.details}`;
    case "discard_pending_action": return "Released the held slot";
    case "list_my_appointments": return `Looked up appointments (${(r.appointments ?? []).length})`;
    case "escalate_to_human": return `Escalated to clinic staff (${a.urgency})`;
    case "get_clinic_info": return `Checked clinic info: ${a.topic}`;
    case "safety_precheck": return `Emergency detected: "${a.matched}"`;
    default: return humanize(e.tool);
  }
}

export function ToolTrace({ events }: { events: ToolEvent[] }) {
  if (!events.length) return <Empty>No activity yet.</Empty>;
  return (
    <ol className="relative space-y-3 border-l border-slate-200 pl-5">
      {events.map((e) => {
        const r = e.result as R;
        const denied = !!e.denied_by;
        const failed = !denied && !!r.error;
        const Icon = denied ? IconShield : failed ? IconAlert : IconCheck;
        const color = denied ? "bg-amber-100 text-amber-700" : failed ? "bg-rose-100 text-rose-600" : "bg-brand-50 text-brand-600";
        return (
          <li key={e.seq} className="relative">
            <span className={`absolute -left-[31px] top-0.5 flex h-5 w-5 items-center justify-center rounded-full ring-4 ring-white ${color}`}>
              <Icon className="h-3 w-3" />
            </span>
            <div className="text-[13px] leading-snug text-slate-700">{describe(e)}</div>
            <details className="group mt-0.5">
              <summary className="cursor-pointer list-none font-mono text-[11px] text-slate-400 hover:text-slate-600">
                {e.tool} · turn {e.turn}
              </summary>
              <pre className="mt-1 max-h-40 overflow-auto rounded-lg bg-slate-50 p-2 font-mono text-[11px] text-slate-600">
                {JSON.stringify({ args: e.args, result: e.result }, null, 2)}
              </pre>
            </details>
          </li>
        );
      })}
    </ol>
  );
}
