"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import Globe, { type GlobeMethods } from "react-globe.gl";
import * as THREE from "three";
import type { GeoPoint, Institution } from "@/lib/geo";
import { greatCircleMidpoint } from "@/lib/geo";
import type { ViewState } from "@/lib/store";
import { arcDotPositions } from "@/lib/arcDots";
import {
  CAMERA_VIEWS,
  angularDistanceDegrees,
  heldView,
  hopView,
  stoppedView,
  verificationView,
} from "@/lib/globeCamera";
import { ACCENT, DANGER_COLOR, HOP_COLORS, REFUND_COLOR, TIER_COLORS } from "@/lib/colors";
import {
  altitudeFactor,
  freeCenter,
  freeRect,
  viewOffsetFor,
  type Occluder,
  type OccluderSide,
  type Rect,
} from "@/lib/globeFrame";
import { isOnVisibleHemisphere } from "@/lib/globeVisibility";

export interface GlobeCanvasProps {
  state: ViewState;
  institutions: Record<string, Institution> | null;
  chainAltitude: number;
  atmosphereColor: string;
  speed: number;
  onFrame?: (cx: number, cy: number) => void;
}

interface ArcDatum {
  id: string;
  startLat: number;
  startLng: number;
  endLat: number;
  endLng: number;
  color: string | string[];
  altitude: number | null;
  stroke: number | null;
  dashLength: number;
  dashGap: number;
  dashInitialGap: number;
  animateTime: number;
}

interface DotTrack {
  id: string;
  points: THREE.Vector3[];
  color: string;
  opacity: number;
  radius: number;
  taper?: boolean;
}

interface HtmlDatum {
  id: string;
  lat: number;
  lng: number;
  altitude: number;
  html: string;
  className: string;
  preferredSide?: "above" | "below";
}

interface RingDatum {
  id: string;
  lat: number;
  lng: number;
  altitude: number;
  color: string;
  maxRadius: number;
}

interface PointDatum {
  id: string;
  lat: number;
  lng: number;
  color: string;
  radius: number;
}

type LandDot = [lat: number, lng: number, corridor: number];
type PathPoint = [lat: number, lng: number];

interface ParticleSet {
  id: string;
  dots: { lat: number; lng: number }[];
  color: string;
}

interface PathDatum {
  id: string;
  points: PathPoint[];
  color: string;
}

const CORRIDOR_VIEW = CAMERA_VIEWS.corridor;
const BASE_PARTICLE_SIZE = 1.8;
function clamp(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(maximum, value));
}

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (character) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return entities[character];
  });
}

const SHORT_NAME: Record<string, string> = {
  payer_rhone: "Rhône Cosmétiques",
  bank_fr: "Banque Hexagone",
  casp_eu: "EuroLedger CASP",
  corr_uk: "Thames Correspondent",
  payout_nl: "Meridian Payouts",
  remit_fr: "QuickRemit",
  vasp_gh: "Kente Digital Assets",
  bank_gh: "Gold Coast Bank",
  momo_gh: "AccraPay Wallets",
  supplier_ssx: "Savanna Shea",
  mule_bank: "Volta Rural Bank",
};

const onePixelPathStroke = () => null;

const DOT_SPACING = 0.8;
const DOT_RADIUS = 0.2;
const DOT_RADIUS_STRONG = 0.26;
const DOT_GEOMETRY = new THREE.SphereGeometry(1, 10, 8);

function dotTrackObject(datum: object) {
  const track = datum as DotTrack;
  const material = new THREE.MeshBasicMaterial({
    color: track.color,
    transparent: track.opacity < 1,
    opacity: track.opacity,
    depthWrite: track.opacity >= 1,
  });
  const mesh = new THREE.InstancedMesh(DOT_GEOMETRY, material, track.points.length);
  const matrix = new THREE.Matrix4();
  const last = Math.max(1, track.points.length - 1);
  track.points.forEach((point, index) => {
    const radius = track.taper
      ? track.radius * (0.6 + (0.65 * index) / last)
      : track.radius;
    matrix.makeScale(radius, radius, radius).setPosition(point);
    mesh.setMatrixAt(index, matrix);
  });
  mesh.instanceMatrix.needsUpdate = true;
  mesh.computeBoundingSphere();
  return mesh;
}

