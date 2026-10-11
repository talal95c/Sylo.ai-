export interface LabelRect {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export interface LabelPlacement {
  side: "above" | "below";
  shiftX: number;
  hidden: boolean;
}

export function resolveLabelOverlap(
  current: LabelRect,
  alternate: LabelRect,
  obstacles: LabelRect[],
  bounds: LabelRect,
  preferredSide: "above" | "below",
): LabelPlacement {
  const oppositeSide = preferredSide === "below" ? "above" : "below";
  const overlaps = (candidate: LabelRect, obstacle: LabelRect) =>
    candidate.left < obstacle.right + 8 &&
    candidate.right > obstacle.left - 8 &&
    candidate.top < obstacle.bottom + 6 &&
    candidate.bottom > obstacle.top - 6;
  const fits = (candidate: LabelRect) =>
    candidate.left >= bounds.left &&
    candidate.right <= bounds.right &&
    candidate.top >= bounds.top &&
    candidate.bottom <= bounds.bottom;

  if (!obstacles.some((obstacle) => overlaps(current, obstacle))) {
    return { side: preferredSide, shiftX: 0, hidden: false };
  }
  if (fits(alternate) && !obstacles.some((obstacle) => overlaps(alternate, obstacle))) {
    return { side: oppositeSide, shiftX: 0, hidden: false };
  }

  for (const obstacle of obstacles) {
    for (const shiftX of [
      obstacle.right + 8 - current.left,
      obstacle.left - 8 - current.right,
    ]) {
      const shifted = {
        ...current,
        left: current.left + shiftX,
        right: current.right + shiftX,
      };
      if (fits(shifted) && !obstacles.some((item) => overlaps(shifted, item))) {
        return { side: preferredSide, shiftX, hidden: false };
      }
    }
  }
  return { side: preferredSide, shiftX: 0, hidden: true };
}
