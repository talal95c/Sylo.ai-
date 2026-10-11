import { describe, expect, it } from "vitest";
import { arcDotPositions, globeVector } from "../arcDots";

const lyon = { lat: 45.76, lng: 4.84 };
const accra = { lat: 5.6, lng: -0.19 };
const frankfurt = { lat: 50.11, lng: 8.68 };

function gaps(points: { distanceTo(other: never): number }[]) {
  return points.slice(1).map((point, index) => point.distanceTo(points[index] as never));
}

describe("arcDotPositions", () => {
  it("starts and ends on the two institutions", () => {
    const points = arcDotPositions(lyon, accra, null, 1.2);
    expect(points[0].distanceTo(globeVector(lyon.lat, lyon.lng))).toBeLessThan(1e-6);
    expect(points.at(-1)!.distanceTo(globeVector(accra.lat, accra.lng))).toBeLessThan(1e-6);
  });

  it("spaces dots evenly along raised and chain arcs", () => {
    for (const altitude of [null, 0.18]) {
      const spacing = gaps(arcDotPositions(lyon, accra, altitude, 1.2));
      const min = Math.min(...spacing);
      const max = Math.max(...spacing);
      expect(max / min).toBeLessThan(1.03);
      expect(spacing.reduce((sum, gap) => sum + gap, 0) / spacing.length).toBeCloseTo(1.2, 0);
    }
  });

  it("keeps the same pitch on short and long hops", () => {
    const short = gaps(arcDotPositions(lyon, frankfurt, null, 1.2));
    const long = gaps(arcDotPositions(lyon, accra, null, 1.2));
    expect(Math.abs(short[0] - long[0]) / long[0]).toBeLessThan(0.15);
  });
});
