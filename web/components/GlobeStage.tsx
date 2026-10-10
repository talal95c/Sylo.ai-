"use client";

import dynamic from "next/dynamic";
import type { GlobeCanvasProps } from "./GlobeCanvas";

const GlobeCanvas = dynamic(() => import("./GlobeCanvas"), {
  ssr: false,
  loading: () => null,
});

export default function GlobeStage(props: GlobeCanvasProps) {
  return (
    <div className="absolute inset-0" aria-label="Payment route globe">
      <GlobeCanvas {...props} />
    </div>
  );
}
