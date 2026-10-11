import { describe, expect, it } from "vitest";
import { isOnVisibleHemisphere } from "../globeVisibility";

describe("isOnVisibleHemisphere", () => {
  it("keeps a point facing the camera", () => {
    expect(isOnVisibleHemisphere({ lat: 5, lng: -1 }, { lat: 26, lng: 3 })).toBe(true);
  });

  it("hides a point on the far side of the globe", () => {
    expect(isOnVisibleHemisphere({ lat: 5, lng: 179 }, { lat: 26, lng: 3 })).toBe(false);
  });

  it("hides points at or behind the limb threshold", () => {
    expect(isOnVisibleHemisphere({ lat: 0, lng: 87 }, { lat: 0, lng: 0 })).toBe(true);
    expect(isOnVisibleHemisphere({ lat: 0, lng: 88 }, { lat: 0, lng: 0 })).toBe(false);
  });

  it("compares across the antimeridian", () => {
    expect(isOnVisibleHemisphere({ lat: 0, lng: -179 }, { lat: 0, lng: 179 })).toBe(true);
  });
});
