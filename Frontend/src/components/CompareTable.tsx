import type { CompareRow } from "../types";
import { Badge, ChangeBadge, humanize, pct } from "./ui";

export function CompareTable({ rows, before, after }: { rows: CompareRow[]; before: string; after: string }) {
  const order: Record<string, number> = { FIXED: 0, REGRESSED: 1, improved: 2, worse: 3, error: 4, same: 5 };
  const sorted = [...rows].sort((x, y) => (order[x.change] ?? 9) - (order[y.change] ?? 9));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400">
            <th className="px-5 py-2.5">Scenario</th>
            <th className="py-2.5 pr-4 text-right">{before}</th>
            <th className="py-2.5 pr-4 text-right">{after}</th>
            <th className="py-2.5 pr-5">Change</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {sorted.map((r) => (
            <tr key={r.scenario_id} className={r.change === "FIXED" ? "bg-emerald-50/50" : r.change === "REGRESSED" ? "bg-rose-50/50" : ""}>
              <td className="px-5 py-2.5">
                <span className="font-medium text-slate-700">{humanize(r.scenario_id)}</span>
                {r.split === "holdout" && <span className="ml-2"><Badge tone="sky">holdout</Badge></span>}
              </td>
              <td className={`py-2.5 pr-4 text-right tabular-nums ${r.before_passed ? "text-emerald-700" : "text-rose-600"}`}>{pct(r.before_pass_rate)}</td>
              <td className={`py-2.5 pr-4 text-right tabular-nums ${r.after_passed ? "text-emerald-700" : "text-rose-600"}`}>{pct(r.after_pass_rate)}</td>
              <td className="py-2.5 pr-5"><ChangeBadge change={r.change} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
