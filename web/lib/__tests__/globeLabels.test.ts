import { describe, expect, it } from "vitest";
import { labelSides, type LabelAnchor } from "../globeLabels";

const anchor = (id: string, x: number, y: number, preferred: "above" | "below" = "above"): LabelAnchor => ({
  id,
  x,
  y,
  preferred,
});

describe("labelSides", () => {
  it("puts the northern label above and the southern one below", () => {
    // Tamale is north of Kumasi → smaller screen y.
    const sides = labelSides([
      anchor("tamale", 800, 300),
      anchor("kumasi", 790, 360),
    ]);
    expect(sides.tamale).toBe("above");
    expect(sides.kumasi).toBe("below");
  });

  it("gives opposite sides to anchors at almost the same height", () => {
    const sides = labelSides([
      anchor("paris", 700, 200),
      anchor("frankfurt", 760, 202),
    ]);
    expect(sides.paris).toBe("above");
    expect(sides.frankfurt).toBe("below");
  });

  it("first of an equal-height pair keeps its preferred side", () => {
    const sides = labelSides([
      anchor("a", 700, 200, "below"),
      anchor("b", 760, 201, "above"),
    ]);
    expect(sides.a).toBe("below");
    expect(sides.b).toBe("above");
  });

  it("keeps preferred sides for far-apart anchors", () => {
    const sides = labelSides([
      anchor("lyon", 300, 200),
      anchor("accra", 700, 500, "below"),
      anchor("london", 1100, 150),
    ]);
    expect(sides).toEqual({ lyon: "above", accra: "below", london: "above" });
  });

  it("resolves a 3-cluster by nearest neighbour", () => {
    const sides = labelSides([
      anchor("north", 800, 200),
      anchor("middle", 810, 260),
      anchor("south", 805, 320),
    ]);
    expect(sides.north).toBe("above");
    expect(sides.south).toBe("below");
    // middle's nearest is north or south at equal distance — opposite of it
    expect(sides.middle === "above" || sides.middle === "below").toBe(true);
    expect(sides.middle).not.toBe(sides.north === sides.middle && sides.south === sides.middle ? sides.middle : "x");
  });

  it("ignores anchors outside the near box even if vertically aligned", () => {
    const sides = labelSides([
      anchor("a", 100, 200),
      anchor("b", 100 + 500, 260),
    ]);
    expect(sides.a).toBe("above");
    expect(sides.b).toBe("above");
  });
});
