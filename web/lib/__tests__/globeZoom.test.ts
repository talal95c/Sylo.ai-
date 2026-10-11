import { describe, expect, it } from "vitest";
import { particleSizeBucket, particleSizeForBucket, scaleAnimationDuration } from "../globeZoom";

describe("particle size zoom buckets", () => {
  it("maps altitude to three stable buckets", () => {
    expect(particleSizeBucket(1.1)).toBe("near");
    expect(particleSizeBucket(1.7)).toBe("middle");
    expect(particleSizeBucket(2.1)).toBe("far");
  });

  it("uses one particle size per bucket", () => {
    expect(particleSizeForBucket("near", 0.1)).toBeCloseTo(0.155);
    expect(particleSizeForBucket("middle", 0.1)).toBeCloseTo(0.12);
    expect(particleSizeForBucket("far", 0.1)).toBe(0.1);
  });

  it("divides arc durations by replay speed", () => {
    expect(scaleAnimationDuration(1500, 1)).toBe(1500);
    expect(scaleAnimationDuration(1500, 2)).toBe(750);
    expect(scaleAnimationDuration(1500, 0)).toBe(1500);
  });
});
