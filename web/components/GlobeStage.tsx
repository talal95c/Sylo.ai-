"use client";

/**
 * The globe stage: turns the engine's events into what the globe shows (build spec, section 8.5).
 *
 * It draws events and decides nothing. Give it every event applied since the last reset, in order:
 *
 *     <GlobeStage events={events} />
 *
 * It resets itself on `scenario.started` and `session.reset`, or when the list gets shorter.
 * The WebGL renderer (GlobeCanvas, the only file that imports react-globe.gl) is loaded on the
 * client only.
 */

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

import {
  CREDITED_COLOR,
  DANGER_COLOR,
  EXCLUDED_COLOR,
  HOP_KIND_COLORS,
  REFUND_COLOR,
  TIER_COLORS,
  hopKindColor,
  tierColor,
  withAlpha,
} from "@/lib/colors";
import type { Hop, Tier } from "@/lib/events";
import {
  CHAIN,
  INSTITUTIONS,
  angularDistance,
  arcApexAltitude,
  greatCircleMidpoint,
  hopAltitude,
  institution,
  type LatLng,
} from "@/lib/geo";

import type { ArcDatum, CameraTarget, MarkerDatum, PointDatum, RingDatum } from "./GlobeCanvas";

const GlobeCanvas = dynamic(() => import("./GlobeCanvas"), { ssr: false, loading: () => null });

/** What the stage reads from an event. Any event envelope fits. */
export interface StageEvent {
  seq: number;
  type: string;
  data: unknown;
}

// ---------------------------------------------------------------- timings and looks (spec 8.5)

const IDLE_VIEW = { lat: 22, lng: 4, altitude: 2.5 };
const SCENARIO_VIEW = { lat: 25, lng: 3, altitude: 1.9 };
const EXCLUDED_FLASH_MS = 1500;
const REFUND_HOP_MS = 800;
const REVERT_MARKER_MS = 4000;
const RESUME_ROTATION_MS = 4000;
const PULSE_MS = 1800;

const COMET = { dashLength: 0.35, dashGap: 1 };
const SOLID = { dashLength: 1, dashGap: 0, dashInitialGap: 0, dashAnimateTime: 0 };
const COMET_COLOR = "#f8fafc";
/**
 * The chain hop is watched from the side, so the height of its arc shows. The camera sits to the
 * east: the arc then rises on the left half of the screen, clear of the event feed on the right.
 */
const CHAIN_SIDE_VIEW = { lat: -4, lng: 26, altitude: 2.0 };
const CHAIN_LABEL = CHAIN.name.replace(/\s*\(.*\)\s*$/, "");

type HopPhase = "idle" | "active" | "settled" | "held" | "resumed" | "refunded";

interface RouteView {
  routeId: string;
  hops: Hop[];
  excluded: boolean;
  /** Excluded routes flash, then disappear. */
  flash: "on" | "gone";
}

interface ReverseArc {
  key: string;
  from: LatLng;
  to: LatLng;
  altitude: number;
  /** true for the first step, which starts at the apex of the held hop. */
  fromApex: boolean;
}

interface Scene {
  routes: RouteView[];
  selectedRouteId: string | null;
  tier: Tier | null;
  phases: HopPhase[];
  durations: number[];
  /** Bumped when a hop's comet must restart: it is part of the arc key. */
  epochs: number[];
  lock: { hop: number; state: "locked" | "revoked" | "open" } | null;
  crossText: string | null;
  reverse: ReverseArc[];
  rings: RingDatum[];
  camera: CameraTarget;
  autoRotate: boolean;
}

/** Camera target for a hop: above its midpoint, or from the side for the high chain arc. */
function hopView(hop: Hop, a: LatLng, b: LatLng): { lat: number; lng: number; altitude: number } {
  const mid = greatCircleMidpoint(a, b);
  if (hop.kind === "chain") {
    return { lat: mid.lat + CHAIN_SIDE_VIEW.lat, lng: mid.lng + CHAIN_SIDE_VIEW.lng, altitude: CHAIN_SIDE_VIEW.altitude };
  }
  return { ...mid, altitude: Math.min(2.0, Math.max(1.6, 1.6 + angularDistance(a, b) * 0.5)) };
}

