"use client";

/**
 * The 3D globe renderer. This is the ONLY file that imports react-globe.gl (it needs WebGL and
 * `window`, so GlobeStage loads it with `next/dynamic` and `ssr: false`).
 *
 * It draws what it is given and decides nothing: arcs, points, rings, markers and a camera target.
 */

import { useEffect, useRef, useState } from "react";
import Globe, { type GlobeMethods } from "react-globe.gl";

export interface ArcDatum {
  key: string;
  startLat: number;
  startLng: number;
  endLat: number;
  endLng: number;
  color: string;
  altitude: number;
  stroke: number;
  /** Dash pattern in fractions of the arc length (three-globe). A solid arc is `dashLength: 1, dashGap: 0`. */
  dashLength: number;
  dashGap: number;
  dashInitialGap: number;
  /** Milliseconds for a dash to travel one full arc length; 0 = static. */
  dashAnimateTime: number;
}

export interface PointDatum {
  key: string;
  lat: number;
  lng: number;
  label: string;
  tooltip: string;
  color: string;
  radius: number;
}

export interface RingDatum {
  key: string;
  lat: number;
  lng: number;
  altitude: number;
  color: string;
  maxRadius: number;
  speed: number;
  /** Milliseconds between two pulses. */
  period: number;
}

export type MarkerKind = "label" | "lock" | "revoked" | "unlock" | "cross";

export interface MarkerDatum {
  key: string;
  lat: number;
  lng: number;
  altitude: number;
  kind: MarkerKind;
  text: string;
  color: string;
}

export interface CameraTarget {
  lat: number;
  lng: number;
  altitude: number;
  ms: number;
  /** Changes every time the camera must move, even to the same place. */
  nonce: number;
}

export interface GlobeCanvasProps {
  arcs: ArcDatum[];
  points: PointDatum[];
  rings: RingDatum[];
  markers: MarkerDatum[];
  camera: CameraTarget;
  autoRotate: boolean;
}

const EARTH_IMAGE = "//unpkg.com/three-globe/example/img/earth-night.jpg";
const SKY_IMAGE = "//unpkg.com/three-globe/example/img/night-sky.png";

const ICONS: Record<MarkerKind, string> = {
  label: "",
  lock:
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
  revoked:
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/><path d="M9 14l6 4M15 14l-6 4"/></svg>',
  unlock:
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/></svg>',
  cross:
    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" aria-hidden="true"><path d="M5 5l14 14M19 5L5 19"/></svg>',
};

/** One DOM element per marker datum (react-globe.gl positions it; the datum never changes once created). */
function markerElement(datum: object): HTMLElement {
  const marker = datum as MarkerDatum;
  const el = document.createElement("div");
  el.setAttribute("data-marker", marker.kind);
  el.style.cssText = [
    "display:flex",
    "align-items:center",
    "gap:6px",
    "transform:translate(-50%,-50%)",
    "white-space:nowrap",
    "pointer-events:none",
    "font:600 12px/1.2 system-ui,-apple-system,Segoe UI,sans-serif",
    `color:${marker.color}`,
  ].join(";");
  if (marker.kind === "label") {
    el.style.transform = "translate(-50%,-190%)";
    el.style.font = "500 11px/1.2 system-ui,-apple-system,Segoe UI,sans-serif";
    el.style.letterSpacing = "0.04em";
    el.style.textShadow = "0 1px 6px rgba(0,0,0,0.9)";
    el.textContent = marker.text;
    return el;
  }
  el.style.padding = "5px 10px 5px 8px";
  el.style.borderRadius = "999px";
  el.style.background = "rgba(2,6,23,0.88)";
  el.style.border = `1.5px solid ${marker.color}`;
  el.style.boxShadow = `0 0 18px ${marker.color}66`;
  el.innerHTML = ICONS[marker.kind];
  // "Headline: detail" is shown on two lines, so a long badge stays narrow.
  const [headline, detail] = marker.text.split(": ");
  const text = document.createElement("span");
  text.textContent = headline;
  if (detail) {
    text.style.display = "flex";
    text.style.flexDirection = "column";
    const second = document.createElement("span");
    second.textContent = detail;
    second.style.cssText = "font:500 11px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace;opacity:0.9";
    text.appendChild(second);
  }
  el.appendChild(text);
  return el;
}

