"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import Globe, { type GlobeMethods } from "react-globe.gl";
import * as THREE from "three";
import type { GeoPoint, Institution } from "@/lib/geo";
import { greatCircleMidpoint } from "@/lib/geo";
import type { ViewState } from "@/lib/store";
import { ACCENT, DANGER_COLOR, HOP_COLORS, REFUND_COLOR, TIER_COLORS } from "@/lib/colors";

export interface GlobeCanvasProps {
  state: ViewState;
  institutions: Record<string, Institution> | null;
  chainAltitude: number;
  atmosphereColor: string;
  speed: number;
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

interface HtmlDatum {
  id: string;
  lat: number;
  lng: number;
  altitude: number;
  html: string;
  className: string;
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

const CORRIDOR_VIEW = { lat: 26, lng: 3, altitude: 1.9 };
function clamp(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(maximum, value));
}

function angularDistanceDegrees(a: GeoPoint, b: GeoPoint) {
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

function hopView(
  from: GeoPoint,
  to: GeoPoint,
  chainAltitude: number,
  isChain = false,
) {
  const midpoint = greatCircleMidpoint(from, to);
  const distance = angularDistanceDegrees(from, to);
  const routeAltitude = clamp(0.55 + distance / 32, 0.75, 1.75);
  const altitude = isChain
    ? Math.max(routeAltitude, chainAltitude * 3.2)
    : routeAltitude;
  return {
    lat: midpoint.lat - altitude * 3,
    lng: midpoint.lng,
    altitude,
  };
}

const LABEL_X_OFFSET: Record<string, string> = {
  payer_rhone: "east-rhone",
  bank_fr: "west-europe",
  casp_eu: "east-europe",
  vasp_gh: "west-ghana",
  mule_bank: "east-ghana",
};
const GHANA_LABEL_IDS = new Set([
  "vasp_gh",
  "bank_gh",
  "momo_gh",
  "supplier_ssx",
  "mule_bank",
]);
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
}: GlobeCanvasProps) {
  const globeRef = useRef<GlobeMethods | undefined>(undefined);
  const { width, height } = useViewport();
  const reducedMotion = useReducedMotion();
  const [landDots, setLandDots] = useState<LandDot[]>([]);
  const [coastlines, setCoastlines] = useState<PathPoint[][]>([]);
  const [cache] = useState(() => new Map<string, object>());
  const speedRef = useRef(speed);

  useEffect(() => {
    speedRef.current = speed;
  }, [speed]);

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

  const arcs = useMemo<ArcDatum[]>(() => {
    if (!institutions) return [];
    const list: ArcDatum[] = [];
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
    const solid = { dashLength: 1, dashGap: 0, dashInitialGap: 0, animateTime: 0 };

    if (!state.selectedRouteId) {
      for (const route of state.routes) {
        const excluded = route.status === "EXCLUDED";
        route.hops.forEach((hop, index) => {
          const altitude = hop.kind === "chain" ? chainAltitude : null;
          push(`${route.routeId}-${index}`, hop.from, hop.to, excluded ? "x" : "eval", {
            color: excluded ? rgba(DANGER_COLOR, 0.85) : rgba(HOP_COLORS[hop.kind], 0.28),
            altitude,
            stroke: excluded ? 0.45 : 0.3,
            ...(excluded
              ? { dashLength: 0.05, dashGap: 0.035, dashInitialGap: 0, animateTime: 0 }
              : solid),
          });
        });
      }
      return list;
    }

    for (const hop of state.hops) {
      const altitude = hop.kind === "chain" ? chainAltitude : null;
      const base = `hop-${hop.index}`;
      const kindColor = HOP_COLORS[hop.kind];
      const duration = reducedMotion ? 0 : hop.durationMs ?? 1400;

      if (hop.state === "pending") {
        push(base, hop.from, hop.to, "pending", {
          color: "rgba(10, 10, 10, 0.16)",
          altitude,
          stroke: 0.22,
          ...solid,
        });
        continue;
      }

      if (hop.state === "settled") {
        push(base, hop.from, hop.to, `settled-${tierColor}`, {
          color: tierColor,
          altitude,
          stroke: 0.5,
          ...solid,
        });
        continue;
      }

      if (hop.state === "refunded") {
        push(base, hop.from, hop.to, "refunded-base", {
          color: rgba(REFUND_COLOR, 0.35),
          altitude,
          stroke: 0.4,
          ...solid,
        });
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
        push(base, hop.from, hop.to, "held", {
          color: TIER_COLORS.MEDIUM,
          altitude,
          stroke: 0.55,
          dashLength: 0.5,
          dashGap: 0.5,
          dashInitialGap: 0,
          animateTime: 0,
        });
        continue;
      }

      push(base, hop.from, hop.to, "active-base", {
        color: rgba(kindColor, 0.22),
        altitude,
        stroke: 0.3,
        ...solid,
      });
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
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [institutions, state.routes, state.selectedRouteId, state.hops, state.stopped, tierColor, holding, heldHop, chainAltitude, reducedMotion]);

  const involved = useMemo(() => {
    const ids = new Set<string>();
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
  }, [state.hops, state.routes, state.selectedRouteId]);

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
    const fallbackLabelIds = state.payment
      ? ["payer_rhone", state.scenario === "diverted" ? "mule_bank" : "supplier_ssx"]
      : state.routes.length
        ? ["payer_rhone", "bank_fr", "corr_uk", "casp_eu", "vasp_gh", state.scenario === "diverted" ? "mule_bank" : "supplier_ssx"]
        : ["payer_rhone", "supplier_ssx"];
    const payerFocused = ["scenario.started", "route.selected", "payment.stopped"].includes(
      state.lastEvent?.type ?? "",
    );
    const supplierFocused = state.lastEvent?.type === "verification.requested";
    const labelIds = focusedHop
      ? [
          ...new Set([
            focusedHop.from,
            focusedHop.to,
            ...(payerFocused ? ["payer_rhone"] : []),
            ...(supplierFocused ? ["supplier_ssx"] : []),
          ]),
        ]
      : fallbackLabelIds;
    const liveTarget =
      state.payment?.status === "in_transit"
        ? state.hops.find((hop) => hop.state === "active")?.to
        : undefined;
    for (const id of labelIds) {
      const institution = institutions[id];
      if (!institution) continue;
      const hasGhanaPair =
        focusedHop &&
        GHANA_LABEL_IDS.has(focusedHop.from) &&
        GHANA_LABEL_IDS.has(focusedHop.to);
      const offset = hasGhanaPair
        ? id === focusedHop.from
          ? "west-ghana"
          : "east-ghana"
        : LABEL_X_OFFSET[id] ?? "center";
      const isLive = liveTarget === id;
      list.push(
        stable(`lbl-${id}`, `${offset}:${isLive}`, () => ({
          id: `lbl-${id}`,
          lat: institution.lat,
          lng: institution.lng,
          altitude: 0.01,
          className: `globe-label ${offset}`,
          html: `<span class="globe-label-pill"><span class="globe-label-name">${SHORT_NAME[id] ?? institution.name}</span><span class="globe-label-city">${institution.city}</span>${isLive ? '<span class="globe-live"><span class="globe-live-dot"></span><span>LIVE</span></span>' : ""}</span>`,
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
      const variant = state.attack.reverted
        ? "reverted"
        : state.revoked
          ? "revoked"
          : state.released
            ? "released"
            : "held";
      const color =
        variant === "released" ? TIER_COLORS.LOW : variant === "held" ? TIER_COLORS.MEDIUM : DANGER_COLOR;
      const caption =
        variant === "reverted"
          ? "Rejected by the smart contract"
          : variant === "revoked"
            ? state.refunded
              ? "Revoked · refunded"
              : "Revoked"
            : variant === "released"
              ? "Released"
              : "Held in escrow";
      const icon =
        variant === "reverted"
          ? `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>`
          : `<svg width="16" height="16" viewBox="0 0 16 16" fill="none"><rect x="3" y="7" width="10" height="7" rx="2" stroke="currentColor" stroke-width="1.5"/><path d="${variant === "released" ? "M5.5 7V5a2.5 2.5 0 0 1 4.9-.7" : "M5.5 7V5a2.5 2.5 0 0 1 5 0v2"}" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>`;
      list.push(
        stable("lock", variant + state.refunded, () => ({
          id: "lock",
          lat: lockPoint.lat,
          lng: lockPoint.lng,
          altitude: chainAltitude,
          className: "globe-marker",
          html: `<div style="color:${color};display:flex;flex-direction:column;align-items:center;gap:6px"><div class="badge">${icon}</div><div class="caption">${caption}</div></div>`,
        })),
      );
    }
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [institutions, involved, state.hops, state.payment?.status, state.selectedRouteId, state.routes.length, state.scenario, state.lastEvent, state.held, state.revoked, state.released, state.refunded, state.attack.reverted, lockPoint, chainHop, chainAltitude]);

  const rings = useMemo<RingDatum[]>(() => {
    if (!institutions) return [];
    const ring = (id: string, lat: number, lng: number, altitude: number, color: string, maxRadius = 3) =>
      stable(`ring-${id}`, color, () => ({ id, lat, lng, altitude, color, maxRadius }));
    if (state.attack.attempted && lockPoint) {
      return [ring("attack", lockPoint.lat, lockPoint.lng, 0.005, DANGER_COLOR, 6)];
    }
    if (state.refunded) {
      const payer = at("payer_rhone");
      return payer ? [ring("refund", payer.lat, payer.lng, 0.005, REFUND_COLOR, 4)] : [];
    }
    if (holding && lockPoint) {
      return [ring("held", lockPoint.lat, lockPoint.lng, 0.005, TIER_COLORS.MEDIUM, 5)];
    }
    if (state.credited) {
      const target = at(state.credited.at);
      return target ? [ring("credited", target.lat, target.lng, 0.005, TIER_COLORS.LOW, 4)] : [];
    }
    const settled = [...state.hops].reverse().find((hop) => hop.state === "settled");
    if (settled) {
      const target = at(settled.to);
      return target ? [ring(`settled-${settled.index}`, target.lat, target.lng, 0.005, tierColor, 2.5)] : [];
    }
    return [];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [institutions, state.attack.attempted, state.refunded, state.credited, state.hops, holding, lockPoint, tierColor]);

  const lastEvent = state.lastEvent;
  useEffect(() => {
    const globe = globeRef.current;
    if (!globe) return;
    const controls = globe.controls() as unknown as { autoRotate: boolean; autoRotateSpeed: number };
    if (!lastEvent || lastEvent.type === "session.reset") {
      controls.autoRotate = !reducedMotion;
      return;
    }
    if (!state.scenario) return;
    controls.autoRotate = false;
    const timers: ReturnType<typeof setTimeout>[] = [];
    const ms = (value: number) => (reducedMotion ? 0 : value);
    const schedule = (delay: number, callback: () => void) => {
      timers.push(setTimeout(callback, ms(delay)));
    };
    const focus = (point: GeoPoint | undefined, altitude: number, duration: number, latitudeOffset = 0) => {
      if (!point) return;
      globe.pointOfView(
        { lat: point.lat + latitudeOffset, lng: point.lng, altitude },
        ms(duration),
      );
    };
    const pointAt = (id: string) => institutions?.[id];
    const focusLock = (altitude: number, duration: number, latitudeOffset = 0) => {
      if (!lockPoint) return;
      focus(lockPoint, altitude, duration, latitudeOffset);
    };
    const pullBack = (delay: number) => {
      schedule(delay, () => {
        globe.pointOfView(CORRIDOR_VIEW, ms(1800));
        schedule(1800 + 2000, () => {
          controls.autoRotate = !reducedMotion;
        });
      });
    };
    const data = lastEvent.data as Record<string, unknown>;
    switch (lastEvent.type) {
      case "scenario.started":
        focus(pointAt("payer_rhone"), 0.85, 1600);
        break;
      case "norms.checked":
        globe.pointOfView(CORRIDOR_VIEW, ms(1400));
        break;
      case "route.selected":
        focus(pointAt("payer_rhone"), 0.85, 1400);
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
          globe.pointOfView(target, ms(duration / Math.max(1, speedRef.current)));
        }
        break;
      }
      case "payment.held":
        focusLock(1.25, 1200, -8);
        break;
      case "verification.requested":
        focus(pointAt("supplier_ssx"), 0.9, 1400);
        break;
      case "intent.revoked":
        focusLock(1.25, 1000);
        break;
      case "escrow.refunded": {
        const payer = pointAt("payer_rhone");
        if (payer && lockPoint) {
          globe.pointOfView(hopView(payer, lockPoint, chainAltitude), ms(1600));
        }
        break;
      }
      case "payment.stopped":
        focus(pointAt("payer_rhone"), 0.9, 1400);
        pullBack(4000);
        break;
      case "escrow.released":
        focusLock(1.25, 1000);
        break;
      case "payment.credited":
        focus(
          typeof data.at === "string" ? pointAt(data.at) : undefined,
          0.85,
          1400,
        );
        pullBack(3500);
        break;
      case "attack.attempted":
        focusLock(1.2, 900);
        break;
      case "tx.reverted":
        focusLock(1.2, 900);
        pullBack(4000);
        break;
    }
    return () => {
      timers.forEach(clearTimeout);
    };
  }, [lastEvent, state.scenario, institutions, lockPoint, reducedMotion, chainAltitude]);

  function onReady() {
    const globe = globeRef.current;
    if (!globe) return;
    const controls = globe.controls() as unknown as {
      autoRotate: boolean;
      autoRotateSpeed: number;
      enableZoom: boolean;
    };
    const frontLight = new THREE.DirectionalLight("#ffffff", 0.55);
    frontLight.position.set(-60, 80, 150);
    globe.scene().add(new THREE.AmbientLight("#ffffff", 0.45), frontLight);
    controls.autoRotate = !reducedMotion;
    controls.autoRotateSpeed = 0.35;
    controls.enableZoom = false;
    globe.pointOfView(CORRIDOR_VIEW, 0);
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
      particlesData={particles}
      particlesList="dots"
      particleLat="lat"
      particleLng="lng"
      particleAltitude={0.002}
      particlesSize={1.8}
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
        element.innerHTML = item.html;
        return element;
      }}
      htmlElementVisibilityModifier={(element, visible) => {
        element.style.opacity = visible ? "1" : "0";
      }}
      enablePointerInteraction={false}
    />
  );
}
