"use client";

// The only module that imports react-globe.gl (it needs the browser: GlobeStage loads it with ssr: false).
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import Globe, { type GlobeMethods } from "react-globe.gl";

import { DANGER_COLOR, HOP_COLORS, REFUND_COLOR, SAFE_COLOR, TIER_COLORS, tierColor, withAlpha } from "@/lib/colors";
import type { HopKind, LegSent, LegSettled, PaymentCredited } from "@/lib/events";
import { angularDistance, greatCircleMidpoint, indexInstitutions, type Geo, type Institution, type LatLng } from "@/lib/geo";
import type { HopView, ViewState } from "@/lib/store";

export interface GlobeCanvasProps {
  state: ViewState;
  geo: Geo | null;
  /** Recorded durations are divided by this: a replay at 2× runs everything twice as fast. */
  playbackRate: number;
}

const GLOBE_IMAGE = "https://unpkg.com/three-globe/example/img/earth-night.jpg";
const BACKGROUND_IMAGE = "https://unpkg.com/three-globe/example/img/night-sky.png";
const CHAIN_LABEL = "Avalanche C-Chain";
const DEFAULT_CHAIN_ALTITUDE = 0.45;
const HELD_COLOR = TIER_COLORS.MEDIUM;
const OVERVIEW = { lat: 25, lng: 3, altitude: 1.9 };
const IDLE_VIEW = { lat: 22, lng: 4, altitude: 2.3 };
const FLASH_MS = 1500;
const REFUND_HOP_MS = 800;
const REVERT_MS = 4000;
const RESUME_ROTATE_MS = 4000;
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

type Pov = LatLng & { altitude: number };

interface ArcDatum {
  key: string;
  startLat: number;
  startLng: number;
  startAltitude: number;
  endLat: number;
  endLng: number;
  endAltitude: number;
  color: string;
  altitude: number | null;
  stroke: number;
  dashLength: number;
  dashGap: number;
  dashInitialGap: number;
  dashAnimateTime: number;
}

interface RingDatum {
  key: string;
  lat: number;
  lng: number;
  altitude: number;
  color: string;
  maxRadius: number;
  speed: number;
  period: number;
}

interface MarkerDatum {
  key: string;
  lat: number;
  lng: number;
  altitude: number;
  element: HTMLElement;
}

type ArcStyle = Pick<ArcDatum, "color" | "stroke" | "dashLength" | "dashGap" | "dashInitialGap" | "dashAnimateTime">;

const solid = (color: string, stroke: number): ArcStyle => ({
  color,
  stroke,
  dashLength: 1,
  dashGap: 0,
  dashInitialGap: 0,
  dashAnimateTime: 0,
});
const comet = (color: string, durationMs: number): ArcStyle => ({
  color,
  stroke: 0.9,
  dashLength: 0.35,
  dashGap: 1,
  dashInitialGap: 1,
  dashAnimateTime: Math.max(200, durationMs),
});
const dashed = (color: string): ArcStyle => ({
  color,
  stroke: 0.4,
  dashLength: 0.06,
  dashGap: 0.04,
  dashInitialGap: 0,
  dashAnimateTime: 0,
});

function arc(key: string, from: Institution, to: Institution, kind: HopKind, chainAltitude: number, style: ArcStyle): ArcDatum {
  return {
    key,
    startLat: from.lat,
    startLng: from.lng,
    startAltitude: 0,
    endLat: to.lat,
    endLng: to.lng,
    endAltitude: 0,
    altitude: kind === "chain" ? chainAltitude : null,
    ...style,
  };
}

/**
 * Half of a chain arc, between the ground and the apex (where the escrow holds the money).
 * three-globe raises both control points to 1.5 × altitude, so altitude / 1.5 keeps the apex level.
 */
function halfArc(key: string, start: Pov, end: Pov, chainAltitude: number, style: ArcStyle): ArcDatum {
  return {
    key,
    startLat: start.lat,
    startLng: start.lng,
    startAltitude: start.altitude,
    endLat: end.lat,
    endLng: end.lng,
    endAltitude: end.altitude,
    altitude: chainAltitude / 1.5,
    ...style,
  };
}

