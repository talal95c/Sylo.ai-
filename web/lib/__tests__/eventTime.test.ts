import { describe, expect, it } from "vitest";
import { formatEventTime } from "../eventTime";

describe("formatEventTime", () => {
  it("shows replay times relative to the scenario start", () => {
    const start = "2026-10-11T09:00:00.000Z";
    expect(formatEventTime(start, "replay", start)).toBe("+0 s");
    expect(formatEventTime("2026-10-11T09:00:12.900Z", "replay", start)).toBe("+12 s");
    expect(formatEventTime("2026-10-11T09:01:04.000Z", "replay", start)).toBe("+1 min 04 s");
  });

  it("shows live timestamps in the viewer's local time", () => {
    const timestamp = "2026-10-11T09:01:04.000Z";
    const date = new Date(timestamp);
    const expected = [date.getHours(), date.getMinutes(), date.getSeconds()]
      .map((value) => String(value).padStart(2, "0"))
      .join(":");
    expect(formatEventTime(timestamp, "live")).toBe(expected);
  });
});
