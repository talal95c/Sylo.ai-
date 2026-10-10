/**
 * Geography: the fictional institutions of spec/geo/institutions.json and great-circle helpers.
 *
 * The JSON is the copy made by scripts/sync-spec.mjs (public/spec is git-ignored): /spec stays the
 * only source of truth.
 */

import raw from "../public/spec/geo/institutions.json";

export interface Institution {
  id: string;
  name: string;
  kind: string;
  city: string;
  country: string;
  lat: number;
  lng: number;
}

export interface LatLng {
  lat: number;
  lng: number;
}

export const INSTITUTIONS: readonly Institution[] = raw.institutions;
export const CHAIN: { name: string; arcAltitude: number } = raw.chain;

const BY_ID = new Map<string, Institution>(INSTITUTIONS.map((item) => [item.id, item]));

export function institution(id: string | null | undefined): Institution | undefined {
  return id ? BY_ID.get(id) : undefined;
}

/** Display name of an institution; falls back to the id when the geography does not know it. */
export function institutionName(id: string | null | undefined): string {
  if (!id) return "";
  const found = BY_ID.get(id);
  return found ? found.name.replace(/\s*\([^)]*\)\s*$/, "") : id;
}

// ---------------------------------------------------------------- great circles

const RAD = Math.PI / 180;

function toVector({ lat, lng }: LatLng): [number, number, number] {
  const phi = lat * RAD;
  const lambda = lng * RAD;
  return [Math.cos(phi) * Math.cos(lambda), Math.cos(phi) * Math.sin(lambda), Math.sin(phi)];
}

/** Angle between two points seen from the centre of the globe, in radians. */
export function angularDistance(a: LatLng, b: LatLng): number {
  const [ax, ay, az] = toVector(a);
  const [bx, by, bz] = toVector(b);
  return Math.acos(Math.min(1, Math.max(-1, ax * bx + ay * by + az * bz)));
}

/** Point at fraction t (0..1) of the great circle from a to b. */
export function greatCircleInterpolate(a: LatLng, b: LatLng, t: number): LatLng {
  const angle = angularDistance(a, b);
  if (angle < 1e-9) return { lat: a.lat, lng: a.lng };
  const va = toVector(a);
  const vb = toVector(b);
  const wa = Math.sin((1 - t) * angle) / Math.sin(angle);
  const wb = Math.sin(t * angle) / Math.sin(angle);
  const x = wa * va[0] + wb * vb[0];
  const y = wa * va[1] + wb * vb[1];
  const z = wa * va[2] + wb * vb[2];
  return { lat: Math.atan2(z, Math.hypot(x, y)) / RAD, lng: Math.atan2(y, x) / RAD };
}

export function greatCircleMidpoint(a: LatLng, b: LatLng): LatLng {
  return greatCircleInterpolate(a, b, 0.5);
}

/**
 * Arc altitude of a hop, in globe radii: the chain hop flies at `chain.arcAltitude` (0.45), the
 * other hops stay low, in proportion to their length (the default of three-globe, with a floor).
 */
export function hopAltitude(kind: string, a: LatLng, b: LatLng): number {
  if (kind === "chain") return CHAIN.arcAltitude;
  return Math.max(0.02, angularDistance(a, b) / 4);
}

/**
 * Altitude of the highest point of the arc that three-globe draws for `altitude`: a cubic Bézier
 * whose two control points sit at 1.5 x altitude above the quarter points of the great circle.
 * For the chain hop this is about 0.46 above the great-circle midpoint (spec: "altitude 0.45").
 */
export function arcApexAltitude(a: LatLng, b: LatLng, altitude: number): number {
  const angle = angularDistance(a, b);
  return (Math.cos(angle / 2) + 3 * (1 + 1.5 * altitude) * Math.cos(angle / 4)) / 4 - 1;
}
