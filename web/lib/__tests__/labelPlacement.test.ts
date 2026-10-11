import { describe, expect, it } from "vitest";
import { resolveLabelOverlap, type LabelRect } from "../labelPlacement";

const bounds: LabelRect = { left: 0, right: 200, top: 0, bottom: 120 };

describe("resolveLabelOverlap", () => {
  it("keeps the preferred side when it does not overlap", () => {
    const result = resolveLabelOverlap(
      { left: 80, right: 120, top: 30, bottom: 50 },
      { left: 80, right: 120, top: 40, bottom: 60 },
      [{ left: 5, right: 45, top: 5, bottom: 25 }],
      bounds,
      "above",
    );
    expect(result).toEqual({ side: "above", shiftX: 0, hidden: false });
  });

  it("flips to the alternate side when that avoids a collision", () => {
    const result = resolveLabelOverlap(
      { left: 80, right: 120, top: 15, bottom: 35 },
      { left: 80, right: 120, top: 55, bottom: 75 },
      [{ left: 70, right: 130, top: 12, bottom: 38 }],
      bounds,
      "above",
    );
    expect(result).toEqual({ side: "below", shiftX: 0, hidden: false });
  });

  it("shifts a lower-priority label beside the collision", () => {
    const result = resolveLabelOverlap(
      { left: 80, right: 120, top: 40, bottom: 60 },
      { left: 80, right: 120, top: 40, bottom: 60 },
      [{ left: 70, right: 130, top: 38, bottom: 62 }],
      bounds,
      "above",
    );
    expect(result).toMatchObject({ side: "above", shiftX: 0, hidden: false });
    expect(result.shiftX).not.toBe(0);
  });

  it("hides only when both sides and horizontal offsets collide", () => {
    const result = resolveLabelOverlap(
      { left: 0, right: 40, top: 40, bottom: 60 },
      { left: 0, right: 40, top: 40, bottom: 60 },
      [
        { left: 0, right: 50, top: 35, bottom: 65 },
        { left: 50, right: 100, top: 35, bottom: 65 },
      ],
      { left: 0, right: 100, top: 0, bottom: 100 },
      "above",
    );
    expect(result.hidden).toBe(true);
  });
});
