"use client";

import type { ReactNode } from "react";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

export function Tag({
  index,
  children,
  icon,
  className,
}: {
  index?: string;
  children: ReactNode;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex h-7 items-center gap-1.5 rounded-full border border-[var(--line-strong)] bg-white px-3 text-[12px] font-medium tracking-[-0.02em] text-ink",
        className,
      )}
    >
      {icon}
      {index ? <span className="font-mono text-[10.5px] text-ink-3">{index}</span> : null}
      {index ? <span className="text-ink-3">·</span> : null}
      {children}
    </span>
  );
}

export function PanelHeaderButton({
  index,
  title,
  meta,
  expanded,
  controls,
  onToggle,
  sticky,
}: {
  index: string;
  title: string;
  meta: string;
  expanded: boolean;
  controls: string;
  onToggle: () => void;
  sticky?: boolean;
}) {
  return (
    <button
      type="button"
      aria-expanded={expanded}
      aria-controls={controls}
      onClick={onToggle}
      className={cx(
        "z-10 flex w-full shrink-0 items-center justify-between gap-3 rounded-t-[18px] bg-white px-4 pb-2.5 pt-4 text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent",
        sticky && "sticky top-0",
      )}
    >
      <Tag index={index}>{title}</Tag>
      <span className="ml-auto font-mono text-[10px] tabular-nums text-ink-3">{meta}</span>
      <svg
        className={cx("shrink-0 text-ink-3 transition-transform duration-200 motion-reduce:transition-none", expanded && "rotate-180")}
        width="14"
        height="14"
        viewBox="0 0 14 14"
        fill="none"
        aria-hidden
      >
        <path d="m3.5 5.25 3.5 3.5 3.5-3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  );
}

export function Spinner({ size = 16, color = "var(--accent)" }: { size?: number; color?: string }) {
  return (
    <svg className="spinner" width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden>
      <circle cx="8" cy="8" r="6.5" stroke={color} strokeOpacity="0.18" strokeWidth="1.5" />
      <path d="M8 1.5a6.5 6.5 0 0 1 6.5 6.5" stroke={color} strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

export function Check({ size = 16, color = "var(--low)" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M3 8.4 6.4 11.6 13 4.6" stroke={color} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Dot({ color, pulse }: { color: string; pulse?: boolean }) {
  return (
    <span
      className={cx("inline-block size-1.5 shrink-0 rounded-full", pulse && "pulse-dot")}
      style={{ background: color, color }}
    />
  );
}

export function LockIcon({ open, size = 16 }: { open?: boolean; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="none" aria-hidden>
      <rect x="3" y="7" width="10" height="7" rx="2" stroke="currentColor" strokeWidth="1.5" />
      <path
        d={open ? "M5.5 7V5a2.5 2.5 0 0 1 4.9-.7" : "M5.5 7V5a2.5 2.5 0 0 1 5 0v2"}
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function shortHash(hash?: string | null, head = 6, tail = 4) {
  if (!hash) return "";
  return `${hash.slice(0, head)}…${hash.slice(-tail)}`;
}

export function formatMoney(value: string | number, currency = "EUR") {
  const amount = typeof value === "number" ? value : Number(value);
  return `${currency} ${amount.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

export function euros(value: number) {
  return `€${value.toLocaleString("en-US", { minimumFractionDigits: value % 1 ? 2 : 0, maximumFractionDigits: 2 })}`;
}

export const ease = [0.22, 1, 0.36, 1] as const;
