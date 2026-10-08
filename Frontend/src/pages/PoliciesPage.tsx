import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { IconAlert, IconCheck } from "../components/icons";
import { PolicyDiff } from "../components/PolicyDiff";
import { Badge, Card, ErrorNote, PageHeader, Tabs, shortDate } from "../components/ui";

const statusTone = {
  active: "green", candidate: "violet", awaiting_review: "amber", rejected: "red", superseded: "slate",
} as const;

export default function PoliciesPage() {
  const qc = useQueryClient();
  const policies = useQuery({ queryKey: ["policies"], queryFn: api.policies });
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<"changes" | "full">("changes");
  const pending = policies.data?.versions.filter((v) => v.status === "awaiting_review") ?? [];
  const version = selected ?? pending[0]?.version ?? policies.data?.active ?? null;
  const meta = policies.data?.versions.find((v) => v.version === version);
  const content = useQuery({ queryKey: ["policy", version], queryFn: () => api.policy(version!), enabled: !!version });
  const diff = useQuery({
    queryKey: ["diff", meta?.parent, version],
    queryFn: () => api.diff(meta!.parent!, version!),
    enabled: !!meta?.parent,
  });
  const done = { onSuccess: () => qc.invalidateQueries() };
  const activate = useMutation({ mutationFn: (v: string) => api.activate(v), ...done });
  const approve = useMutation({ mutationFn: (v: string) => api.approve(v), ...done });
  const reject = useMutation({ mutationFn: (v: string) => api.reject(v), ...done });
  const busy = activate.isPending || approve.isPending || reject.isPending;
  const showChanges = view === "changes" && !!meta?.parent;

  return (
    <div>
      <PageHeader
        title="Policies"
        subtitle="The agent's behaviour rules. Each improvement is a new version, so you can always see what changed and roll back instantly. The safety rules live in code and a locked file the loop can't edit."
      />
      {pending.length > 0 && (
        <div className="mb-5 flex items-center gap-2 rounded-2xl bg-amber-50 px-4 py-3 text-sm text-amber-900 ring-1 ring-amber-200">
          <IconAlert className="h-4 w-4 shrink-0" />
          <span><b>{pending.map((p) => p.version).join(", ")}</b> passed the regression gate and is waiting for your
            review. Patients keep getting the live version until you approve.</span>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
        <div className="space-y-2">
          <div className="label px-1">Versions</div>
          {policies.data?.versions.slice().reverse().map((v) => (
            <button key={v.version} onClick={() => setSelected(v.version)}
                    className={`card w-full px-4 py-3 text-left transition hover:ring-brand-300 ${v.version === version ? "ring-2 ring-brand-500" : ""}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-slate-900">{v.version}</span>
                <Badge tone={statusTone[v.status]}>{v.status.replace("_", " ")}</Badge>
              </div>
              <div className="mt-1 text-xs text-slate-400">
                {v.parent ? `from ${v.parent} · ` : "hand-written baseline · "}{shortDate(v.created_at)}
              </div>
            </button>
          ))}
        </div>

        {meta && (
          <Card
            title={<span className="flex items-center gap-2">Policy {meta.version} <Badge tone={statusTone[meta.status]}>{meta.status.replace("_", " ")}</Badge></span>}
            right={
              meta.status === "awaiting_review" ? (
                <div className="flex gap-2">
                  <button className="btn-ghost" onClick={() => reject.mutate(meta.version)} disabled={busy}>Reject</button>
                  <button className="btn-primary" onClick={() => approve.mutate(meta.version)} disabled={busy}>
                    <IconCheck className="h-4 w-4" /> Approve &amp; go live
                  </button>
                </div>
              ) : meta.status !== "active" ? (
                <button className="btn-ghost" onClick={() => activate.mutate(meta.version)} disabled={busy}>Make live</button>
              ) : <Badge tone="green">Serving patients</Badge>
            }
          >
            <div className="space-y-4">
              <ErrorNote error={activate.error || approve.error || reject.error} />
              {meta.parent && (
                <Tabs value={view} onChange={setView}
                      tabs={[{ id: "changes", label: `Changes from ${meta.parent}` }, { id: "full", label: "Full policy" }]} />
              )}
              {showChanges
                ? <PolicyDiff diff={diff.data?.diff ?? ""} />
                : <pre className="whitespace-pre-wrap rounded-xl bg-slate-50 p-4 font-sans text-sm leading-relaxed text-slate-700">{content.data?.content}</pre>}
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