function sameArc(a: ArcDatum, b: ArcDatum): boolean {
  return (
    a.startLat === b.startLat &&
    a.startLng === b.startLng &&
    a.startAltitude === b.startAltitude &&
    a.endLat === b.endLat &&
    a.endLng === b.endLng &&
    a.endAltitude === b.endAltitude &&
    a.color === b.color &&
    a.altitude === b.altitude &&
    a.stroke === b.stroke &&
    a.dashLength === b.dashLength &&
    a.dashGap === b.dashGap &&
    a.dashInitialGap === b.dashInitialGap &&
    a.dashAnimateTime === b.dashAnimateTime
  );
}

/** Where the lock sits: the great-circle midpoint of the held hop, at the chain arc's altitude. */
function apexOf(hops: HopView[], index: number | undefined, institutions: Record<string, Institution>, chainAltitude: number): Pov | null {
  if (index === undefined) return null;
  const hop = hops.find((h) => h.index === index);
  const from = hop && institutions[hop.from];
  const to = hop && institutions[hop.to];
  if (!hop || !from || !to) return null;
  return { ...greatCircleMidpoint(from, to), altitude: hop.kind === "chain" ? chainAltitude : 0.05 };
}

interface ArcInputs {
  state: ViewState;
  institutions: Record<string, Institution>;
  chainAltitude: number;
  flashing: boolean;
  refundCursor: number | null;
  reducedMotion: boolean;
  playbackRate: number;
}

