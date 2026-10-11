"use client";

import createGlobe from "cobe";
import { greatCirclePoint } from "@/lib/arcDots";
import { useEffect, useRef } from "react";

const LYON: [number, number] = [45.764, 4.836];
const TAMALE: [number, number] = [9.403, -0.842];
const ACCENT: [number, number, number] = [1 / 255, 43 / 255, 1];

// Dotted ground track Lyon → Tamale, evenly spaced along the great circle.
const CORRIDOR_DOTS = (() => {
  const from = { lat: LYON[0], lng: LYON[1] };
  const to = { lat: TAMALE[0], lng: TAMALE[1] };
  const count = 36;
  return Array.from({ length: count - 1 }, (_, index) => {
    const { lat, lng } = greatCirclePoint(from, to, (index + 1) / count);
    return { location: [lat, lng] as [number, number], size: 0.0055 };
  });
})();

const FOCUS_PHI = Math.PI - ((2 * Math.PI) / 180 - Math.PI / 2);
const FOCUS_THETA = 0.15;

export default function LandingGlobe() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const drag = useRef<{ x: number; offset: number } | null>(null);
  const offset = useRef(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    let width = canvas.offsetWidth;

    const globe = createGlobe(canvas, {
      devicePixelRatio: dpr,
      width: width * dpr,
      height: width * dpr,
      phi: FOCUS_PHI,
      theta: FOCUS_THETA,
      dark: 0,
      diffuse: 0.4,
      mapSamples: 16000,
      mapBrightness: 1.2,
      baseColor: [1, 1, 1],
      markerColor: ACCENT,
      glowColor: [1, 1, 1],
      markers: [
        { location: LYON, size: 0.025, id: "lyon" },
        { location: TAMALE, size: 0.025, id: "tamale" },
        ...CORRIDOR_DOTS,
      ],
      markerElevation: 0.01,
    });

    const onResize = () => {
      width = canvas.offsetWidth;
      globe.update({ width: width * dpr, height: width * dpr });
    };
    window.addEventListener("resize", onResize);

    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = (now - start) / 1000;
      const sway = reduced ? 0 : Math.sin(t * 0.18) * 0.22;
      globe.update({ phi: FOCUS_PHI + sway + offset.current });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    requestAnimationFrame(() => {
      canvas.style.opacity = "1";
    });

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
      globe.destroy();
    };
  }, []);

  return (
    <div className="relative aspect-square w-full">
      <canvas
        ref={canvasRef}
        aria-label="Globe showing the Lyon to Tamale payment corridor"
        className="size-full cursor-grab opacity-0 transition-opacity duration-[1200ms] ease-out active:cursor-grabbing [contain:layout_paint_size]"
        onPointerDown={(event) => {
          drag.current = { x: event.clientX, offset: offset.current };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          if (!drag.current) return;
          offset.current = drag.current.offset + (event.clientX - drag.current.x) / 260;
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
      />
      <span className="landing-pin" style={{ positionAnchor: "--cobe-lyon", opacity: "var(--cobe-visible-lyon, 0)" } as React.CSSProperties}>
        Lyon <span className="text-ink-3">· payer</span>
      </span>
      <span className="landing-pin" style={{ positionAnchor: "--cobe-tamale", opacity: "var(--cobe-visible-tamale, 0)", top: "anchor(bottom)", bottom: "auto", translate: "-50% 10px" } as React.CSSProperties}>
        Tamale <span className="text-ink-3">· supplier</span>
      </span>
    </div>
  );
}
