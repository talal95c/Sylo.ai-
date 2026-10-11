"use client";

import createGlobe from "cobe";
import { useEffect, useRef, useState } from "react";

type LatLng = [number, number];
type Side = "top" | "bottom" | "left" | "right";

interface Node {
  id: string;
  location: LatLng;
  label: string;
  role: string;
  side: Side;
}

interface Corridor {
  id: string;
  from: LatLng;
  to: LatLng;
  routeId?: "R1" | "R2" | "R3";
}

const LYON: LatLng = [45.764, 4.836];
const LONDON: LatLng = [51.507, -0.128];
const AMSTERDAM: LatLng = [52.368, 4.904];
const FRANKFURT: LatLng = [50.111, 8.682];
const ACCRA: LatLng = [5.604, -0.187];
const TAMALE: LatLng = [9.403, -0.842];

const NODES: Node[] = [
  { id: "lyon", location: LYON, label: "lyon", role: "payer", side: "bottom" },
  { id: "london", location: LONDON, label: "london", role: "corr.", side: "left" },
  { id: "amsterdam", location: AMSTERDAM, label: "amsterdam", role: "payout", side: "top" },
  { id: "frankfurt", location: FRANKFURT, label: "frankfurt", role: "casp", side: "right" },
  { id: "accra", location: ACCRA, label: "accra", role: "vasp", side: "bottom" },
  { id: "tamale", location: TAMALE, label: "tamale", role: "supplier", side: "top" },
];

const CORRIDORS: Corridor[] = [
  { id: "lyon-london", from: LYON, to: LONDON },
  { id: "lyon-amsterdam", from: LYON, to: AMSTERDAM },
  { id: "lyon-frankfurt", from: LYON, to: FRANKFURT },
  { id: "r1", from: LONDON, to: TAMALE, routeId: "R1" },
  { id: "r2", from: AMSTERDAM, to: TAMALE, routeId: "R2" },
  { id: "r3", from: FRANKFURT, to: ACCRA, routeId: "R3" },
  { id: "accra-tamale", from: ACCRA, to: TAMALE },
];

const ROUTES = ["R1", "R2", "R3"] as const;
const ROUTE_NAME: Record<string, string> = { R1: "correspondent", R2: "payout", R3: "stablecoin" };
const FALLBACK_AMOUNTS: Record<string, number> = { R1: 66237, R2: 79154, R3: 41820 };

const ACCENT: [number, number, number] = [1 / 255, 43 / 255, 1];
const FOCUS_PHI = Math.PI - ((2 * Math.PI) / 180 - Math.PI / 2);
const FOCUS_THETA = 0.18;
const SPEED = 0.0016;

interface TrafficRow {
  routeId: string;
  amountEur: number;
}

function useSimulatedTraffic() {
  const [amounts, setAmounts] = useState<Record<string, number>>(FALLBACK_AMOUNTS);

  useEffect(() => {
    let rows: TrafficRow[] = [];
    let cursor = 0;
    let alive = true;
    fetch("/spec/fixtures/traffic.jsonl")
      .then((response) => (response.ok ? response.text() : ""))
      .then((text) => {
        if (!alive) return;
        rows = text
          .split("\n")
          .filter(Boolean)
          .map((line) => JSON.parse(line) as TrafficRow);
      })
      .catch(() => undefined);

    const interval = window.setInterval(() => {
      if (rows.length) {
        const row = rows[cursor % rows.length];
        cursor += 1;
        setAmounts((current) => ({ ...current, [row.routeId]: row.amountEur }));
        return;
      }
      setAmounts((current) =>
        Object.fromEntries(
          Object.entries(current).map(([id, value]) => [id, Math.max(8000, value + (Math.random() - 0.5) * 6000)]),
        ),
      );
    }, 900);

    return () => {
      alive = false;
      window.clearInterval(interval);
    };
  }, []);

  return amounts;
}

const euros = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 });
const formatAmount = (value: number) => `€${euros.format(value / 1000)}k`;

const PYRAMID_FACES = [
  "rotateY(0deg) translateZ(4px) rotateX(19.5deg)",
  "rotateY(120deg) translateZ(4px) rotateX(19.5deg)",
  "rotateY(240deg) translateZ(4px) rotateX(19.5deg)",
  "rotateX(-90deg) rotateZ(60deg) translateY(4px)",
];
const PYRAMID_SHADES = ["#0a0a0a", "#2b2b2b", "#4a4a4a", "#1a1a1a"];

function Pyramid() {
  return (
    <span className="landing-pyramid" aria-hidden>
      {PYRAMID_FACES.map((transform, index) => (
        <span
          key={transform}
          className="landing-pyramid-face"
          style={{ transform, borderBottomColor: PYRAMID_SHADES[index] }}
        />
      ))}
    </span>
  );
}

