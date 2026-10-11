export type ParticleSizeBucket = "near" | "middle" | "far";

export function particleSizeBucket(altitude: number): ParticleSizeBucket {
  if (altitude < 1.3) return "near";
  if (altitude < 1.9) return "middle";
  return "far";
}

export function particleSizeForBucket(bucket: ParticleSizeBucket, baseSize: number) {
  if (bucket === "near") return baseSize * 1.55;
  if (bucket === "middle") return baseSize * 1.2;
  return baseSize;
}

export function scaleAnimationDuration(durationMs: number, speed: number) {
  return durationMs / Math.max(1, speed);
}
