// Duotone icon set (soft fill + rounded stroke, 24px grid), so the UI needs no icon dependency.
import type { ReactNode } from "react";

type P = { className?: string };

const icon = (paths: ReactNode, className = "h-5 w-5") => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round"
       strokeLinejoin="round" className={className} aria-hidden="true">
    {paths}
  </svg>
);
// Soft background layer for the duotone look.
const soft = (d: string) => <path d={d} fill="currentColor" stroke="none" opacity={0.14} />;

export const IconChat = ({ className }: P) =>
  icon(<>{soft("M20 11.5a8 8 0 0 1-11.6 7.1L4 19.5l.9-4.2A8 8 0 1 1 20 11.5Z")}
    <path d="M20 11.5a8 8 0 0 1-11.6 7.1L4 19.5l.9-4.2A8 8 0 1 1 20 11.5Z" /><path d="M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01" /></>, className);
export const IconBeaker = ({ className }: P) =>
  icon(<>{soft("M6 15h12l1.6 3.3A1.6 1.6 0 0 1 18.2 21H5.8a1.6 1.6 0 0 1-1.4-2.7L6 15Z")}
    <path d="M9 3h6M10 3v6.2l-5.6 9.1A1.6 1.6 0 0 0 5.8 21h12.4a1.6 1.6 0 0 0 1.4-2.7L14 9.2V3" /><path d="M6.5 15h11" /></>, className);
export const IconLoop = ({ className }: P) =>
  icon(<>{soft("M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16Z")}
    <path d="M4.5 10A8 8 0 0 1 18 6.3L20 8" /><path d="M20 3.5V8h-4.5" /><path d="M19.5 14A8 8 0 0 1 6 17.7L4 16" /><path d="M4 20.5V16h4.5" /></>, className);
export const IconDoc = ({ className }: P) =>
  icon(<>{soft("M6 3h8l5 5v12a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z")}
    <path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8Z" /><path d="M14 3v5h5M9 13h6M9 17h4" /></>, className);
export const IconPlus = ({ className }: P) => icon(<path d="M12 5v14M5 12h14" />, className);
export const IconRefresh = ({ className }: P) =>
  icon(<><path d="M20 11a8 8 0 1 0-2.3 5.7" /><path d="M20 4v7h-7" /></>, className);
export const IconSend = ({ className }: P) =>
  icon(<><path d="M4.5 12 20 4.5 15.5 20l-3.2-6.3L4.5 12Z" fill="currentColor" opacity={0.2} stroke="none" />
    <path d="M4.5 12 20 4.5 15.5 20l-3.2-6.3L4.5 12ZM12.3 13.7 20 4.5" /></>, className);
export const IconShield = ({ className }: P) =>
  icon(<>{soft("M12 3 5 6v5c0 4.4 3 8.4 7 10 4-1.6 7-5.6 7-10V6l-7-3Z")}<path d="M12 3 5 6v5c0 4.4 3 8.4 7 10 4-1.6 7-5.6 7-10V6l-7-3Z" /></>, className);
export const IconCheck = ({ className }: P) => icon(<path d="m5 12.5 4.5 4.5L19 7.5" />, className);
export const IconX = ({ className }: P) => icon(<path d="M6 6l12 12M18 6 6 18" />, className);
export const IconAlert = ({ className }: P) =>
  icon(<>{soft("M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z")}
    <path d="M12 9v4M12 17h.01" /><path d="M10.3 3.9 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" /></>, className);
export const IconChevron = ({ className }: P) => icon(<path d="m9 6 6 6-6 6" />, className);
export const IconChevronDown = ({ className }: P) => icon(<path d="m6 9 6 6 6-6" />, className);
export const IconPlay = ({ className }: P) =>
  icon(<path d="M7 5v14l11-7L7 5Z" fill="currentColor" opacity={0.9} />, className);
export const IconUser = ({ className }: P) =>
  icon(<>{soft("M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z")}<circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>, className);
export const IconUsers = ({ className }: P) =>
  icon(<>{soft("M9 4a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z")}<circle cx="9" cy="7.5" r="3.5" />
    <path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.2a3.5 3.5 0 0 1 0 6.6M18 14.5a6.5 6.5 0 0 1 3.5 5.5" /></>, className);
export const IconSpark = ({ className }: P) =>
  icon(<>{soft("M12 3l2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2L12 3Z")}
    <path d="M12 3l2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2L12 3Z" /></>, className);
export const IconCross = ({ className }: P) =>
  icon(<path d="M9.5 4h5v5.5H20v5h-5.5V20h-5v-5.5H4v-5h5.5V4Z" fill="currentColor" stroke="none" />, className);
