import type { HopKind, Tier } from "./events";

export const ACCENT = "#012bff";

export const HOP_COLORS: Record<HopKind, string> = {
  bank: "#3b6bff",
  chain: "#8b5cf6",
  wallet: "#10b981",
};

export const TIER_COLORS: Record<Tier, string> = {
  LOW: "#16a34a",
  MEDIUM: "#d97706",
  HIGH: "#ea580c",
  CRITICAL: "#dc2626",
};

export const REFUND_COLOR = "#f59e0b";
export const DANGER_COLOR = "#e5484d";

export const IRIDESCENT =
  "linear-gradient(90deg, #c9aaff 0%, #fdffbc 25%, #ffccfd 50%, #b3e1ff 75%, #8399ff 100%)";
