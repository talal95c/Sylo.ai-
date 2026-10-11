export function flowGraphScale(width: number, height: number, canvasWidth: number, canvasHeight: number): number {
  return Math.max(1, Math.min(1.15, width / canvasWidth, height / canvasHeight));
}
