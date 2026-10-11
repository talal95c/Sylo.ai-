"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import type { ViewState } from "@/lib/store";
import type { GlobeCanvasProps } from "./GlobeCanvas";

const GlobeCanvas = dynamic(() => import("./GlobeCanvas"), {
  ssr: false,
  loading: () => null,
});

function globeTone(state: ViewState) {
  const status = state.payment?.status ?? "idle";
  if (state.attack.attempted || state.attack.reverted || status === "stopped") {
    return {
      atmosphere: "#FF8A9A",
      halo: "radial-gradient(ellipse at var(--globe-cx, 50%) var(--globe-cy, 48%), rgba(255,138,154,0.34) 0%, rgba(255,138,154,0.16) 42%, transparent 74%)",
    };
  }
  if (status === "deciding") {
    return {
      atmosphere: "#8399FF",
      halo: "radial-gradient(ellipse at var(--globe-cx, 50%) var(--globe-cy, 48%), rgba(131,153,255,0.34) 0%, rgba(131,153,255,0.16) 42%, transparent 74%)",
    };
  }
  if (status === "in_transit") {
    return {
      atmosphere: "#B3E1FF",
      halo: "radial-gradient(ellipse at var(--globe-cx, 50%) var(--globe-cy, 48%), rgba(179,225,255,0.38) 0%, rgba(179,225,255,0.17) 42%, transparent 74%)",
    };
  }
  if (status === "held" || status === "awaiting_supplier" || status === "awaiting_analyst") {
    return {
      atmosphere: "#FBBF77",
      halo: "radial-gradient(ellipse at var(--globe-cx, 50%) var(--globe-cy, 48%), rgba(251,191,119,0.34) 0%, rgba(251,191,119,0.16) 42%, transparent 74%)",
    };
  }
  if (status === "credited") {
    return {
      atmosphere: "#86EFAC",
      halo: "radial-gradient(ellipse at var(--globe-cx, 50%) var(--globe-cy, 48%), rgba(134,239,172,0.34) 0%, rgba(134,239,172,0.16) 42%, transparent 74%)",
    };
  }
  return {
    atmosphere: "#C9AAFF",
    halo: "radial-gradient(ellipse at var(--globe-cx, 50%) var(--globe-cy, 48%), rgba(201,170,255,0.32) 0%, rgba(179,225,255,0.23) 42%, transparent 74%)",
  };
}

export default function GlobeStage({
  state,
  ...props
}: Omit<GlobeCanvasProps, "atmosphereColor" | "onFrame"> & { state: ViewState }) {
  const tone = globeTone(state);
  const rootRef = useRef<HTMLDivElement>(null);
  // cacheComponents keeps /demo in a hidden <Activity> after navigation: its Effects
  // clean up (react-globe.gl disposes its renderer) but the DOM stays. Remount the
  // globe each time the Effects run again so it never comes back blank.
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setGeneration((value) => value + 1));
    return () => cancelAnimationFrame(frame);
  }, []);
  const onFrame = useCallback((cx: number, cy: number) => {
    const root = rootRef.current;
    if (!root) return;
    root.style.setProperty("--globe-cx", `${cx}px`);
    root.style.setProperty("--globe-cy", `${cy}px`);
  }, []);
  return (
    <div ref={rootRef} className="absolute inset-0" aria-label="Payment route globe">
      <motion.div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-0"
        initial={false}
        animate={{ background: tone.halo }}
        transition={{ duration: 0.7, ease: "easeInOut" }}
      />
      <div className="absolute inset-0 z-[1]">
        {generation > 0 ? (
          <GlobeCanvas
            key={generation}
            {...props}
            state={state}
            atmosphereColor={tone.atmosphere}
            onFrame={onFrame}
          />
        ) : null}
      </div>
    </div>
  );
}
