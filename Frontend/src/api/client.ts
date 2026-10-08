import type {
  ClinicInfo,
  Health,
  JobEvent,
  JobInfo,
  LoopListItem,
  LoopReport,
  NewSessionResponse,
  PolicyVersion,
  RunListItem,
  RunResult,
  Scenario,
  TurnResult,
} from "../types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body: unknown = {}) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => request<Health>("/health"),
  clinic: () => request<ClinicInfo>("/clinic"),
  resetDemo: () => post<Record<string, number>>("/demo/reset"),

  newSession: (policy_version?: string) => post<NewSessionResponse>("/sessions", { policy_version }),
  sendMessage: (sessionId: string, text: string) =>
    post<TurnResult>(`/sessions/${sessionId}/messages`, { text }),

  scenarios: () => request<Scenario[]>("/scenarios"),
  runs: () => request<RunListItem[]>("/evals/runs"),
  run: (id: string) => request<RunResult>(`/evals/runs/${id}`),
  startEval: (body: { policy_version?: string; trials?: number; scenario_ids?: string[] }) =>
    post<JobInfo>("/evals/runs", body),

  loops: () => request<LoopListItem[]>("/loops"),
  loop: (id: string) => request<LoopReport>(`/loops/${id}`),
  startLoop: (body: {
    trials?: number;
    max_attempts?: number;
    baseline_run_id?: string;
    scenario_ids?: string[];
    review?: boolean;
  }) => post<JobInfo>("/loop", body),

  policies: () => request<{ active: string; versions: PolicyVersion[] }>("/policies"),
  policy: (v: string) => request<PolicyVersion & { content: string }>(`/policies/${v}`),
  diff: (oldV: string, newV: string) =>
    request<{ diff: string }>(`/policy-diff?old=${encodeURIComponent(oldV)}&new=${encodeURIComponent(newV)}`),
  activate: (v: string) => post<{ active: string }>(`/policies/${v}/activate`),
  approve: (v: string) => post<{ active: string }>(`/policies/${v}/approve`),
  reject: (v: string) => post<{ rejected: string }>(`/policies/${v}/reject`),
};

/** Subscribe to a job's server-sent events. Returns an unsubscribe function. */
export function streamJob(
  jobId: string,
  onEvent: (e: JobEvent) => void,
  onEnd: (info: JobInfo) => void,
): () => void {
  const source = new EventSource(`/api/jobs/${jobId}/events`);
  source.onmessage = (msg) => onEvent(JSON.parse(msg.data));
  source.addEventListener("end", (msg) => {
    onEnd(JSON.parse((msg as MessageEvent).data));
    source.close();
  });
  source.onerror = () => {
    // EventSource retries automatically; the server replays the full event log on reconnect,
    // so we close and let the caller re-subscribe instead of receiving duplicates.
    source.close();
  };
  return () => source.close();
}
