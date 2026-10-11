export interface LabelAnchor {
  id: string;
  x: number;
  y: number;
  preferred: "above" | "below";
}

// Decides which side of its geo anchor each label pill sits on, so two close
// anchors never get labels on the same side pointing at the wrong dot. Works
// on screen coordinates: the anchor higher on screen (smaller y) gets its
// label above, the lower one below.
export function labelSides(
  anchors: LabelAnchor[],
  near = { dx: 160, dy: 90 },
): Record<string, "above" | "below"> {
  const sides: Record<string, "above" | "below"> = {};
  anchors.forEach((anchor, index) => {
    let nearestIndex = -1;
    let nearestDistance = Infinity;
    anchors.forEach((other, otherIndex) => {
      if (otherIndex === index) return;
      const dx = Math.abs(other.x - anchor.x);
      const dy = Math.abs(other.y - anchor.y);
      if (dx >= near.dx || dy >= near.dy) return;
      const distance = Math.hypot(dx, dy);
      if (distance < nearestDistance) {
        nearestIndex = otherIndex;
        nearestDistance = distance;
      }
    });
    const nearest = nearestIndex === -1 ? null : anchors[nearestIndex];
    if (!nearest) {
      sides[anchor.id] = anchor.preferred;
      return;
    }
    const dy = nearest.y - anchor.y;
    if (Math.abs(dy) >= 4) {
      sides[anchor.id] = dy > 0 ? "above" : "below";
      return;
    }
    // Almost the same height: the pair must end up on opposite sides, and the
    // anchor that comes first in input order keeps its own preference.
    if (nearestIndex > index) {
      sides[anchor.id] = anchor.preferred;
      return;
    }
    const otherSide = sides[nearest.id] ?? nearest.preferred;
    sides[anchor.id] = otherSide === "above" ? "below" : "above";
  });
  return sides;
}
