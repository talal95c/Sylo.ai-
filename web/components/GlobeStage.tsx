"use client";

import dynamic from "next/dynamic";

import type { GlobeCanvasProps } from "./GlobeCanvas";

// WebGL and react-globe.gl need the browser: never render the globe on the server.
const GlobeCanvas = dynamic(() => import("./GlobeCanvas"), {
  ssr: false,
  loading: () => <div className="globe-loading" aria-hidden="true" />,
});

export default function GlobeStage(props: GlobeCanvasProps) {
  return (
    <div className="globe-layer" aria-hidden="true">
      <GlobeCanvas {...props} />
    </div>
  );
}
