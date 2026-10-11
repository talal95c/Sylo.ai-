import { describe, expect, it } from "vitest";
import { particleSizeBucket, particleSizeForBucket } from "../globeZoom";

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
});
