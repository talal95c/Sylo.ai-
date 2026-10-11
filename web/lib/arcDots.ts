import * as THREE from "three";

// Mirrors three-globe's arc geometry (radius 100, Bézier with altitude
// auto-scale 0.5) so the dots sit exactly where its arcs would be drawn.
const GLOBE_RADIUS = 100;
const AUTO_SCALE = 0.5;
const RAD = Math.PI / 180;

type LatLng = { lat: number; lng: number };

function unit({ lat, lng }: LatLng) {
  return new THREE.Vector3(Math.cos(lat * RAD) * Math.cos(lng * RAD), Math.cos(lat * RAD) * Math.sin(lng * RAD), Math.sin(lat * RAD));
}

export function greatCircleDistance(a: LatLng, b: LatLng) {
  return unit(a).angleTo(unit(b));
}

/** Point at fraction t along the great circle from a to b (same as d3 geoInterpolate). */
export function greatCirclePoint(a: LatLng, b: LatLng, t: number): LatLng {
  const angle = greatCircleDistance(a, b);
  if (angle === 0) return { lat: a.lat, lng: a.lng };
  const p = unit(a)
    .multiplyScalar(Math.sin((1 - t) * angle))
    .addScaledVector(unit(b), Math.sin(t * angle))
    .divideScalar(Math.sin(angle));
  return { lat: Math.atan2(p.z, Math.hypot(p.x, p.y)) / RAD, lng: Math.atan2(p.y, p.x) / RAD };
}

export function globeVector(lat: number, lng: number, relAltitude = 0) {
  const phi = (90 - lat) * RAD;
  const theta = (90 - lng) * RAD;
  const r = GLOBE_RADIUS * (1 + relAltitude);
  return new THREE.Vector3(r * Math.sin(phi) * Math.cos(theta), r * Math.cos(phi), r * Math.sin(phi) * Math.sin(theta));
}

class SphereArc extends THREE.Curve<THREE.Vector3> {
  constructor(
    private readonly a: THREE.Vector3,
    private readonly b: THREE.Vector3,
  ) {
    super();
  }

  getPoint(t: number, target = new THREE.Vector3()) {
    const angle = this.a.angleTo(this.b);
    if (angle === 0) return target.copy(this.a);
    return target
      .copy(this.a)
      .multiplyScalar(Math.sin((1 - t) * angle))
      .addScaledVector(this.b, Math.sin(t * angle))
      .divideScalar(Math.sin(angle));
  }
}

export function arcCurve(start: LatLng, end: LatLng, altitude: number | null): THREE.Curve<THREE.Vector3> {
  const height = altitude ?? (greatCircleDistance(start, end) / 2) * AUTO_SCALE;
  if (height) {
    const control = height * 1.5;
    const at = (t: number) => greatCirclePoint(start, end, t);
    return new THREE.CubicBezierCurve3(
      globeVector(start.lat, start.lng),
      globeVector(at(0.25).lat, at(0.25).lng, control),
      globeVector(at(0.75).lat, at(0.75).lng, control),
      globeVector(end.lat, end.lng),
    );
  }
  return new SphereArc(globeVector(start.lat, start.lng, 0.001), globeVector(end.lat, end.lng, 0.001));
}

/** Points spaced evenly by arc length (world units), endpoints included. */
export function arcDotPositions(start: LatLng, end: LatLng, altitude: number | null, spacing: number) {
  const curve = arcCurve(start, end, altitude);
  curve.arcLengthDivisions = 400;
  const count = Math.max(2, Math.round(curve.getLength() / spacing));
  return curve.getSpacedPoints(count);
}
