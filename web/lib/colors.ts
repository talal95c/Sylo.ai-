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
