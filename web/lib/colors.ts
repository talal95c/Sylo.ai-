import type { HopKind, Tier } from "./events";

export const HOP_COLORS: Record<HopKind, string> = {
  bank: "#60a5fa",
  chain: "#a855f7",
  wallet: "#34d399",
};

export const TIER_COLORS: Record<Tier, string> = {
  LOW: "#22c55e",
  MEDIUM: "#f59e0b",
  HIGH: "#f97316",
  CRITICAL: "#ef4444",
};

export const REFUND_COLOR = "#fbbf24";
export const DANGER_COLOR = "#ef4444";
export const SAFE_COLOR = "#22c55e";
export const SIGNAL_COLOR = "#7dd3fc";

export function withAlpha(hex: string, alpha: number): string {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function tierColor(tier: Tier | null | undefined): string {
  return tier ? TIER_COLORS[tier] : SIGNAL_COLOR;
}