function buildArcs({ state, institutions, chainAltitude, flashing, refundCursor, reducedMotion, playbackRate }: ArcInputs): ArcDatum[] {
  const arcs: ArcDatum[] = [];
  const selected = state.selectedRouteId !== null;
  const tier = tierColor(state.payment.tier);
  const onSelectedRoute = new Set(state.hops.map((h) => `${h.from}>${h.to}`));
  const drawn = new Set<string>();

  for (const route of state.routes) {
    const excluded = route.status === "EXCLUDED";
    if (excluded && !flashing) continue;
    for (const hop of route.hops) {
      const segment = `${hop.from}>${hop.to}`;
      if (selected && onSelectedRoute.has(segment)) continue;
      const key = `${excluded ? "excluded" : "route"}:${segment}`;
      const from = institutions[hop.from];
      const to = institutions[hop.to];
      if (drawn.has(key) || !from || !to) continue;
      drawn.add(key);
      const style = excluded
        ? dashed(withAlpha(DANGER_COLOR, 0.95))
        : solid(withAlpha(HOP_COLORS[hop.kind], selected ? 0.08 : 0.25), 0.3);
      arcs.push(arc(key, from, to, hop.kind, chainAltitude, style));
    }
  }

  const lock = state.chain.lock;
  const heldIndex = state.held?.hop ?? null;
  const lockApex = apexOf(state.hops, heldIndex ?? undefined, institutions, chainAltitude);
  for (const hop of state.hops) {
    const from = institutions[hop.from];
    const to = institutions[hop.to];
    if (!from || !to) continue;
    const key = `hop:${hop.index}`;
    const kindColor = HOP_COLORS[hop.kind];
    const isHeld = hop.index === heldIndex;
    // The escrow holds the money at the apex of the chain arc: refunds and releases start from there.
    const apex = isHeld && hop.kind === "chain" ? lockApex : null;
    const ground = (point: Institution): Pov => ({ lat: point.lat, lng: point.lng, altitude: 0 });

    if (hop.state === "pending" && state.payment.status === "stopped") {
      arcs.push(arc(`${key}:never-sent`, from, to, hop.kind, chainAltitude, solid(withAlpha(kindColor, 0.2), 0.3)));
    } else if (hop.state === "pending") {
      arcs.push(arc(`${key}:pending`, from, to, hop.kind, chainAltitude, solid(withAlpha(kindColor, 0.7), 0.45)));
    } else if (hop.state === "active" && isHeld && (lock === "locked" || lock === "revoked")) {
      arcs.push(arc(`${key}:held`, from, to, hop.kind, chainAltitude, solid(HELD_COLOR, 0.6)));
    } else if (hop.state === "active" && reducedMotion) {
      arcs.push(arc(`${key}:active`, from, to, hop.kind, chainAltitude, solid(kindColor, 0.6)));
    } else if (hop.state === "active") {
      const duration = (hop.durationMs ?? 1400) / playbackRate;
      arcs.push(arc(`${key}:track`, from, to, hop.kind, chainAltitude, solid(withAlpha(kindColor, 0.35), 0.45)));
      if (apex && lock === "open") {
        arcs.push(halfArc(`${key}:comet:${hop.since}`, apex, ground(to), chainAltitude, comet(kindColor, duration / 2)));
      } else {
        arcs.push(arc(`${key}:comet:${hop.since}`, from, to, hop.kind, chainAltitude, comet(kindColor, duration)));
      }
    } else if (hop.state === "settled") {
      arcs.push(arc(`${key}:settled`, from, to, hop.kind, chainAltitude, solid(tier, 0.55)));
    } else if (refundCursor !== null && hop.index < refundCursor) {
      // Refunding: the reverse comet has not reached this hop yet.
      const style = isHeld ? solid(HELD_COLOR, 0.6) : solid(tier, 0.55);
      arcs.push(arc(`${key}:${isHeld ? "held" : "settled"}`, from, to, hop.kind, chainAltitude, style));
    } else if (refundCursor !== null && hop.index === refundCursor) {
      const back = comet(REFUND_COLOR, REFUND_HOP_MS / playbackRate);
      const track = solid(withAlpha(REFUND_COLOR, 0.3), 0.45);
      if (apex) {
        arcs.push(halfArc(`${key}:refund-track`, apex, ground(from), chainAltitude, track));
        arcs.push(halfArc(`${key}:refund-comet:${hop.since}`, apex, ground(from), chainAltitude, back));
      } else {
        arcs.push(arc(`${key}:refund-track`, from, to, hop.kind, chainAltitude, track));
        arcs.push(arc(`${key}:refund-comet:${hop.since}`, to, from, hop.kind, chainAltitude, back));
      }
    } else if (apex) {
      arcs.push(halfArc(`${key}:refunded`, ground(from), apex, chainAltitude, solid(REFUND_COLOR, 0.55)));
      arcs.push(halfArc(`${key}:never-sent`, apex, ground(to), chainAltitude, solid(withAlpha(kindColor, 0.2), 0.3)));
    } else {
      arcs.push(arc(`${key}:refunded`, from, to, hop.kind, chainAltitude, solid(REFUND_COLOR, 0.55)));
    }
  }
  return arcs;
}

/** three-globe binds data by object identity: reuse unchanged arcs so running comets are not restarted. */
function useStableArcs(arcs: ArcDatum[]): ArcDatum[] {
  const [cache] = useState(() => new Map<string, ArcDatum>());
  return useMemo(() => {
    const keep = new Set<string>();
    const stable = arcs.map((datum) => {
      keep.add(datum.key);
      const previous = cache.get(datum.key);
      if (previous && sameArc(previous, datum)) return previous;
      cache.set(datum.key, datum);
      return datum;
    });
    for (const key of [...cache.keys()]) if (!keep.has(key)) cache.delete(key);
    return stable;
  }, [arcs, cache]);
}

const LOCK_CLOSED =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="4.5" y="10.5" width="15" height="10" rx="2"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5"/></svg>';
const LOCK_OPEN =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="4.5" y="10.5" width="15" height="10" rx="2"/><path d="M8 10.5V7a4 4 0 0 1 7.6-1.8"/></svg>';
const CROSS =
  '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>';

