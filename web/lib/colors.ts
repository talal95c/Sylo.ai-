/** Colours of the build spec, section 8.5. */

import type { HopKind, Tier } from "./events";

export const HOP_KIND_COLORS: Record<HopKind, string> = {
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
export const EXCLUDED_COLOR = "#ef4444";
export const CREDITED_COLOR = "#22c55e";
export const DANGER_COLOR = "#ef4444";
export const NEUTRAL_COLOR = "#94a3b8";

export function hopKindColor(kind: string): string {
  return HOP_KIND_COLORS[kind as HopKind] ?? NEUTRAL_COLOR;
}

export function tierColor(tier: Tier | null | undefined): string {
  return (tier && TIER_COLORS[tier]) || NEUTRAL_COLOR;
}

/** "#60a5fa" + 0.25 -> "rgba(96,165,250,0.25)" */
export function withAlpha(hex: string, alpha: number): string {
  const match = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!match) return hex;
  const value = parseInt(match[1], 16);
  const a = Math.min(1, Math.max(0, alpha));
  return `rgba(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255},${a})`;
}
