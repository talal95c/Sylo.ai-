import { describe, expect, it } from "vitest";
import { altitudeFactor, freeCenter, freeRect, viewOffsetFor, type Occluder } from "../globeFrame";

const W = 1440;
const H = 900;

const leftPanel: Occluder = {
  side: "left",
  rect: { left: 16, right: 356, top: 76, bottom: 812, width: 340, height: 736 },
};
const rightPanel: Occluder = {
  side: "right",
  rect: { left: 1104, right: 1424, top: 76, bottom: 812, width: 320, height: 736 },
};
const collapsedPill: Occluder = {
  side: "right",
  rect: { left: 1240, right: 1424, top: 76, bottom: 160, width: 184, height: 84 },
};
const controlsBar: Occluder = {
  side: "bottom",
  rect: { left: 500, right: 940, top: 804, bottom: 860, width: 440, height: 56 },
};

describe("freeRect", () => {
  it("leaves a margin around panels", () => {
    const rect = freeRect([leftPanel, rightPanel, controlsBar], W, H)!;
    expect(rect.left).toBe(372);
    expect(rect.right).toBe(1088);
    expect(rect.top).toBe(76);
    expect(rect.bottom).toBe(788);
  });

  it("ignores a collapsed right pill", () => {
    const rect = freeRect([leftPanel, collapsedPill, controlsBar], W, H)!;
    expect(rect.right).toBe(W - 16);
  });

  it("returns null when the free strip is too narrow", () => {
    const wide: Occluder = {
      side: "left",
      rect: { left: 0, right: 800, top: 0, bottom: H, width: 800, height: H },
    };
    const wideRight: Occluder = {
      side: "right",
      rect: { left: 1000, right: W, top: 0, bottom: H, width: 440, height: H },
    };
    expect(freeRect([wide, wideRight], W, H)).toBeNull();
  });

  it("uses defaults with no occluders", () => {
    const rect = freeRect([], W, H)!;
    expect(rect).toEqual({ left: 16, right: W - 16, top: 76, bottom: H - 16 });
  });
});

describe("freeCenter / viewOffsetFor", () => {
  it("offsets the projection so the free centre becomes the camera centre", () => {
    const rect = freeRect([leftPanel, rightPanel, controlsBar], W, H)!;
    const { cx, cy } = freeCenter(rect);
    const offset = viewOffsetFor(W, H, cx, cy);
    // cx < W/2 (left panel wider effect) → positive x shifts the look-at left
    expect(cx).toBeCloseTo((372 + 1088) / 2);
    expect(offset.x).toBeCloseTo(W / 2 - cx);
    expect(offset.y).toBeCloseTo(H / 2 - cy);
    // a centred free rect gives no offset
    const centred = viewOffsetFor(W, H, W / 2, H / 2);
    expect(centred).toEqual({ x: 0, y: 0 });
  });
});

describe("altitudeFactor", () => {
  it("is 1 when the free rect fills the canvas", () => {
    const free = { left: 16, right: W - 16, top: 76, bottom: H - 16 };
    expect(altitudeFactor(free, W, H)).toBe(1);
  });

  it("pulls back when panels squeeze the free rect", () => {
    const rect = freeRect([leftPanel, rightPanel, controlsBar], W, H)!;
    const factor = altitudeFactor(rect, W, H);
    expect(factor).toBeGreaterThan(1);
    expect(factor).toBeLessThanOrEqual(1.6);
  });

  it("caps at 1.6 on very narrow free rects", () => {
    const free = { left: 400, right: 1040, top: 300, bottom: 600 };
    expect(altitudeFactor(free, W, H)).toBe(1.6);
  });

  it("is 1 with no free rect", () => {
    expect(altitudeFactor(null, W, H)).toBe(1);
  });
});
