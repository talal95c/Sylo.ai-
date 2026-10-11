import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ACCENT, CSS_COLOR_VARIABLES, DANGER_COLOR, HOP_COLORS, REFUND_COLOR, TIER_COLORS } from "../colors";

const css = readFileSync(fileURLToPath(new URL("../../app/globals.css", import.meta.url)), "utf8");
const source = readFileSync(fileURLToPath(new URL("../colors.ts", import.meta.url)), "utf8");

describe("WebGL colors", () => {
  it("keeps each literal synchronized with its CSS custom property", () => {
    const variables = new Map(
      [...css.matchAll(/(--[\w-]+):\s*(#[0-9a-fA-F]{6})/g)].map(([, name, value]) => [name, value.toLowerCase()]),
    );
    const literals = {
      ACCENT,
      "HOP_COLORS.bank": HOP_COLORS.bank,
      "HOP_COLORS.chain": HOP_COLORS.chain,
      "HOP_COLORS.wallet": HOP_COLORS.wallet,
      "TIER_COLORS.LOW": TIER_COLORS.LOW,
      "TIER_COLORS.MEDIUM": TIER_COLORS.MEDIUM,
      "TIER_COLORS.HIGH": TIER_COLORS.HIGH,
      "TIER_COLORS.CRITICAL": TIER_COLORS.CRITICAL,
      REFUND_COLOR,
      DANGER_COLOR,
    };

    for (const [name, value] of Object.entries(literals)) {
      expect(variables.get(CSS_COLOR_VARIABLES[name as keyof typeof CSS_COLOR_VARIABLES])).toBe(value.toLowerCase());
    }
    expect(variables.get("--critical")).toBe(variables.get("--danger"));

    expect([...new Set([...source.matchAll(/#[0-9a-fA-F]{6}/g)].map(([value]) => value.toLowerCase()))].sort())
      .toEqual([...new Set(Object.values(literals).map((value) => value.toLowerCase()))].sort());
  });
});
