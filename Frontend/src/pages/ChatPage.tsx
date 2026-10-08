import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { IconPlus, IconSend } from "../components/icons";
import { AgentAvatar, Bubble } from "../components/TranscriptViewer";
import { ErrorNote } from "../components/ui";

interface Line {
  role: "patient" | "agent";
  text: string;
}

const SUGGESTIONS = [
  "Book a dermatology appointment next Friday",
  "I need to move my appointment",
  "Cancel my appointment",
  "What are your opening hours?",
];

export default function ChatPage() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [text, setText] = useState("");
  const bottom = useRef<HTMLDivElement>(null);

  const start = useMutation({
    mutationFn: () => api.newSession(),
    onSuccess: (s) => {
      setSessionId(s.session_id);
      setLines([{ role: "agent", text: s.greeting }]);
    },
  });

  const send = useMutation({
    mutationFn: (msg: string) => api.sendMessage(sessionId!, msg),
    onMutate: (msg) => setLines((l) => [...l, { role: "patient", text: msg }]),
    onSuccess: (r) => setLines((l) => [...l, { role: "agent", text: r.reply }]),
  });

  const started = useRef(false); // StrictMode runs effects twice in dev; start only one session
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    start.mutate();
  }, []);

  useEffect(() => {
    // Block body on purpose: newer browsers make scrollIntoView return a Promise, and an effect
    // must return nothing (or a clean-up function).
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines, send.isPending]);

  const submit = (msg: string) => {
    const m = msg.trim();
    if (!m || !sessionId || send.isPending) return;
    setText("");
    send.mutate(m);
  };
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    submit(text);
  };

  return (
    <div className="card flex h-[calc(100dvh-8.5rem)] min-h-[480px] flex-col overflow-hidden lg:h-[calc(100dvh-3rem)]">
      <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-3.5 sm:px-6">
        <div className="flex items-center gap-3">
          <AgentAvatar size="h-11 w-11" />
          <div>
            <div className="text-[15px] font-semibold text-slate-900">Clinic Assistant</div>
            <div className="flex items-center gap-1.5 text-xs font-medium text-emerald-700">
              <span className="h-2 w-2 rounded-full bg-emerald-500 ring-2 ring-emerald-100" />
              Online
            </div>
          </div>
        </div>
        <button className="btn-icon" title="New conversation" onClick={() => start.mutate()} disabled={start.isPending}>
          <IconPlus className="h-5 w-5" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto bg-gradient-to-b from-brand-50 to-white px-4 py-6 sm:px-8 lg:px-12">
        <div className="space-y-4">
          {lines.map((l, i) => <Bubble key={i} role={l.role} text={l.text} />)}
          {send.isPending && (
            <div className="flex items-end gap-2.5">
              <AgentAvatar />
              <div className="flex gap-1 rounded-2xl rounded-bl-md bg-white px-4 py-3.5 shadow-sm ring-1 ring-slate-200/80">
                <span className="typing-dot h-1.5 w-1.5 rounded-full bg-brand-600" />
                <span className="typing-dot h-1.5 w-1.5 rounded-full bg-brand-600" />
                <span className="typing-dot h-1.5 w-1.5 rounded-full bg-brand-600" />
              </div>
            </div>
          )}
          {lines.length === 1 && !send.isPending && (
            <div className="flex flex-wrap gap-2 sm:pl-[2.6rem]">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => submit(s)}
                        className="rounded-full bg-white px-3.5 py-2 text-[13px] font-medium text-slate-600 ring-1 ring-slate-200 transition hover:bg-brand-50 hover:text-brand-800 hover:ring-brand-300">
                  {s}
                </button>
              ))}
            </div>
          )}
          <div ref={bottom} />
        </div>
      </div>

      <div className="border-t border-slate-100 p-3 sm:px-6 sm:py-4">
        <ErrorNote error={send.error || start.error} />
        <form onSubmit={onSubmit}
              className="flex items-center gap-2 rounded-2xl bg-slate-50 p-1.5 ring-1 ring-slate-200 transition focus-within:bg-white focus-within:ring-2 focus-within:ring-brand-500">
          <input
            className="min-w-0 flex-1 bg-transparent px-3 py-2.5 text-[15px] outline-none placeholder:text-slate-400"
            placeholder={sessionId ? "Type your message…" : "Connecting…"}
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={!sessionId}
            autoFocus
          />
          <button className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-700 text-white shadow-sm transition hover:bg-brand-800 disabled:opacity-40"
                  disabled={!text.trim() || send.isPending || !sessionId} title="Send">
            <IconSend className="h-[18px] w-[18px]" />
          </button>
        </form>
        <p className="mt-2 text-center text-[11px] text-slate-400">
          For emergencies, call 911. This assistant can't give medical advice.
        </p>
      </div>
    </div>
  );
}
