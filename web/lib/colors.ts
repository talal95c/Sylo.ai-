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
  CRITICAL: "#e5484d",
};

export const REFUND_COLOR = "#f59e0b";
export const DANGER_COLOR = "#e5484d";

export const CSS_HOP_COLORS: Record<HopKind, string> = {
  bank: "var(--bank)",
  chain: "var(--chain)",
  wallet: "var(--wallet)",
};

export const CSS_TIER_COLORS: Record<Tier, string> = {
  LOW: "var(--low)",
  MEDIUM: "var(--medium)",
  HIGH: "var(--high)",
  CRITICAL: "var(--critical)",
};

export const CSS_REFUND_COLOR = "var(--refund)";

export const CSS_COLOR_VARIABLES = {
  ACCENT: "--accent",
  "HOP_COLORS.bank": "--bank",
  "HOP_COLORS.chain": "--chain",
  "HOP_COLORS.wallet": "--wallet",
  "TIER_COLORS.LOW": "--low",
  "TIER_COLORS.MEDIUM": "--medium",
  "TIER_COLORS.HIGH": "--high",
  "TIER_COLORS.CRITICAL": "--critical",
  REFUND_COLOR: "--refund",
  DANGER_COLOR: "--danger",
} as const;
