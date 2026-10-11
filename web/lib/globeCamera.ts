import { greatCircleMidpoint, type GeoPoint } from "./geo";

export const CAMERA_VIEWS = {
  corridor: { lat: 26, lng: 3, altitude: 1.9 },
  payerAltitude: 1.15,
  heldAltitude: 1.55,
  heldNorthOffset: 14,
  stoppedMinimumAltitude: 1.9,
  verificationMinimumAltitude: 1.4,
  attackAltitude: 1.35,
} as const;

function clamp(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(maximum, value));
}

export function angularDistanceDegrees(a: GeoPoint, b: GeoPoint) {
  const radians = Math.PI / 180;
  const latitudeDelta = (b.lat - a.lat) * radians;
  const longitudeDelta = (b.lng - a.lng) * radians;
  const latitudeA = a.lat * radians;
  const latitudeB = b.lat * radians;
  const haversine =
    Math.sin(latitudeDelta / 2) ** 2 +
    Math.cos(latitudeA) * Math.cos(latitudeB) * Math.sin(longitudeDelta / 2) ** 2;
  const bounded = clamp(haversine, 0, 1);
  return (2 * Math.atan2(Math.sqrt(bounded), Math.sqrt(1 - bounded))) / radians;
}

export function hopView(from: GeoPoint, to: GeoPoint, chainAltitude: number, isChain = false) {
  const midpoint = greatCircleMidpoint(from, to);
  const distance = angularDistanceDegrees(from, to);
  const routeAltitude = clamp(0.8 + distance / 32, 1, 1.75);
  return {
    lat: midpoint.lat,
    lng: midpoint.lng,
    altitude: isChain ? Math.max(routeAltitude, chainAltitude * 3.2) : routeAltitude,
  };
}

export function heldView(lockPoint: GeoPoint, altitude = CAMERA_VIEWS.heldAltitude) {
  return {
    lat: clamp(lockPoint.lat + CAMERA_VIEWS.heldNorthOffset, -80, 80),
    lng: lockPoint.lng,
    altitude,
  };
}

export function stoppedView(payer: GeoPoint, beneficiary: GeoPoint) {
  return {
    ...greatCircleMidpoint(payer, beneficiary),
    altitude: Math.max(
      CAMERA_VIEWS.stoppedMinimumAltitude,
      hopView(payer, beneficiary, 0).altitude,
    ),
  };
}

export function verificationView(lockPoint: GeoPoint, supplier: GeoPoint) {
  return {
    ...greatCircleMidpoint(lockPoint, supplier),
    altitude: Math.max(
      CAMERA_VIEWS.verificationMinimumAltitude,
      hopView(lockPoint, supplier, 0).altitude,
    ),
  };
}