function ringColor(datum: object): (t: number) => string {
  const { color } = datum as RingDatum;
  const value = parseInt(color.replace("#", ""), 16);
  const rgb = `${(value >> 16) & 255},${(value >> 8) & 255},${value & 255}`;
  return (t: number) => `rgba(${rgb},${Math.max(0, 1 - t)})`;
}

export default function GlobeCanvas({ arcs, points, rings, markers, camera, autoRotate }: GlobeCanvasProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const globeRef = useRef<GlobeMethods | undefined>(undefined);
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  const [ready, setReady] = useState(false);

  // Fill the parent, and follow its size.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setSize({ width: Math.max(1, el.clientWidth), height: Math.max(1, el.clientHeight) });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Camera moves requested by the stage.
  useEffect(() => {
    if (!ready || !globeRef.current) return;
    globeRef.current.pointOfView({ lat: camera.lat, lng: camera.lng, altitude: camera.altitude }, camera.ms);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the nonce says when to move
  }, [ready, camera.nonce]);

  // Slow auto-rotation while idle.
  useEffect(() => {
    if (!ready || !globeRef.current) return;
    const controls = globeRef.current.controls();
    controls.autoRotate = autoRotate;
    controls.autoRotateSpeed = 0.45;
  }, [ready, autoRotate]);

  return (
    <div ref={containerRef} style={{ position: "absolute", inset: 0, overflow: "hidden" }} data-testid="globe-canvas">
      {size && (
        <Globe
          ref={globeRef}
          width={size.width}
          height={size.height}
          globeImageUrl={EARTH_IMAGE}
          backgroundImageUrl={SKY_IMAGE}
          backgroundColor="#020617"
          showAtmosphere
          atmosphereColor="#60a5fa"
          atmosphereAltitude={0.16}
          onGlobeReady={() => setReady(true)}
          // institutions
          pointsData={points}
          pointLat="lat"
          pointLng="lng"
          pointColor="color"
          pointRadius="radius"
          pointAltitude={0.006}
          pointLabel="tooltip"
          pointsMerge={false}
          pointsTransitionDuration={0}
          labelsData={points}
          labelLat="lat"
          labelLng="lng"
          labelText="label"
          labelColor={() => "rgba(226,232,240,0.9)"}
          labelSize={0.55}
          labelDotRadius={0}
          labelAltitude={0.008}
          labelResolution={2}
          labelsTransitionDuration={0}
          // routes, comet, refund
          arcsData={arcs}
          arcStartLat="startLat"
          arcStartLng="startLng"
          arcEndLat="endLat"
          arcEndLng="endLng"
          arcColor="color"
          arcAltitude="altitude"
          arcStroke="stroke"
          arcDashLength="dashLength"
          arcDashGap="dashGap"
          arcDashInitialGap="dashInitialGap"
          arcDashAnimateTime="dashAnimateTime"
          arcsTransitionDuration={0}
          arcCurveResolution={96}
          // pulses
          ringsData={rings}
          ringLat="lat"
          ringLng="lng"
          ringAltitude="altitude"
          ringColor={ringColor}
          ringMaxRadius="maxRadius"
          ringPropagationSpeed="speed"
          ringRepeatPeriod="period"
          // lock, revert cross, chain label
          htmlElementsData={markers}
          htmlLat="lat"
          htmlLng="lng"
          htmlAltitude="altitude"
          htmlElement={markerElement}
          htmlTransitionDuration={0}
        />
      )}
    </div>
  );
}
