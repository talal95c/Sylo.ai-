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
      {index ? <span className="text-ink-3">•</span> : null}
      {children}
    </span>
  );
}

export function Metric({
  label,
  value,
  sub,
  color = "var(--accent)",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  color?: string;
}) {
  return (
    <div className="border-l-2 pl-3" style={{ borderColor: color }}>
      <div className="text-[17px] font-medium leading-tight tracking-[-0.03em] tabular-nums">
        {value}
      </div>
      <div className="mt-0.5 text-[12px] text-ink-2">{label}</div>
      {sub ? <div className="mt-0.5 text-[11px] text-ink-3">{sub}</div> : null}
    </div>
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
