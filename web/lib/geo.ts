export interface Institution {
  id: string;
  name: string;
  short: string;
  kind: string;
  city: string;
  country: string;
  lat: number;
  lng: number;
}

export interface Geo {
  chain: { name: string; arcAltitude: number };
  institutions: Institution[];
}

export interface LatLng {
  lat: number;
  lng: number;
}

export async function loadGeo(): Promise<Geo> {
  const response = await fetch("/spec/geo/institutions.json");
  if (!response.ok) {
    throw new Error(`institutions.json: HTTP ${response.status} (run pnpm sync-spec)`);
  }
  return (await response.json()) as Geo;
}

export function indexInstitutions(geo: Geo | null): Record<string, Institution> {
  const index: Record<string, Institution> = {};
  for (const institution of geo?.institutions ?? []) index[institution.id] = institution;
  return index;
}

/** Display names for the feed and the card; ids are shown as-is when the geography is missing. */
export function shortNames(geo: Geo | null): Record<string, string> {
  const names: Record<string, string> = {};
  for (const institution of geo?.institutions ?? []) names[institution.id] = institution.short;
  return names;
}

const toRad = (deg: number) => (deg * Math.PI) / 180;
const toDeg = (rad: number) => (rad * 180) / Math.PI;

/** Midpoint of the great circle between two points: where an arc's apex sits. */
export function greatCircleMidpoint(a: LatLng, b: LatLng): LatLng {
  const phi1 = toRad(a.lat);
  const phi2 = toRad(b.lat);
  const lambda1 = toRad(a.lng);
  const deltaLambda = toRad(b.lng - a.lng);
  const bx = Math.cos(phi2) * Math.cos(deltaLambda);
  const by = Math.cos(phi2) * Math.sin(deltaLambda);
  const phi = Math.atan2(Math.sin(phi1) + Math.sin(phi2), Math.sqrt((Math.cos(phi1) + bx) ** 2 + by ** 2));
  const lambda = lambda1 + Math.atan2(by, Math.cos(phi1) + bx);
  return { lat: toDeg(phi), lng: ((toDeg(lambda) + 540) % 360) - 180 };
}

/** Angular distance in radians. */
export function angularDistance(a: LatLng, b: LatLng): number {
  const dPhi = toRad(b.lat - a.lat);
  const dLambda = toRad(b.lng - a.lng);
  const h = Math.sin(dPhi / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLambda / 2) ** 2;
  return 2 * Math.asin(Math.min(1, Math.sqrt(h)));
}
