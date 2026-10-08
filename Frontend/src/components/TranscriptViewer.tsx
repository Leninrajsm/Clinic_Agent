import type { ReactNode } from "react";
import type { TranscriptLine } from "../types";
import { IconCross } from "./icons";

export function AgentAvatar({ size = "h-8 w-8" }: { size?: string }) {
  return (
    <div className={`flex ${size} shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-600 to-brand-800 text-white`}>
      <IconCross className="h-4 w-4" />
    </div>
  );
}

export function Bubble({ role, text, children }: { role: "patient" | "agent"; text: string; children?: ReactNode }) {
  if (role === "patient") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[min(78%,44rem)] whitespace-pre-wrap rounded-2xl rounded-br-md bg-brand-700 px-4 py-2.5 text-sm leading-relaxed text-white shadow-sm">
          {text}
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-end gap-2.5">
      <AgentAvatar />
      <div className="max-w-[min(78%,44rem)]">
        <div className="whitespace-pre-wrap rounded-2xl rounded-bl-md bg-white px-4 py-2.5 text-sm leading-relaxed text-slate-800 shadow-sm ring-1 ring-slate-200/80">
          {text.replace(/\*\*(.+?)\*\*/g, "$1")}
        </div>
        {children}
      </div>
    </div>
  );
}

export function TranscriptViewer({ lines }: { lines: TranscriptLine[] }) {
  return (
    <div className="space-y-3 rounded-xl bg-slate-50 p-4">
      {lines.map((l, i) => <Bubble key={i} role={l.role} text={l.text} />)}
    </div>
  );
}
