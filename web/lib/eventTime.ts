export type EventTimeMode = "live" | "replay";

export function formatEventTime(
  timestamp: string,
  mode: EventTimeMode,
  scenarioStart?: string,
): string {
  const eventTime = Date.parse(timestamp);
  if (!Number.isFinite(eventTime)) return "--";

  if (mode === "replay") {
    const startTime = Date.parse(scenarioStart ?? timestamp);
    const elapsedSeconds = Math.max(0, Math.floor((eventTime - startTime) / 1000));
    if (elapsedSeconds < 60) return `+${elapsedSeconds} s`;
    const minutes = Math.floor(elapsedSeconds / 60);
    const seconds = String(elapsedSeconds % 60).padStart(2, "0");
    return `+${minutes} min ${seconds} s`;
  }

  const date = new Date(eventTime);
  return [date.getHours(), date.getMinutes(), date.getSeconds()]
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
}