function rgba(hex: string, alpha: number) {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function subscribeResize(callback: () => void) {
  window.addEventListener("resize", callback);
  return () => window.removeEventListener("resize", callback);
}

function useViewport() {
  const width = useSyncExternalStore(subscribeResize, () => window.innerWidth, () => 1440);
  const height = useSyncExternalStore(subscribeResize, () => window.innerHeight, () => 900);
  return { width, height };
}

function subscribeMotion(callback: () => void) {
  const query = window.matchMedia("(prefers-reduced-motion: reduce)");
  query.addEventListener("change", callback);
  return () => query.removeEventListener("change", callback);
}

function useReducedMotion() {
  return useSyncExternalStore(
    subscribeMotion,
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => false,
  );
}

export default function GlobeCanvas({
  state,
  institutions,
  chainAltitude,
  atmosphereColor,
  speed,
  onFrame,
}: GlobeCanvasProps) {
  const globeRef = useRef<GlobeMethods | undefined>(undefined);
  const { width, height } = useViewport();
  const reducedMotion = useReducedMotion();
  const freeRectRef = useRef<Rect | null>(null);
  const viewOffsetRef = useRef({ x: 0, y: 0 });
  const viewOffsetTargetRef = useRef({ x: 0, y: 0 });
  const offsetTweenRef = useRef(0);
  const onFrameRef = useRef(onFrame);

  useEffect(() => {
    onFrameRef.current = onFrame;
  }, [onFrame]);
  const [landDots, setLandDots] = useState<LandDot[]>([]);
  const [coastlines, setCoastlines] = useState<PathPoint[][]>([]);
  const [particleSize, setParticleSize] = useState(BASE_PARTICLE_SIZE);
  const [cache] = useState(() => new Map<string, object>());
  const speedRef = useRef(speed);
  const cameraTimersRef = useRef(new Set<ReturnType<typeof setTimeout>>());
  const processedCameraSeqRef = useRef<number | null>(null);
  const lastZoomUpdateRef = useRef(0);

  useEffect(() => {
    speedRef.current = speed;
  }, [speed]);

  useEffect(
    () => () => {
      cameraTimersRef.current.forEach(clearTimeout);
      cameraTimersRef.current.clear();
    },
    [],
  );

  const material = useMemo(
    () =>
      new THREE.MeshPhongMaterial({
        color: "#ffffff",
        transparent: true,
        opacity: 0.85,
        emissive: "#f5f7ff",
        emissiveIntensity: 0.4,
        shininess: 8,
      }),
    [],
  );

  useEffect(() => {
    let alive = true;
    Promise.all([fetch("/geo/land-dots.json"), fetch("/geo/coastline-50m.json")])
      .then(async ([dotsResponse, coastlineResponse]) => {
        if (!dotsResponse.ok || !coastlineResponse.ok) return null;
        return Promise.all([dotsResponse.json(), coastlineResponse.json()]);
      })
      .then((data) => {
        if (!alive || !data) return;
        setLandDots(data[0] as LandDot[]);
        setCoastlines(data[1] as PathPoint[][]);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  function stable<T extends object>(id: string, signature: string, make: () => T): T {
    const key = `${id}|${signature}`;
    const existing = cache.get(key);
    if (existing) return existing as T;
    const created = make();
    cache.set(key, created);
    return created;
  }

  const particles = useMemo<ParticleSet[]>(() => {
    const neutral: ParticleSet["dots"] = [];
    const corridor: ParticleSet["dots"] = [];
    for (const [lat, lng, isCorridor] of landDots) {
      (isCorridor ? corridor : neutral).push({ lat, lng });
    }
    return [
      { id: "land", dots: neutral, color: "rgba(30,35,50,0.38)" },
      { id: "corridor", dots: corridor, color: "rgba(1,43,255,0.75)" },
    ];
  }, [landDots]);

  const paths = useMemo<PathDatum[]>(() => {
    const coastlinePaths = coastlines.map((points, index) => ({
      id: `coastline-${index}`,
      points,
      color: "rgba(10,20,40,0.22)",
    }));
    const graticulePaths: PathDatum[] = [];
    for (let lat = -80; lat <= 80; lat += 20) {
      const points: PathPoint[] = [];
      for (let lng = -180; lng <= 180; lng += 4) points.push([lat, lng]);
      graticulePaths.push({
        id: `graticule-lat-${lat}`,
        points,
        color: "rgba(10,20,40,0.06)",
      });
    }
    for (let lng = -180; lng < 180; lng += 20) {
      const points: PathPoint[] = [];
      for (let lat = -90; lat <= 90; lat += 4) points.push([lat, lng]);
      graticulePaths.push({
        id: `graticule-lng-${lng}`,
        points,
        color: "rgba(10,20,40,0.06)",
      });
    }
    return [...coastlinePaths, ...graticulePaths];
  }, [coastlines]);

  const at = (id: string) => institutions?.[id];
  const chainHop = state.hops.find((hop) => hop.kind === "chain");
  const lockPoint = useMemo(() => {
    const route = state.routes.find((candidate) => candidate.routeId === state.selectedRouteId);
    const hop = chainHop ?? route?.hops.find((candidate) => candidate.kind === "chain");
    if (!hop || !institutions) return null;
    const from = institutions[hop.from];
    const to = institutions[hop.to];
    if (!from || !to) return null;
    return greatCircleMidpoint(from, to);
  }, [chainHop, institutions, state.routes, state.selectedRouteId]);

  const tierColor = TIER_COLORS[state.payment?.tier ?? "LOW"];
  const heldHop = state.held?.hop;
  const holding = state.held !== null && !state.released && !state.refunded;

  const { arcs, tracks } = useMemo(() => {
    const list: ArcDatum[] = [];
    const tracks: DotTrack[] = [];
    if (!institutions) return { arcs: list, tracks };
    const push = (
      id: string,
      fromId: string,
      toId: string,
      signature: string,
      style: Omit<ArcDatum, "id" | "startLat" | "startLng" | "endLat" | "endLng">,
    ) => {
      const from = institutions[fromId];
      const to = institutions[toId];
      if (!from || !to) return;
      list.push(
        stable(id, signature, () => ({
          id,
          startLat: from.lat,
          startLng: from.lng,
          endLat: to.lat,
          endLng: to.lng,
          ...style,
        })),
      );
    };
    const dots = (
      id: string,
      fromId: string,
      toId: string,
      altitude: number | null,
      style: { color: string; opacity: number; radius?: number; taper?: boolean },
    ) => {
      const from = institutions[fromId];
      const to = institutions[toId];
      if (!from || !to) return;
      const radius = style.radius ?? DOT_RADIUS;
      const taper = style.taper ?? false;
      tracks.push(
        stable(`dots-${id}`, `${fromId}>${toId}|${altitude}|${style.color}|${style.opacity}|${radius}|${taper}`, () => ({
          id,
          color: style.color,
          opacity: style.opacity,
          radius,
          taper,
          points: arcDotPositions(from, to, altitude, DOT_SPACING),
        })),
      );
    };

    for (const [index, sample] of (state.wave?.samples ?? []).entries()) {
      const sampleId = `${sample.paymentId || "traffic"}-${index}`;
      dots(`wave-${sampleId}-track`, sample.from, sample.to, null, {
        color: DANGER_COLOR,
        opacity: 0.85,
        radius: DOT_RADIUS_STRONG,
      });
      push(`wave-${sampleId}-comet`, sample.from, sample.to, `wave-comet-${sampleId}`, {
        color: [rgba(DANGER_COLOR, 0), DANGER_COLOR],
        altitude: null,
        stroke: 0.9,
        dashLength: 0.45,
        dashGap: 1,
        dashInitialGap: 1,
        animateTime: reducedMotion ? 0 : 1500,
      });
    }

    if (!state.selectedRouteId) {
      for (const route of state.routes) {
        const unavailable = Boolean(state.rails[route.routeId] || state.killSwitch?.adapter === route.routeId);
        const excludedByNorms = route.status === "EXCLUDED";
        route.hops.forEach((hop, index) => {
          const altitude = hop.kind === "chain" ? chainAltitude : null;
          dots(
            `${route.routeId}-${index}`,
            hop.from,
            hop.to,
            altitude,
            unavailable
              ? { color: DANGER_COLOR, opacity: 0.55 }
              : excludedByNorms
                ? { color: "#0a0a0a", opacity: 0.12, radius: DOT_RADIUS * 0.8 }
                : { color: HOP_COLORS[hop.kind], opacity: 0.35, taper: true },
          );
        });
      }
      return { arcs: list, tracks };
    }

    for (const hop of state.hops) {
      const altitude = hop.kind === "chain" ? chainAltitude : null;
      const base = `hop-${hop.index}`;
      const kindColor = HOP_COLORS[hop.kind];
      const duration = reducedMotion ? 0 : hop.durationMs ?? 1400;

      if (hop.state === "pending") {
        dots(base, hop.from, hop.to, altitude, { color: "#0a0a0a", opacity: 0.28, radius: DOT_RADIUS * 0.85, taper: true });
        continue;
      }

      if (hop.state === "settled") {
        dots(base, hop.from, hop.to, altitude, { color: tierColor, opacity: 1, radius: DOT_RADIUS_STRONG });
        continue;
      }

      if (hop.state === "refunded") {
        dots(base, hop.from, hop.to, altitude, { color: REFUND_COLOR, opacity: 0.6 });
        if (!state.stopped && !reducedMotion) {
          push(`${base}-back`, hop.to, hop.from, "refunded-comet", {
            color: [rgba(REFUND_COLOR, 0), REFUND_COLOR],
            altitude,
            stroke: 0.7,
            dashLength: 0.4,
            dashGap: 1,
            dashInitialGap: 1,
            animateTime: 800,
          });
        }
        continue;
      }

      if (holding && hop.index === heldHop) {
        dots(base, hop.from, hop.to, altitude, { color: TIER_COLORS.MEDIUM, opacity: 1, radius: DOT_RADIUS_STRONG });
        continue;
      }

      dots(base, hop.from, hop.to, altitude, { color: kindColor, opacity: 0.45, taper: true });
      push(`${base}-comet`, hop.from, hop.to, `comet-${duration}-${state.released}`, {
        color: [rgba(hop.kind === "chain" ? kindColor : ACCENT, 0), hop.kind === "chain" ? kindColor : ACCENT],
        altitude,
        stroke: hop.kind === "chain" ? 0.75 : 0.9,
        dashLength: duration ? (hop.kind === "chain" ? 0.35 : 0.45) : 1,
        dashGap: duration ? 1 : 0,
        dashInitialGap: duration ? 1 : 0,
        animateTime: duration,
      });
    }

    for (const route of state.routes) {
      const unavailable = Boolean(state.rails[route.routeId] || state.killSwitch?.adapter === route.routeId);
      if (!unavailable || route.routeId === state.selectedRouteId) continue;
      route.hops.forEach((hop, index) => {
        dots(`unavailable-${route.routeId}-${index}`, hop.from, hop.to, hop.kind === "chain" ? chainAltitude : null, {
          color: DANGER_COLOR,
          opacity: 0.55,
        });
      });
    }
    return { arcs: list, tracks };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [institutions, state.routes, state.rails, state.killSwitch, state.selectedRouteId, state.hops, state.stopped, state.wave, tierColor, holding, heldHop, chainAltitude, reducedMotion]);

  const involved = useMemo(() => {
    const ids = new Set<string>();
    for (const sample of state.wave?.samples ?? []) {
      ids.add(sample.from);
      ids.add(sample.to);
    }
    for (const institution of state.wave?.cluster?.institutions ?? []) {
      ids.add(institution);
    }
    if (state.selectedRouteId) {
      state.hops.forEach((hop) => {
        ids.add(hop.from);
        ids.add(hop.to);
      });
    } else if (state.routes.length) {
      state.routes.forEach((route) =>
        route.hops.forEach((hop) => {
          ids.add(hop.from);
          ids.add(hop.to);
        }),
      );
    } else {
      ids.add("payer_rhone");
      ids.add("supplier_ssx");
    }
    return ids;
  }, [state.hops, state.routes, state.selectedRouteId, state.wave]);

  const points = useMemo<PointDatum[]>(() => {
    if (!institutions) return [];
    return Object.values(institutions).map((institution) => {
      const active = involved.has(institution.id);
      const mule = institution.id === "mule_bank";
      return stable(`pt-${institution.id}`, `${active}`, () => ({
        id: institution.id,
        lat: institution.lat,
        lng: institution.lng,
        color: active ? (mule ? DANGER_COLOR : "#0a0a0a") : "rgba(10,10,10,0.25)",
        radius: active ? 0.32 : 0.2,
      }));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [institutions, involved]);

  const htmlData = useMemo<HtmlDatum[]>(() => {
    if (!institutions) return [];
    const list: HtmlDatum[] = [];
    const focusedHop =
      state.hops.find((hop) => hop.state === "active") ??
      [...state.hops].reverse().find((hop) => hop.state !== "pending") ??
      state.hops[0];
    const muleScenario = state.scenario === "mule_wave" || state.scenario === "diverted";
    const fallbackLabelIds = state.payment
      ? ["payer_rhone", muleScenario ? "mule_bank" : "supplier_ssx"]
      : state.routes.length
        ? ["payer_rhone", "bank_fr", "corr_uk", "casp_eu", "vasp_gh", muleScenario ? "mule_bank" : "supplier_ssx"]
        : state.scenario === "mule_wave"
          ? ["payer_rhone", "bank_fr", "mule_bank"]
          : ["payer_rhone", "supplier_ssx"];
    const payerFocused = ["scenario.started", "route.selected", "payment.stopped"].includes(
      state.lastEvent?.type ?? "",
    );
    const supplierFocused = state.lastEvent?.type === "verification.requested";
    const labelIds = [
      ...new Set([
        ...(focusedHop
          ? [
              focusedHop.to,
              focusedHop.from,
              ...(payerFocused ? ["payer_rhone"] : []),
              ...(supplierFocused ? ["supplier_ssx"] : []),
            ]
          : fallbackLabelIds),
        ...(state.scenario === "mule_wave" && state.wave ? ["mule_bank"] : []),
      ]),
    ];
    const liveTarget =
      state.payment?.status === "in_transit"
        ? state.hops.find((hop) => hop.state === "active")?.to
        : undefined;
    const closePair = focusedHop
      ? angularDistanceDegrees(institutions[focusedHop.from], institutions[focusedHop.to]) < 10
      : false;
    for (const id of labelIds) {
      const institution = institutions[id];
      if (!institution) continue;
      const isLive = liveTarget === id;
      const preferredSide = closePair && focusedHop?.to === id ? "below" : "above";
      list.push(
        stable(`lbl-${id}`, `${preferredSide}:${isLive}`, () => ({
          id: `lbl-${id}`,
          lat: institution.lat,
          lng: institution.lng,
          altitude: 0.01,
          className: `globe-label${preferredSide === "below" ? " below" : ""}`,
          preferredSide,
          html: `<span class="globe-label-connector"></span><span class="globe-label-pill"><span class="globe-label-name">${SHORT_NAME[id] ?? institution.name}</span><span class="globe-label-city">${institution.city}</span>${isLive ? '<span class="globe-live"><span class="globe-live-dot"></span><span>LIVE</span></span>' : ""}</span>`,
        })),
      );
    }

    if (state.wave?.breaker && state.wave.cluster) {
      const centroid = state.wave.cluster.centroid;
      const regionName =
        state.wave.breaker.scope.regionName ??
        state.wave.cluster.regionName ??
        state.wave.cluster.region;
      const region = regionName.replace(/\s+Region$/, "");
      const label = `Circuit breaker · ${region} · 24 h`;
      list.push(
        stable("wave-breaker", label, () => ({
          id: "wave-breaker",
          lat: centroid.lat,
          lng: centroid.lng,
          altitude: 0.015,
          className: "globe-label globe-label-breaker",
          preferredSide: "below",
          html: `<span class="globe-label-connector"></span><span class="globe-label-pill globe-label-breaker-pill"><span class="globe-label-name globe-label-breaker-name">${escapeHtml(label)}</span></span>`,
        })),
      );
    }

    if (lockPoint && state.selectedRouteId && chainHop && !state.held) {
      list.push(
        stable("chain-label", "chain", () => ({
          id: "chain-label",
          lat: lockPoint.lat,
          lng: lockPoint.lng,
          altitude: chainAltitude,
          className: "globe-chain-label",
          html: "Avalanche C-Chain",
        })),
      );
    }

    if (lockPoint && state.held) {
      const variant = state.incident
        ? "guardian"
        : state.attack.reverted
        ? "reverted"
        : state.revoked
          ? "revoked"
          : state.released
            ? "released"
            : "held";
      const color =
        variant === "released" ? TIER_COLORS.LOW : variant === "held" ? TIER_COLORS.MEDIUM : DANGER_COLOR;
      const caption =
        variant === "guardian"
          ? state.incident?.action.includes("PAUSE")
            ? "Corridor FR to GH paused"
            : "Frozen by the guardian"
          : variant === "reverted"
          ? "Rejected by the smart contract"
          : variant === "revoked"
            ? state.refunded
              ? "Revoked · refunded"
              : "Revoked"
            : variant === "released"
              ? "Released"
              : "Held in escrow";
      const icon =
        variant === "guardian"
          ? `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M8 1.8 13 3.7v4c0 3.1-2.1 5.4-5 6.5-2.9-1.1-5-3.4-5-6.5v-4L8 1.8Z" stroke="currentColor" stroke-width="1.5"/><path d="M8 5v4M8 11.5v.1" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`
          : variant === "reverted"
          ? `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`
          : `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="3" y="7" width="10" height="7" rx="2" stroke="currentColor" stroke-width="1.5"/><path d="${variant === "released" ? "M5.5 7V5a2.5 2.5 0 0 1 4.9-.7" : "M5.5 7V5a2.5 2.5 0 0 1 5 0v2"}" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`;
      list.push(
        stable("lock", variant + state.refunded + (state.incident?.incidentId ?? ""), () => ({
          id: "lock",
          lat: lockPoint.lat,
          lng: lockPoint.lng,
          altitude: chainAltitude,
          className: "globe-marker",
          html: `<div style="color:${color};position:relative"><div class="badge">${icon}</div><div class="caption">${caption}</div></div>`,
        })),
      );
    }
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [institutions, involved, state.hops, state.payment?.status, state.selectedRouteId, state.routes.length, state.scenario, state.wave, state.lastEvent, state.held, state.incident, state.revoked, state.released, state.refunded, state.attack.reverted, lockPoint, chainHop, chainAltitude]);

  const handleGlobeZoom = useCallback(
    (pov: { lat: number; lng: number; altitude: number }) => {
      const now = performance.now();
      if (now - lastZoomUpdateRef.current < 100) return;
      lastZoomUpdateRef.current = now;
      const nextSize = BASE_PARTICLE_SIZE * clamp(1.9 / pov.altitude, 1, 1.7);
      setParticleSize((current) => (Math.abs(current - nextSize) < 0.01 ? current : nextSize));
    },
    [],
  );

  useEffect(() => {
    const globe = globeRef.current;
    if (globe) handleGlobeZoom(globe.pointOfView());
  }, [handleGlobeZoom]);

  useEffect(() => {
    let frame = 0;
    const gap = 18;

    const layoutLabels = () => {
      const globe = globeRef.current;
      if (!globe) return;
      const cameraPov = globe.pointOfView();

      const free = freeRectRef.current;
      const viewportLeft = free ? free.left : 12;
      const viewportRight = free ? free.right : width - 12;
      const viewportTop = free ? free.top : 76;
      const viewportBottom = free ? free.bottom : height - 72;
      const placed: DOMRect[] = [...document.querySelectorAll<HTMLElement>(".globe-marker, .globe-chain-label")]
        .filter((marker) => marker.style.opacity !== "0")
        .map((marker) => {
          const rect = marker.getBoundingClientRect();
          return rect.width > 0 ? rect : (marker.firstElementChild?.getBoundingClientRect() ?? rect);
        })
        .filter((rect) => rect.width > 0 && rect.height > 0);

      for (const label of htmlData) {
        if (!label.className.startsWith("globe-label")) continue;
        const element = document.querySelector<HTMLElement>(
          `.globe-label[data-globe-label-id="${label.id}"]`,
        );
        const pill = element?.querySelector<HTMLElement>(".globe-label-pill");
        if (!element || !pill) continue;

        const screen = globe.getScreenCoords(label.lat, label.lng, label.altitude);
        const behindGlobe =
          element.dataset.globeVisible === "false" ||
          !isOnVisibleHemisphere(label, cameraPov);
        const anchorOutside =
          screen.x < viewportLeft ||
          screen.x > viewportRight ||
          screen.y < viewportTop ||
          screen.y > viewportBottom;
        const hidden = behindGlobe || anchorOutside;
        element.classList.toggle("panel-hidden", hidden);
        element.style.opacity = hidden ? "0" : "1";
        if (hidden) continue;

        let below = label.preferredSide === "below";
        element.classList.toggle("below", below);
        element.style.setProperty("--globe-label-shift-x", "0px");
        let rect = pill.getBoundingClientRect();
        if (!below && rect.top < viewportTop) below = true;
        if (below && rect.bottom > viewportBottom) below = false;
        element.classList.toggle("below", below);
        rect = pill.getBoundingClientRect();

        let shiftX = clamp(0, viewportLeft - rect.left, viewportRight - rect.right);
        element.style.setProperty("--globe-label-shift-x", `${shiftX}px`);
        rect = pill.getBoundingClientRect();

        const collision = placed.find(
          (other) =>
            rect.left < other.right + 8 &&
            rect.right > other.left - 8 &&
            rect.top < other.bottom + 6 &&
            rect.bottom > other.top - 6,
        );
        if (collision) {
          element.classList.toggle("below", !below);
          const alternateRect = pill.getBoundingClientRect();
          const alternateFits =
            alternateRect.top >= viewportTop &&
            alternateRect.bottom <= viewportBottom &&
            !placed.some(
              (other) =>
                alternateRect.left < other.right + 8 &&
                alternateRect.right > other.left - 8 &&
                alternateRect.top < other.bottom + 6 &&
                alternateRect.bottom > other.top - 6,
            );
          if (alternateFits) {
            below = !below;
            rect = alternateRect;
          } else {
            element.classList.toggle("below", below);
            const shiftRight = collision.right + 8 - rect.left;
            const shiftLeft = collision.left - 8 - rect.right;
            shiftX += rect.right + shiftRight <= viewportRight ? shiftRight : shiftLeft;
            shiftX = clamp(
              shiftX,
              viewportLeft - rect.left + shiftX,
              viewportRight - rect.right + shiftX,
            );
            element.style.setProperty("--globe-label-shift-x", `${shiftX}px`);
            rect = pill.getBoundingClientRect();
          }
        }

        const stillCollides = placed.some(
          (other) =>
            rect.left < other.right + 8 &&
            rect.right > other.left - 8 &&
            rect.top < other.bottom + 6 &&
            rect.bottom > other.top - 6,
        );
        if (stillCollides) {
          element.classList.add("panel-hidden");
          element.style.opacity = "0";
          continue;
        }

        const connectorLength = Math.hypot(shiftX, gap);
        const connectorAngle = (Math.atan2(shiftX, gap) * 180) / Math.PI;
        element.style.setProperty("--globe-label-connector-length", `${connectorLength}px`);
        element.style.setProperty(
          "--globe-label-connector-angle",
          `${below ? -connectorAngle : connectorAngle}deg`,
        );
        placed.push(rect);
      }
    };

    // Layout reads DOM rects for every label; ~10 Hz keeps the demo laptop smooth.
    let last = -Infinity;
    const tick = (now: number) => {
      if (now - last >= 100) {
        last = now;
        layoutLabels();
      }
      frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [height, htmlData, width]);

  const rings = useMemo<RingDatum[]>(() => {
    if (!institutions) return [];
    const ring = (id: string, lat: number, lng: number, altitude: number, color: string, maxRadius = 3) =>
      stable(`ring-${id}`, color, () => ({ id, lat, lng, altitude, color, maxRadius }));
    const waveRings: RingDatum[] = [];
    if (state.scenario === "mule_wave" && state.wave?.cluster) {
      const { lat, lng } = state.wave.cluster.centroid;
      if (state.wave.breaker) {
        waveRings.push(ring("wave-breaker", lat, lng, 0.004, TIER_COLORS.MEDIUM, 12));
      }
      waveRings.push(ring("wave-cluster", lat, lng, 0.006, DANGER_COLOR, 4));
    }
    if (state.attack.attempted && lockPoint) {
      return [...waveRings, ring("attack", lockPoint.lat, lockPoint.lng, chainAltitude, DANGER_COLOR, 6)];
    }
    if (state.refunded) {
      const payer = at("payer_rhone");
      return payer ? [...waveRings, ring("refund", payer.lat, payer.lng, 0.005, REFUND_COLOR, 4)] : waveRings;
    }
    if (holding && lockPoint) {
      return [...waveRings, ring("held", lockPoint.lat, lockPoint.lng, chainAltitude, TIER_COLORS.MEDIUM, 5)];
    }
    if (state.credited) {
      const target = at(state.credited.at);
      return target ? [...waveRings, ring("credited", target.lat, target.lng, 0.005, TIER_COLORS.LOW, 4)] : waveRings;
    }
    const settled = [...state.hops].reverse().find((hop) => hop.state === "settled");
    if (settled) {
      const target = at(settled.to);
      return target ? [...waveRings, ring(`settled-${settled.index}`, target.lat, target.lng, 0.005, tierColor, 2.5)] : waveRings;
    }
    return waveRings;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [institutions, state.attack.attempted, state.refunded, state.credited, state.hops, state.wave, state.scenario, holding, lockPoint, tierColor]);

  const lastEvent = state.lastEvent;
  useEffect(() => {
    const globe = globeRef.current;
    if (!globe) return;
    if (lastEvent?.type === "scenario.started" || lastEvent?.type === "session.reset") {
      cameraTimersRef.current.forEach(clearTimeout);
      cameraTimersRef.current.clear();
    }
    if (lastEvent && processedCameraSeqRef.current === lastEvent.seq) return;
    const controls = globe.controls() as unknown as { autoRotate: boolean; autoRotateSpeed: number };
    if (!lastEvent || lastEvent.type === "session.reset") {
      controls.autoRotate = false;
      if (lastEvent) processedCameraSeqRef.current = lastEvent.seq;
      const fit = altitudeFactor(freeRectRef.current, width, height);
      globe.pointOfView(
        { ...CAMERA_VIEWS.corridor, altitude: CAMERA_VIEWS.corridor.altitude * fit },
        reducedMotion ? 0 : 1200,
      );
      return;
    }
    if (!institutions) return;
    processedCameraSeqRef.current = lastEvent.seq;
    if (!state.scenario) return;
    controls.autoRotate = false;
    const ms = (value: number) => (reducedMotion ? 0 : value);
    const schedule = (delay: number, callback: () => void) => {
      let timer: ReturnType<typeof setTimeout>;
      timer = setTimeout(() => {
        cameraTimersRef.current.delete(timer);
        callback();
      }, ms(delay));
      cameraTimersRef.current.add(timer);
    };
    const pov = (target: { lat: number; lng: number; altitude: number }, duration: number) => {
      const fit = altitudeFactor(freeRectRef.current, width, height);
      globe.pointOfView({ ...target, altitude: target.altitude * fit }, duration);
    };
    const focus = (point: GeoPoint | undefined, altitude: number, duration: number) => {
      if (!point) return;
      pov({ lat: point.lat, lng: point.lng, altitude }, ms(duration));
    };
    const pointAt = (id: string) => institutions?.[id];
    const focusLock = (altitude: number, duration: number) => {
      if (!lockPoint) return;
      focus(lockPoint, altitude, duration);
    };
    const pullBack = (delay: number) => {
      schedule(delay, () => {
        pov(CAMERA_VIEWS.corridor, ms(1800));
      });
    };
    const data = lastEvent.data as Record<string, unknown>;
    switch (lastEvent.type) {
      case "scenario.started":
        if (data.scenario === "mule_wave") {
          const from = pointAt("bank_fr");
          const to = pointAt("mule_bank");
          if (from && to) globe.pointOfView(hopView(from, to, chainAltitude), ms(1600));
          break;
        }
        focus(pointAt("payer_rhone"), CAMERA_VIEWS.payerAltitude, 1600);
        break;
      case "traffic.sample": {
        const sample =
          state.wave?.samples.length === 1
            ? (data.arcs as { from: string; to: string }[] | undefined)?.[0]
            : undefined;
        const from = sample ? pointAt(sample.from) : undefined;
        const to = sample ? pointAt(sample.to) : undefined;
        if (from && to) globe.pointOfView(hopView(from, to, chainAltitude), ms(1400));
        break;
      }
      case "cluster.detected": {
        const centroid = data.centroid as GeoPoint | undefined;
        if (centroid) {
          globe.pointOfView({ ...centroid, altitude: 1.2 }, ms(1200));
        }
        break;
      }
      case "norms.checked":
        pov(CAMERA_VIEWS.corridor, ms(1400));
        break;
      case "route.selected":
        focus(pointAt("payer_rhone"), CAMERA_VIEWS.payerAltitude, 1400);
        break;
      case "leg.sent": {
        const from = institutions?.[String(data.from)];
        const to = institutions?.[String(data.to)];
        if (from && to) {
          const target = hopView(from, to, chainAltitude, data.kind === "chain");
          const duration = clamp(
            (typeof data.durationMs === "number" ? data.durationMs : 1400) * 0.6,
            900,
            1800,
          );
          pov(target, ms(duration / Math.max(1, speedRef.current)));
        }
        break;
      }
      case "payment.held": {
        if (lockPoint) pov(heldView(lockPoint), ms(1200));
        break;
      }
      case "verification.requested": {
        const supplier = pointAt("supplier_ssx");
        if (!lockPoint || !supplier) break;
        pov(verificationView(lockPoint, supplier), ms(1400));
        break;
      }
      case "intent.revoked":
        focusLock(CAMERA_VIEWS.heldAltitude, 1000);
        break;
      case "escrow.refunded": {
        const payer = pointAt("payer_rhone");
        if (payer && lockPoint) {
          pov(hopView(payer, lockPoint, chainAltitude), ms(1600));
        }
        break;
      }
      case "payment.stopped": {
        const payer = pointAt("payer_rhone");
        const route = state.routes.find((item) => item.routeId === state.selectedRouteId);
        const beneficiaryId =
          state.hops.at(-1)?.to ??
          route?.hops.at(-1)?.to ??
          (state.scenario === "diverted" ? "mule_bank" : "supplier_ssx");
        const beneficiary = pointAt(beneficiaryId);
        if (payer && beneficiary) {
          pov(stoppedView(payer, beneficiary), ms(1400));
        } else {
          focus(payer, CAMERA_VIEWS.payerAltitude, 1400);
        }
        pullBack(4000);
        break;
      }
      case "escrow.released":
        focusLock(CAMERA_VIEWS.heldAltitude, 1000);
        break;
      case "payment.credited":
        if (Object.keys(state.rails).length === 0 && state.scenario === "legit") {
          pov(CAMERA_VIEWS.corridor, ms(1400));
        } else {
          focus(
            typeof data.at === "string" ? pointAt(data.at) : undefined,
            CAMERA_VIEWS.payerAltitude,
            1400,
          );
          pullBack(3500);
        }
        break;
      case "attack.attempted":
        focusLock(CAMERA_VIEWS.attackAltitude, 900);
        break;
      case "tx.reverted":
        focusLock(CAMERA_VIEWS.attackAltitude, 900);
        pullBack(4000);
        break;
    }
  }, [lastEvent, state.scenario, state.wave, state.rails, state.routes, state.selectedRouteId, state.hops, institutions, lockPoint, reducedMotion, chainAltitude, width, height]);

  // Panel-aware framing: measure the occluders, then tween a camera view
  // offset so pointOfView targets land in the centre of the free area.
  useEffect(() => {
    const applyViewOffset = (target: { x: number; y: number }) => {
      const globe = globeRef.current;
      if (!globe) return;
      const camera = globe.camera() as THREE.PerspectiveCamera;
      if (offsetTweenRef.current) {
        cancelAnimationFrame(offsetTweenRef.current);
        offsetTweenRef.current = 0;
      }
      const setOffset = (x: number, y: number) => {
        viewOffsetRef.current = { x, y };
        if (Math.abs(x) < 0.5 && Math.abs(y) < 0.5) camera.clearViewOffset();
        else camera.setViewOffset(width, height, x, y, width, height);
      };
      if (reducedMotion) {
        setOffset(target.x, target.y);
        return;
      }
      const from = { ...viewOffsetRef.current };
      const start = performance.now();
      const tick = (now: number) => {
        const t = Math.min(1, (now - start) / 600);
        const eased = 1 - (1 - t) ** 3;
        setOffset(from.x + (target.x - from.x) * eased, from.y + (target.y - from.y) * eased);
        if (t < 1) offsetTweenRef.current = requestAnimationFrame(tick);
        else offsetTweenRef.current = 0;
      };
      offsetTweenRef.current = requestAnimationFrame(tick);
    };

    const measure = () => {
      const globe = globeRef.current;
      const occluders: Occluder[] = [
        ...document.querySelectorAll<HTMLElement>("[data-globe-occluder]"),
      ].map((element) => ({
        side: element.dataset.globeOccluder as OccluderSide,
        rect: element.getBoundingClientRect(),
      }));
      const free = freeRect(occluders, width, height);
      freeRectRef.current = free;
      const { cx, cy } = free
        ? freeCenter(free)
        : { cx: width / 2, cy: height / 2 };
      onFrameRef.current?.(cx, cy);
      if (!globe) return;
      if (process.env.NODE_ENV !== "production") {
        (window as unknown as { __syloGlobe?: GlobeMethods }).__syloGlobe = globe;
      }
      const target = free ? viewOffsetFor(width, height, cx, cy) : { x: 0, y: 0 };
      const previous = viewOffsetTargetRef.current;
      viewOffsetTargetRef.current = target;
      if (Math.abs(target.x - previous.x) <= 4 && Math.abs(target.y - previous.y) <= 4) return;
      applyViewOffset(target);
    };

    measure();
    const interval = setInterval(measure, 250);
    window.addEventListener("resize", measure);
    return () => {
      clearInterval(interval);
      window.removeEventListener("resize", measure);
      if (offsetTweenRef.current) cancelAnimationFrame(offsetTweenRef.current);
    };
  }, [width, height, reducedMotion]);

  function onReady() {
    const globe = globeRef.current;
    if (!globe) return;
    globe.renderer().setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    const controls = globe.controls() as unknown as {
      autoRotate: boolean;
      autoRotateSpeed: number;
      enableZoom: boolean;
    };
    const frontLight = new THREE.DirectionalLight("#ffffff", 0.55);
    frontLight.position.set(-60, 80, 150);
    globe.scene().add(new THREE.AmbientLight("#ffffff", 0.45), frontLight);
    controls.autoRotate = false;
    controls.enableZoom = false;
    globe.pointOfView(CORRIDOR_VIEW, reducedMotion ? 0 : 1200);
  }

  return (
    <Globe
      ref={globeRef}
      width={width}
      height={height}
      backgroundColor="rgba(0,0,0,0)"
      globeImageUrl={null}
      globeMaterial={material}
      showAtmosphere
      atmosphereColor={atmosphereColor}
      atmosphereAltitude={0.16}
      onGlobeReady={onReady}
      onZoom={handleGlobeZoom}
      particlesData={particles}
      particlesList="dots"
      particleLat="lat"
      particleLng="lng"
      particleAltitude={0.002}
      particlesSize={particleSize}
      particlesSizeAttenuation={false}
      particlesColor="color"
      pathsData={paths}
      pathPoints="points"
      pathPointAlt={0.0015}
      pathColor="color"
      pathStroke={onePixelPathStroke}
      pathTransitionDuration={0}
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
      arcDashAnimateTime="animateTime"
      arcsTransitionDuration={0}
      customLayerData={tracks}
      customThreeObject={dotTrackObject}
      pointsData={points}
      pointLat="lat"
      pointLng="lng"
      pointColor="color"
      pointRadius="radius"
      pointAltitude={0.004}
      pointsTransitionDuration={0}
      ringsData={rings}
      ringLat="lat"
      ringLng="lng"
      ringAltitude="altitude"
      ringColor={(ring: object) => (t: number) => rgba((ring as RingDatum).color, Math.max(0, 1 - t))}
      ringMaxRadius="maxRadius"
      ringPropagationSpeed={2.2}
      ringRepeatPeriod={reducedMotion ? 0 : 1100}
      htmlElementsData={htmlData}
      htmlLat="lat"
      htmlLng="lng"
      htmlAltitude="altitude"
      htmlTransitionDuration={0}
      htmlElement={(datum) => {
        const item = datum as HtmlDatum;
        const element = document.createElement("div");
        element.className = item.className;
        if (item.className.startsWith("globe-label")) {
          element.dataset.globeLabelId = item.id;
          element.dataset.preferredSide = item.preferredSide ?? "above";
        }
        element.innerHTML = item.html;
        return element;
      }}
      htmlElementVisibilityModifier={(element, visible) => {
        element.dataset.globeVisible = String(visible);
        element.style.opacity =
          visible && element.classList.contains("panel-hidden") === false
            ? "1"
            : "0";
      }}
      enablePointerInteraction={false}
    />
  );
}