function markerElement(className: string, html: string): HTMLElement {
  const anchor = document.createElement("div");
  anchor.className = "globe-anchor";
  anchor.setAttribute("aria-hidden", "true");
  const body = document.createElement("div");
  body.className = className;
  body.innerHTML = html;
  anchor.appendChild(body);
  return anchor;
}

const subscribeResize = (onChange: () => void) => {
  window.addEventListener("resize", onChange);
  return () => window.removeEventListener("resize", onChange);
};
const subscribeMotion = (onChange: () => void) => {
  const query = window.matchMedia(REDUCED_MOTION_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
};

let ringCounter = 0;

export default function GlobeCanvas({ state, geo, playbackRate }: GlobeCanvasProps) {
  const globeRef = useRef<GlobeMethods | undefined>(undefined);
  const width = useSyncExternalStore(subscribeResize, () => window.innerWidth, () => 1440);
  const height = useSyncExternalStore(subscribeResize, () => window.innerHeight, () => 900);
  const reducedMotion = useSyncExternalStore(
    subscribeMotion,
    () => window.matchMedia(REDUCED_MOTION_QUERY).matches,
    () => false,
  );

  const institutions = useMemo(() => indexInstitutions(geo), [geo]);
  const chainAltitude = geo?.chain.arcAltitude ?? DEFAULT_CHAIN_ALTITUDE;

  const [flashing, setFlashing] = useState(false);
  const [refundCursor, setRefundCursor] = useState<number | null>(null);
  const [revertVisible, setRevertVisible] = useState(false);
  const [rings, setRings] = useState<RingDatum[]>([]);
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());
  const processed = useRef({ run: -1, seq: 0 });

  // One-shot effects (camera, pulses, flashes) for each event the globe has not seen yet.
  useEffect(() => {
    const globe = globeRef.current;
    // State is only set from these timers, never synchronously in this effect.
    const later = (fn: () => void, ms = 0) => {
      const timer = setTimeout(() => {
        timers.current.delete(timer);
        fn();
      }, ms);
      timers.current.add(timer);
    };
    const fly = (pov: Pov, ms: number) => {
      if (!reducedMotion) globe?.pointOfView(pov, ms);
    };
    const rotate = (on: boolean) => {
      const controls = globe?.controls();
      if (controls) controls.autoRotate = on && !reducedMotion;
    };
    const pulse = (at: LatLng | null | undefined, color: string, altitude = 0.01, maxRadius = 3) => {
      if (!at || reducedMotion) return;
      ringCounter += 1;
      const ring: RingDatum = { key: `ring-${ringCounter}`, lat: at.lat, lng: at.lng, altitude, color, maxRadius, speed: maxRadius * 1.8, period: 700 };
      later(() => setRings((current) => [...current, ring]));
      later(() => setRings((current) => current.filter((r) => r !== ring)), 2100);
    };
    const apex = (index: number | undefined) => apexOf(state.hops, index, institutions, chainAltitude);

    if (processed.current.run !== state.run) {
      processed.current = { run: state.run, seq: 0 };
      timers.current.forEach(clearTimeout);
      timers.current.clear();
      later(() => {
        setRings([]);
        setFlashing(false);
        setRefundCursor(null);
        setRevertVisible(false);
      });
      if (state.feed.length === 0) rotate(true);
    }

    for (const item of state.feed) {
      if (item.seq <= processed.current.seq) continue;
      processed.current.seq = item.seq;
      const event = item.event;
      switch (event.type) {
        case "scenario.started":
          rotate(false);
          fly(OVERVIEW, 1000);
          break;
        case "norms.checked":
          later(() => setFlashing(true));
          later(() => setFlashing(false), FLASH_MS);
          break;
        case "leg.sent": {
          const d = event.data as LegSent;
          const from = institutions[d.from];
          const to = institutions[d.to];
          if (from && to) {
            const altitude = Math.min(2.0, Math.max(1.6, 1.6 + angularDistance(from, to) * 0.9));
            fly({ ...greatCircleMidpoint(from, to), altitude }, Math.min(1200, d.durationMs / playbackRate));
          }
          break;
        }
        case "leg.settled":
          pulse(institutions[(event.data as LegSettled).at], tierColor(state.payment.tier));
          break;
        case "payment.held": {
          const lock = apex(state.held?.hop);
          if (lock) {
            pulse(lock, HELD_COLOR, lock.altitude, 4);
            fly({ lat: lock.lat, lng: lock.lng, altitude: 1.9 }, 900);
          }
          break;
        }
        case "escrow.refunded": {
          const fromHop = state.held?.hop ?? 0;
          const payer = institutions[state.payment.payer?.institutionId ?? state.hops[0]?.from ?? ""];
          const lock = apex(fromHop);
          if (lock && payer) fly({ ...greatCircleMidpoint(lock, payer), altitude: 2.0 }, 1000);
          if (!reducedMotion) {
            const step = REFUND_HOP_MS / playbackRate;
            later(() => setRefundCursor(fromHop));
            for (let index = fromHop - 1; index >= 0; index -= 1) later(() => setRefundCursor(index), (fromHop - index) * step);
            later(() => {
              setRefundCursor(null);
              pulse(payer, REFUND_COLOR, 0.01, 4);
            }, (fromHop + 1) * step);
          }
          break;
        }
        case "escrow.released": {
          const lock = apex(state.held?.hop);
          pulse(lock, SAFE_COLOR, lock?.altitude, 4);
          break;
        }
        case "payment.credited":
          pulse(institutions[(event.data as PaymentCredited).at], SAFE_COLOR, 0.01, 4);
          later(() => rotate(true), RESUME_ROTATE_MS);
          break;
        case "attack.attempted": {
          const lock = apex(state.held?.hop);
          if (lock) {
            pulse(lock, DANGER_COLOR, lock.altitude, 4);
            fly({ lat: lock.lat, lng: lock.lng, altitude: 1.9 }, 800);
          }
          break;
        }
        case "tx.reverted":
          later(() => setRevertVisible(true));
          later(() => setRevertVisible(false), REVERT_MS);
          break;
      }
    }
  }, [state, institutions, chainAltitude, playbackRate, reducedMotion]);

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach(clearTimeout);
  }, []);

  const arcs = useStableArcs(
    useMemo(
      () => buildArcs({ state, institutions, chainAltitude, flashing, refundCursor, reducedMotion, playbackRate }),
      [state, institutions, chainAltitude, flashing, refundCursor, reducedMotion, playbackRate],
    ),
  );

  const chainHop = useMemo(() => {
    const selectedChainHop = state.hops.find((h) => h.kind === "chain");
    if (selectedChainHop || state.selectedRouteId) return selectedChainHop ?? null;
    return state.routes.filter((r) => r.status === "PASS").flatMap((r) => r.hops).find((h) => h.kind === "chain") ?? null;
  }, [state.hops, state.routes, state.selectedRouteId]);
  const chainApex = useMemo(() => {
    const from = chainHop && institutions[chainHop.from];
    const to = chainHop && institutions[chainHop.to];
    return from && to ? { ...greatCircleMidpoint(from, to), altitude: chainAltitude } : null;
  }, [chainHop, institutions, chainAltitude]);
  const lockApex = useMemo(
    () => apexOf(state.hops, state.held?.hop, institutions, chainAltitude),
    [state.hops, state.held, institutions, chainAltitude],
  );
  const lock = state.chain.lock;

  const chainMarker = useMemo<MarkerDatum | null>(() => {
    if (!chainApex) return null;
    return { key: "chain-label", ...chainApex, element: markerElement("globe-chip", `<span class="globe-chip__dot"></span>${CHAIN_LABEL}`) };
  }, [chainApex]);
  const lockMarker = useMemo<MarkerDatum | null>(() => {
    if (!lockApex || lock === "none") return null;
    const view = {
      locked: { modifier: "", icon: LOCK_CLOSED, text: "Held in escrow" },
      revoked: { modifier: " globe-lock--revoked", icon: LOCK_CLOSED, text: "Revoked" },
      open: { modifier: " globe-lock--open", icon: LOCK_OPEN, text: "Released" },
    }[lock];
    const html = `<span class="globe-lock__icon">${view.icon}</span><span>${view.text}</span>`;
    return { key: `lock-${lock}`, ...lockApex, element: markerElement(`globe-lock${view.modifier}`, html) };
  }, [lockApex, lock]);
  const revertMarker = useMemo<MarkerDatum | null>(() => {
    if (!lockApex || !revertVisible) return null;
    const html = `<span class="globe-revert__icon">${CROSS}</span><span>Rejected by the smart contract</span>`;
    return { key: "revert", ...lockApex, element: markerElement("globe-revert", html) };
  }, [lockApex, revertVisible]);
  const markers = useMemo(
    () => [chainMarker, lockMarker, revertMarker].filter((m): m is MarkerDatum => m !== null),
    [chainMarker, lockMarker, revertMarker],
  );

  const points = useMemo(() => geo?.institutions ?? [], [geo]);
  const onRoute = useMemo(() => new Set(state.hops.flatMap((h) => [h.from, h.to])), [state.hops]);
  const idle = state.payment.status === "idle";
  const pointColor = (d: object) =>
    idle || onRoute.has((d as Institution).id) ? "rgba(226, 232, 240, 0.95)" : "rgba(148, 163, 184, 0.45)";
  const labelColor = (d: object) =>
    idle || onRoute.has((d as Institution).id) ? "rgba(226, 232, 240, 0.9)" : "rgba(148, 163, 184, 0.4)";

  const onGlobeReady = () => {
    const globe = globeRef.current;
    if (!globe) return;
    globe.pointOfView(reducedMotion ? OVERVIEW : IDLE_VIEW, 0);
    const controls = globe.controls();
    controls.autoRotate = !reducedMotion && state.payment.status === "idle";
    controls.autoRotateSpeed = 0.35;
  };

  return (
    <Globe
      ref={globeRef}
      width={width}
      height={height}
      globeOffset={width >= 1100 ? [-48, 24] : [0, 0]}
      backgroundColor="#060a13"
      backgroundImageUrl={BACKGROUND_IMAGE}
      globeImageUrl={GLOBE_IMAGE}
      atmosphereColor="#7aa2ff"
      atmosphereAltitude={0.16}
      onGlobeReady={onGlobeReady}
      pointsData={points}
      pointLat="lat"
      pointLng="lng"
      pointColor={pointColor}
      pointAltitude={0.006}
      pointRadius={0.22}
      pointLabel={(d: object) => `${(d as Institution).name} · ${(d as Institution).city}`}
      labelsData={points}
      labelLat="lat"
      labelLng="lng"
      labelText="short"
      labelSize={0.55}
      labelDotRadius={0.12}
      labelColor={labelColor}
      labelAltitude={0.008}
      labelResolution={2}
      arcsData={arcs}
      arcStartLat="startLat"
      arcStartLng="startLng"
      arcStartAltitude="startAltitude"
      arcEndLat="endLat"
      arcEndLng="endLng"
      arcEndAltitude="endAltitude"
      arcColor="color"
      arcAltitude="altitude"
      arcStroke="stroke"
      arcDashLength="dashLength"
      arcDashGap="dashGap"
      arcDashInitialGap="dashInitialGap"
      arcDashAnimateTime="dashAnimateTime"
      arcsTransitionDuration={reducedMotion ? 0 : 700}
      ringsData={rings}
      ringLat="lat"
      ringLng="lng"
      ringAltitude="altitude"
      ringColor={(d: object) => (t: number) => withAlpha((d as RingDatum).color, 1 - t)}
      ringMaxRadius="maxRadius"
      ringPropagationSpeed="speed"
      ringRepeatPeriod="period"
      htmlElementsData={markers}
      htmlLat="lat"
      htmlLng="lng"
      htmlAltitude="altitude"
      htmlElement={(d: object) => (d as MarkerDatum).element}
      htmlTransitionDuration={0}
    />
  );
}
