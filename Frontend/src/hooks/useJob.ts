import { useEffect, useState } from "react";
import { streamJob } from "../api/client";
import type { JobEvent, JobInfo } from "../types";

/** Live events for a background job: SSE first, falling back to polling if the stream drops. */
export function useJob(jobId: string | null) {
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [info, setInfo] = useState<JobInfo | null>(null);

  useEffect(() => {
    if (!jobId) return;
    setEvents([]);
    setInfo(null);
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      if (stopped) return;
      try {
        const res = await fetch(`/api/jobs/${jobId}`);
        const data = (await res.json()) as JobInfo & { events: JobEvent[] };
        setEvents(data.events);
        if (data.status !== "running") {
          setInfo(data);
          return;
        }
      } catch {
        /* retry */
      }
      timer = setTimeout(poll, 3000);
    };

    const received: JobEvent[] = [];
    const close = streamJob(
      jobId,
      (e) => {
        received.push(e);
        setEvents([...received]);
      },
      (end) => setInfo(end),
    );
    // If the stream errors, EventSource is closed by streamJob; polling picks up from the full log.
    const watchdog = setInterval(async () => {
      if (stopped) return;
      const res = await fetch(`/api/jobs/${jobId}`).catch(() => null);
      if (!res) return;
      const data = (await res.json()) as JobInfo & { events: JobEvent[] };
      if (data.events.length > received.length + 2 || data.status !== "running") {
        clearInterval(watchdog);
        close();
        poll();
      }
    }, 10000);

    return () => {
      stopped = true;
      close();
      clearInterval(watchdog);
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  return { events, info, running: !!jobId && !info };
}