const SIDE_LAYOUT: Record<Side, React.CSSProperties> = {
  top: { bottom: "anchor(top)", left: "anchor(center)", translate: "-50% 0", flexDirection: "column-reverse" },
  bottom: { top: "anchor(bottom)", left: "anchor(center)", translate: "-50% -12px", flexDirection: "column" },
  left: { bottom: "anchor(top)", right: "anchor(center)", translate: "6px 0", flexDirection: "row-reverse", alignItems: "flex-end" },
  right: { bottom: "anchor(top)", left: "anchor(center)", translate: "-6px 0", flexDirection: "row", alignItems: "flex-end" },
};

export default function LandingGlobe() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const drag = useRef({ phi: 0, theta: 0 });
  const offset = useRef({ phi: 0, theta: 0 });
  const paused = useRef(false);
  const amounts = useSimulatedTraffic();

  useEffect(() => {
    const onMove = (event: PointerEvent) => {
      if (!pointer.current) return;
      drag.current = {
        phi: (event.clientX - pointer.current.x) / 300,
        theta: (event.clientY - pointer.current.y) / 1000,
      };
    };
    const onUp = () => {
      if (!pointer.current) return;
      offset.current = {
        phi: offset.current.phi + drag.current.phi,
        theta: offset.current.theta + drag.current.theta,
      };
      drag.current = { phi: 0, theta: 0 };
      pointer.current = null;
      paused.current = false;
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("pointerup", onUp, { passive: true });
    window.addEventListener("pointercancel", onUp, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let globe: ReturnType<typeof createGlobe> | null = null;
    let frame = 0;
    let phi = 0;

    const init = () => {
      const width = canvas.offsetWidth;
      if (width === 0 || globe) return;
      globe = createGlobe(canvas, {
        devicePixelRatio: Math.min(window.devicePixelRatio || 1, 2),
        width,
        height: width,
        phi: FOCUS_PHI,
        theta: FOCUS_THETA,
        dark: 0,
        diffuse: 1.5,
        mapSamples: 16000,
        mapBrightness: 10,
        baseColor: [1, 1, 1],
        markerColor: [0, 0, 0],
        glowColor: [0.95, 0.95, 0.96],
        markerElevation: 0.02,
        markers: NODES.map((node) => ({ location: node.location, size: 0.012, id: node.id })),
        arcs: CORRIDORS.map((corridor) => ({ from: corridor.from, to: corridor.to, id: corridor.id })),
        arcColor: ACCENT,
        arcWidth: 0.5,
        arcHeight: 0.25,
        opacity: 0.75,
      });

      const tick = () => {
        if (!paused.current && !reduced) phi += SPEED;
        globe?.update({
          phi: FOCUS_PHI + phi + offset.current.phi + drag.current.phi,
          theta: FOCUS_THETA + offset.current.theta + drag.current.theta,
        });
        frame = requestAnimationFrame(tick);
      };
      tick();
      requestAnimationFrame(() => {
        canvas.style.opacity = "1";
      });
    };

    const resize = new ResizeObserver(() => {
      const width = canvas.offsetWidth;
      if (!globe) init();
      else if (width > 0) globe.update({ width, height: width });
    });
    resize.observe(canvas);
    init();

    return () => {
      resize.disconnect();
      cancelAnimationFrame(frame);
      globe?.destroy();
    };
  }, []);

  return (
    <div className="relative aspect-square w-full select-none">
      <canvas
        ref={canvasRef}
        aria-label="Globe showing Sylo's France to Ghana payment corridors"
        className="size-full cursor-grab touch-none rounded-full opacity-0 transition-opacity duration-[1200ms] ease-out active:cursor-grabbing [contain:layout_paint_size]"
        onPointerDown={(event) => {
          pointer.current = { x: event.clientX, y: event.clientY };
          paused.current = true;
        }}
      />
      {NODES.map((node) => (
        <span
          key={node.id}
          className="landing-node"
          style={
            {
              positionAnchor: `--cobe-${node.id}`,
              opacity: `var(--cobe-visible-${node.id}, 0)`,
              filter: `blur(calc((1 - var(--cobe-visible-${node.id}, 0)) * 8px))`,
              ...SIDE_LAYOUT[node.side],
            } as React.CSSProperties
          }
        >
          <Pyramid />
          <span className="landing-node-label">
            {node.label}
            <span className="text-ink-3"> · {node.role}</span>
          </span>
        </span>
      ))}
      <span
        className="landing-traffic"
        style={
          {
            positionAnchor: "--cobe-arc-r2",
            top: "anchor(center)",
            left: "anchor(center)",
            translate: "56px -20%",
            opacity: "var(--cobe-visible-arc-r2, 0)",
            filter: "blur(calc((1 - var(--cobe-visible-arc-r2, 0)) * 8px))",
          } as React.CSSProperties
        }
      >
        {ROUTES.map((routeId) => (
          <span key={routeId} className="landing-traffic-row">
            <span>{routeId}</span>
            <span className="text-white/55">{ROUTE_NAME[routeId]}</span>
            <span className="ml-auto">{formatAmount(amounts[routeId] ?? 0)}</span>
          </span>
        ))}
        <span className="landing-traffic-foot">simulated traffic</span>
      </span>
    </div>
  );
}