function initialScene(nonce = 0): Scene {
  return {
    routes: [],
    selectedRouteId: null,
    tier: null,
    phases: [],
    durations: [],
    epochs: [],
    lock: null,
    crossText: null,
    reverse: [],
    rings: [],
    camera: { ...IDLE_VIEW, ms: 0, nonce },
    autoRotate: true,
  };
}

function place(id: string): LatLng | null {
  const found = institution(id);
  return found ? { lat: found.lat, lng: found.lng } : null;
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

function isTier(value: unknown): value is Tier {
  return typeof value === "string" && value in TIER_COLORS;
}

function readHops(value: unknown): Hop[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => record(item))
    .filter((item) => typeof item.from === "string" && typeof item.to === "string")
    .map((item) => ({ from: item.from as string, to: item.to as string, kind: (item.kind as Hop["kind"]) ?? "bank" }));
}

// ---------------------------------------------------------------- scene -> what the canvas draws

function selectedRoute(scene: Scene): RouteView | undefined {
  return scene.routes.find((route) => route.routeId === scene.selectedRouteId);
}

/** Where the lock, the chain label and the revert cross sit: the apex of a hop's arc. */
function apexOf(hop: Hop): { at: LatLng; altitude: number } | null {
  const a = place(hop.from);
  const b = place(hop.to);
  if (!a || !b) return null;
  return { at: greatCircleMidpoint(a, b), altitude: arcApexAltitude(a, b, hopAltitude(hop.kind, a, b)) };
}

function buildArcs(scene: Scene): ArcDatum[] {
  const arcs: ArcDatum[] = [];
  const tierHex = tierColor(scene.tier);

  for (const route of scene.routes) {
    const isSelected = route.routeId === scene.selectedRouteId;
    if (route.excluded && route.flash === "gone") continue;

    route.hops.forEach((hop, index) => {
      const a = place(hop.from);
      const b = place(hop.to);
      if (!a || !b) return;
      const geometry = { startLat: a.lat, startLng: a.lng, endLat: b.lat, endLng: b.lng, altitude: hopAltitude(hop.kind, a, b) };
      const kindHex = hopKindColor(hop.kind);
      const id = `${route.routeId}:${index}`;

      if (route.excluded) {
        // illegal route: red, dashed, for 1.5 s
        arcs.push({ key: `${id}:excluded`, ...geometry, color: withAlpha(EXCLUDED_COLOR, 0.95), stroke: 0.3, dashLength: 0.06, dashGap: 0.05, dashInitialGap: 0, dashAnimateTime: 0 });
        return;
      }
      if (!scene.selectedRouteId) {
        arcs.push({ key: `${id}:candidate`, ...geometry, color: withAlpha(kindHex, 0.25), stroke: 0.2, ...SOLID });
        return;
      }
      if (!isSelected) {
        arcs.push({ key: `${id}:other`, ...geometry, color: withAlpha(kindHex, 0.08), stroke: 0.14, ...SOLID });
        return;
      }

      const phase = scene.phases[index] ?? "idle";
      const duration = scene.durations[index] ?? 1400;
      const epoch = scene.epochs[index] ?? 0;
      switch (phase) {
        case "idle":
          arcs.push({ key: `${id}:idle`, ...geometry, color: withAlpha(kindHex, 0.7), stroke: 0.3, ...SOLID });
          break;
        case "active":
          arcs.push({ key: `${id}:track`, ...geometry, color: withAlpha(kindHex, 0.4), stroke: 0.3, ...SOLID });
          // the comet: one dash that enters at the start and reaches the end after `duration` ms
          arcs.push({ key: `${id}:comet:${epoch}`, ...geometry, color: COMET_COLOR, stroke: 0.75, ...COMET, dashInitialGap: 1, dashAnimateTime: duration });
          break;
        case "settled":
          arcs.push({ key: `${id}:settled`, ...geometry, color: withAlpha(tierHex, 0.95), stroke: 0.42, ...SOLID });
          break;
        case "held":
        case "resumed":
          arcs.push({ key: `${id}:track`, ...geometry, color: withAlpha(kindHex, 0.4), stroke: 0.3, ...SOLID });
          // the half already travelled stays amber: the money stopped at the apex
          arcs.push({ key: `${id}:half`, ...geometry, color: withAlpha(TIER_COLORS.MEDIUM, 0.95), stroke: 0.5, dashLength: 0.5, dashGap: 2, dashInitialGap: 0.5, dashAnimateTime: 0 });
          if (phase === "resumed") {
            // the comet leaves the apex and reaches the end after half the hop's duration
            arcs.push({ key: `${id}:resume:${epoch}`, ...geometry, color: COMET_COLOR, stroke: 0.75, dashLength: 0.3, dashGap: 2, dashInitialGap: 0.5, dashAnimateTime: duration });
          }
          break;
        case "refunded":
          arcs.push({ key: `${id}:refunded`, ...geometry, color: withAlpha(REFUND_COLOR, 0.28), stroke: 0.22, ...SOLID });
          break;
      }
    });
  }

  // the refund flies back: reversed arcs, one hop at a time
  for (const arc of scene.reverse) {
    arcs.push({
      key: arc.key,
      startLat: arc.from.lat,
      startLng: arc.from.lng,
      endLat: arc.to.lat,
      endLng: arc.to.lng,
      altitude: arc.altitude,
      color: REFUND_COLOR,
      stroke: 0.75,
      dashLength: 0.3,
      dashGap: 2,
      dashInitialGap: arc.fromApex ? 0.5 : 1,
      dashAnimateTime: arc.fromApex ? REFUND_HOP_MS * 2 : REFUND_HOP_MS,
    });
  }
  return arcs;
}

