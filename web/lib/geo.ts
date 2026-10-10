import type { InstitutionId } from "./events";

export interface Institution {
  id: InstitutionId;
  name: string;
  kind: string;
  city: string;
  country: string;
  lat: number;
  lng: number;
}

export interface GeoPoint {
  lat: number;
  lng: number;
}

interface GeoFile {
  institutions: Institution[];
  chain: { name: string; arcAltitude: number };
}

export async function loadGeo(): Promise<{
  institutions: Record<string, Institution>;
  chain: GeoFile["chain"];
}> {
  const response = await fetch("/spec/geo/institutions.json");
  if (!response.ok) {
    throw new Error(`Unable to load geography (${response.status})`);
  }

  const data = (await response.json()) as GeoFile;
  return {
    institutions: Object.fromEntries(
      data.institutions.map((institution) => [institution.id, institution]),
    ),
    chain: data.chain,
  };
}

export function greatCircleMidpoint(a: GeoPoint, b: GeoPoint): GeoPoint {
  const lat1 = (a.lat * Math.PI) / 180;
  const lon1 = (a.lng * Math.PI) / 180;
  const lat2 = (b.lat * Math.PI) / 180;
  const deltaLon = ((b.lng - a.lng) * Math.PI) / 180;

  const bx = Math.cos(lat2) * Math.cos(deltaLon);
  const by = Math.cos(lat2) * Math.sin(deltaLon);
  const lat = Math.atan2(
    Math.sin(lat1) + Math.sin(lat2),
    Math.sqrt((Math.cos(lat1) + bx) ** 2 + by ** 2),
  );
  const lon = lon1 + Math.atan2(by, Math.cos(lat1) + bx);

  return {
    lat: (lat * 180) / Math.PI,
    lng: ((((lon * 180) / Math.PI + 540) % 360) + 360) % 360 - 180,
  };
}
