const DEGREES_TO_RADIANS = Math.PI / 180;

export interface GlobeDirection {
  lat: number;
  lng: number;
}

export function isOnVisibleHemisphere(
  point: GlobeDirection,
  camera: GlobeDirection,
  threshold = 0.05,
) {
  const pointLat = point.lat * DEGREES_TO_RADIANS;
  const cameraLat = camera.lat * DEGREES_TO_RADIANS;
  const longitudeDelta = (point.lng - camera.lng) * DEGREES_TO_RADIANS;
  const dot =
    Math.sin(pointLat) * Math.sin(cameraLat) +
    Math.cos(pointLat) * Math.cos(cameraLat) * Math.cos(longitudeDelta);
  return dot >= threshold;
}