function buildPoints(scene: Scene): PointDatum[] {
  const route = selectedRoute(scene);
  const onRoute = new Set<string>(route ? route.hops.flatMap((hop) => [hop.from, hop.to]) : []);
  return INSTITUTIONS.map((item) => ({
    key: item.id,
    lat: item.lat,
    lng: item.lng,
    label: item.city,
    tooltip: `${item.name} · ${item.city}`,
    color: onRoute.has(item.id) ? "#f8fafc" : "rgba(148,163,184,0.85)",
    radius: onRoute.has(item.id) ? 0.3 : 0.2,
  }));
}

function buildMarkers(scene: Scene): MarkerDatum[] {
  const markers: MarkerDatum[] = [];
  const route = selectedRoute(scene);
  if (!route) return markers;

  const chainIndex = route.hops.findIndex((hop) => hop.kind === "chain");
  if (chainIndex >= 0 && !scene.lock) {
    const apex = apexOf(route.hops[chainIndex]);
    if (apex) {
      markers.push({ key: "chain-label", lat: apex.at.lat, lng: apex.at.lng, altitude: apex.altitude, kind: "label", text: CHAIN_LABEL, color: HOP_KIND_COLORS.chain });
    }
  }

  if (scene.lock && route.hops[scene.lock.hop]) {
    const apex = apexOf(route.hops[scene.lock.hop]);
    if (apex) {
      const base = { lat: apex.at.lat, lng: apex.at.lng, altitude: apex.altitude };
      if (scene.crossText) {
        markers.push({ key: "lock:cross", ...base, kind: "cross", text: scene.crossText, color: DANGER_COLOR });
      } else if (scene.lock.state === "locked") {
        markers.push({ key: "lock:locked", ...base, kind: "lock", text: `Held in escrow · ${CHAIN_LABEL}`, color: TIER_COLORS.MEDIUM });
      } else if (scene.lock.state === "revoked") {
        markers.push({ key: "lock:revoked", ...base, kind: "revoked", text: "Revoked", color: DANGER_COLOR });
      } else {
        markers.push({ key: "lock:open", ...base, kind: "unlock", text: "Released", color: CREDITED_COLOR });
      }
    }
  }
  return markers;
}

