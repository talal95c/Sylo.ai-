export interface Rect {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export interface OccluderRect extends Rect {
  width: number;
  height: number;
}

export type OccluderSide = "left" | "right" | "bottom";

export interface Occluder {
  side: OccluderSide;
  rect: OccluderRect;
}

const EDGE_MARGIN = 16;
const TOP_MARGIN = 76;
const MIN_FREE_WIDTH_RATIO = 0.45;

// The area of the canvas not covered by panels. Returns null when the
// remaining strip is too narrow for an offset to make sense.
export function freeRect(
  occluders: Occluder[],
  width: number,
  height: number,
): Rect | null {
  let left = EDGE_MARGIN;
  let right = width - EDGE_MARGIN;
  let bottom = height - EDGE_MARGIN;
  for (const occluder of occluders) {
    const rect = occluder.rect;
    if (rect.width <= 0 || rect.height <= 0) continue;
    if (occluder.side === "left") {
      left = Math.max(left, rect.right + EDGE_MARGIN);
    } else if (occluder.side === "right") {
      // A collapsed feed pill must not push the globe sideways.
      if (rect.height > 200) right = Math.min(right, rect.left - EDGE_MARGIN);
    } else {
      bottom = Math.min(bottom, rect.top - EDGE_MARGIN);
    }
  }
  if (right - left < width * MIN_FREE_WIDTH_RATIO) return null;
  return { left, right, top: TOP_MARGIN, bottom };
}

export function freeCenter(rect: Rect) {
  return { cx: (rect.left + rect.right) / 2, cy: (rect.top + rect.bottom) / 2 };
}

// Offset passed to THREE.PerspectiveCamera.setViewOffset so that the point
// the camera looks at lands on (cx, cy) instead of the canvas centre.
export function viewOffsetFor(width: number, height: number, cx: number, cy: number) {
  return { x: width / 2 - cx, y: height / 2 - cy };
}

// How much to raise event camera altitudes so the focused hop stays inside
// the free rect. 1 = unchanged, up to 1.6 = pull back.
export function altitudeFactor(free: Rect | null, width: number, height: number) {
  if (!free) return 1;
  const fit = Math.min(
    (free.right - free.left) / width,
    (free.bottom - free.top) / height,
  );
  return Math.max(1, Math.min(1.6, 1 / (fit * 1.15)));
}