/** Keeps the same object for an unchanged datum, so the globe does not restart its animation. */
function stable<T extends { key: string }>(cache: Map<string, { signature: string; datum: T }>, next: T[]): T[] {
  const keys = new Set<string>();
  const out = next.map((datum) => {
    keys.add(datum.key);
    const signature = JSON.stringify(datum);
    const known = cache.get(datum.key);
    if (known && known.signature === signature) return known.datum;
    cache.set(datum.key, { signature, datum });
    return datum;
  });
  for (const key of [...cache.keys()]) if (!keys.has(key)) cache.delete(key);
  return out;
}

// ---------------------------------------------------------------- the stage

/** What the canvas is given. Built from the scene after every change, never during render. */
interface View {
  arcs: ArcDatum[];
  points: PointDatum[];
  markers: MarkerDatum[];
  rings: RingDatum[];
  camera: CameraTarget;
  autoRotate: boolean;
}

type Cache<T> = Map<string, { signature: string; datum: T }>;

function idleView(): View {
  const scene = initialScene();
  return { arcs: [], points: buildPoints(scene), markers: [], rings: [], camera: scene.camera, autoRotate: true };
}

export default function GlobeStage({ events }: { events: readonly StageEvent[] }) {
  const sceneRef = useRef<Scene>(initialScene());
  const processedRef = useRef(0);
  const timersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
  const nonceRef = useRef(0);
  const arcCache = useRef<Cache<ArcDatum>>(new Map());
  const pointCache = useRef<Cache<PointDatum>>(new Map());
  const markerCache = useRef<Cache<MarkerDatum>>(new Map());
  const [view, setView] = useState<View>(idleView);

  useEffect(() => {
    const timers = timersRef.current;
    // The caches keep unchanged data identical, so the globe does not restart a running comet.
    const redraw = () => {
      const scene = sceneRef.current;
      setView({
        arcs: stable(arcCache.current, buildArcs(scene)),
        points: stable(pointCache.current, buildPoints(scene)),
        markers: stable(markerCache.current, buildMarkers(scene)),
        rings: scene.rings,
        camera: scene.camera,
        autoRotate: scene.autoRotate,
      });
    };
    const reducedMotion = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const after = (ms: number, run: () => void) => {
      const id = setTimeout(() => {
        timers.delete(id);
        run();
        redraw();
      }, ms);
      timers.add(id);
    };
    const clearTimers = () => {
      timers.forEach((id) => clearTimeout(id));
      timers.clear();
    };
    const moveCamera = (view: { lat: number; lng: number; altitude: number }, ms: number) => {
      nonceRef.current += 1;
      sceneRef.current.camera = { ...view, ms: reducedMotion ? 0 : ms, nonce: nonceRef.current };
    };
    const pulse = (key: string, at: LatLng, color: string, options: { altitude?: number; repeat?: boolean; maxRadius?: number } = {}) => {
      const scene = sceneRef.current;
      const ring: RingDatum = {
        key,
        lat: at.lat,
        lng: at.lng,
        altitude: options.altitude ?? 0.004,
        color,
        maxRadius: options.maxRadius ?? 4.5,
        speed: 3.2,
        period: options.repeat ? 1200 : 60_000,
      };
      scene.rings = [...scene.rings.filter((item) => item.key !== key), ring];
      if (!options.repeat) {
        after(PULSE_MS, () => {
          sceneRef.current.rings = sceneRef.current.rings.filter((item) => item !== ring);
        });
      }
    };
    const stopPulse = (key: string) => {
      sceneRef.current.rings = sceneRef.current.rings.filter((item) => item.key !== key);
    };
    const reset = (view: { lat: number; lng: number; altitude: number }, ms: number, autoRotate: boolean) => {
      clearTimers();
      nonceRef.current += 1;
      sceneRef.current = { ...initialScene(nonceRef.current), camera: { ...view, ms: reducedMotion ? 0 : ms, nonce: nonceRef.current }, autoRotate };
    };
    const lockApex = () => {
      const scene = sceneRef.current;
      const route = selectedRoute(scene);
      return scene.lock && route?.hops[scene.lock.hop] ? apexOf(route.hops[scene.lock.hop]) : null;
    };

    /** The refund flies back hop by hop, from the apex of the held hop to the payer. */
    const flyBack = (animate: boolean) => {
      const scene = sceneRef.current;
      const route = selectedRoute(scene);
      if (!route) return;
      const heldHop = scene.lock ? scene.lock.hop : scene.phases.findIndex((phase) => phase === "held");
      if (heldHop < 0) return;
      const payer = place(route.hops[0].from);
      const finish = () => {
        if (payer) pulse("refund", payer, REFUND_COLOR, { maxRadius: 6 });
        moveCamera(SCENARIO_VIEW, 1200);
      };
      if (!animate) {
        for (let index = 0; index <= heldHop; index += 1) scene.phases[index] = "refunded";
        finish();
        return;
      }
      const step = (index: number) => {
        const current = sceneRef.current;
        const hop = route.hops[index];
        const from = place(hop.to);
        const to = place(hop.from);
        if (!from || !to) return;
        const arc: ReverseArc = { key: `refund:${index}:${nonceRef.current}`, from, to, altitude: hopAltitude(hop.kind, from, to), fromApex: index === heldHop };
        current.phases[index] = "refunded";
        current.reverse = [...current.reverse, arc];
        if (index !== heldHop) moveCamera({ ...greatCircleMidpoint(from, to), altitude: 1.8 }, REFUND_HOP_MS);
        after(REFUND_HOP_MS, () => {
          sceneRef.current.reverse = sceneRef.current.reverse.filter((item) => item !== arc);
          if (index > 0) step(index - 1);
          else finish();
        });
      };
      step(heldHop);
    };

    const apply = (event: StageEvent, animate: boolean) => {
      const data = record(event.data);
      const scene = sceneRef.current;
      const route = selectedRoute(scene);

      switch (event.type) {
        case "session.reset":
          reset(IDLE_VIEW, 1000, true);
          break;

        case "scenario.started":
          reset(SCENARIO_VIEW, 1000, false);
          break;

        case "norms.checked": {
          const routes = Array.isArray(data.routes) ? data.routes.map(record) : [];
          scene.routes = routes.map((item) => {
            const excluded = item.status === "EXCLUDED";
            return { routeId: String(item.routeId), hops: readHops(item.hops), excluded, flash: excluded && animate ? "on" : "gone" } as RouteView;
          });
          if (animate) {
            after(EXCLUDED_FLASH_MS, () => {
              sceneRef.current.routes = sceneRef.current.routes.map((item) => (item.excluded ? { ...item, flash: "gone" } : item));
            });
          }
          break;
        }

        case "risk.scored":
          if (isTier(data.tier)) scene.tier = data.tier;
          break;

        case "route.selected": {
          scene.selectedRouteId = typeof data.routeId === "string" ? data.routeId : null;
          if (isTier(data.tier)) scene.tier = data.tier;
          const chosen = selectedRoute(scene);
          scene.phases = (chosen?.hops ?? []).map(() => "idle");
          scene.durations = (chosen?.hops ?? []).map(() => 1400);
          scene.epochs = (chosen?.hops ?? []).map(() => 0);
          break;
        }

        case "leg.sent": {
          const index = Number(data.hop);
          if (!route || !route.hops[index]) break;
          scene.durations[index] = Number(data.durationMs) || 1400;
          scene.epochs[index] = (scene.epochs[index] ?? 0) + 1;
          scene.phases[index] = animate ? "active" : "settled";
          const a = place(route.hops[index].from);
          const b = place(route.hops[index].to);
          if (a && b && animate) {
            moveCamera(hopView(route.hops[index], a, b), Math.min(900, scene.durations[index] * 0.6));
          }
          break;
        }

        case "leg.settled": {
          const index = Number(data.hop);
          if (!route || !route.hops[index]) break;
          scene.phases[index] = "settled";
          const at = place(String(data.at ?? route.hops[index].to));
          if (at && animate) pulse(`settled:${index}`, at, tierColor(scene.tier));
          break;
        }

        case "escrow.deposited":
        case "payment.held": {
          if (!route) break;
          const active = scene.phases.findIndex((phase) => phase === "active" || phase === "held");
          const index = event.type === "payment.held" && Number.isInteger(Number(data.hop)) ? Number(data.hop) : active >= 0 ? active : route.hops.findIndex((hop) => hop.kind === "chain");
          if (index < 0 || !route.hops[index]) break;
          scene.phases[index] = "held"; // the comet stops in place
          scene.lock = { hop: index, state: "locked" };
          const apex = apexOf(route.hops[index]);
          if (apex) {
            pulse("held", apex.at, TIER_COLORS.MEDIUM, { altitude: apex.altitude, repeat: true, maxRadius: 5 });
          }
          break;
        }

        case "intent.revoked":
          if (scene.lock) scene.lock = { ...scene.lock, state: "revoked" };
          stopPulse("held");
          break;

        case "escrow.refunded":
          stopPulse("held");
          flyBack(animate);
          break;

        case "escrow.released": {
          stopPulse("held");
          if (!scene.lock) break;
          const index = scene.lock.hop;
          scene.lock = { ...scene.lock, state: "open" };
          scene.epochs[index] = (scene.epochs[index] ?? 0) + 1;
          scene.phases[index] = animate ? "resumed" : "settled";
          break;
        }

        case "payment.credited": {
          const at = place(String(data.at ?? ""));
          if (at) pulse("credited", at, CREDITED_COLOR, { maxRadius: 7 });
          after(RESUME_ROTATION_MS, () => {
            sceneRef.current.autoRotate = true;
          });
          break;
        }

        case "attack.attempted": {
          const apex = lockApex();
          if (apex) {
            pulse("attack", apex.at, DANGER_COLOR, { altitude: apex.altitude, maxRadius: 6 });
            const held = route?.hops[scene.lock?.hop ?? -1];
            const a = held ? place(held.from) : null;
            const b = held ? place(held.to) : null;
            if (animate && held && a && b) moveCamera(hopView(held, a, b), 700);
          }
          break;
        }

        case "tx.reverted": {
          if (!scene.lock) break;
          scene.crossText = typeof data.text === "string" && data.text ? data.text.replace(/\.$/, "") : "Rejected by the smart contract";
          after(REVERT_MARKER_MS, () => {
            sceneRef.current.crossText = null;
          });
          break;
        }

        default:
          break; // every other event is told by the card, the alert and the feed
      }
    };

    if (events.length < processedRef.current) {
      reset(IDLE_VIEW, 0, true);
      processedRef.current = 0;
    }
    const fresh = events.slice(processedRef.current);
    fresh.forEach((event, index) => {
      // Only the newest event of a batch animates: a replayed buffer lands on its final picture.
      apply(event, !reducedMotion && index === fresh.length - 1);
    });
    processedRef.current = events.length;
    if (fresh.length > 0) redraw();
  }, [events]);

  // On unmount: stop the timers and forget what was processed (so a remount starts clean).
  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      timers.forEach((id) => clearTimeout(id));
      timers.clear();
      processedRef.current = 0;
      sceneRef.current = initialScene();
    };
  }, []);

  return (
    <div style={{ position: "absolute", inset: 0 }} aria-hidden="true">
      <GlobeCanvas arcs={view.arcs} points={view.points} rings={view.rings} markers={view.markers} camera={view.camera} autoRotate={view.autoRotate} />
    </div>
  );
}
