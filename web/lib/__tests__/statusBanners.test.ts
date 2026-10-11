import { describe, expect, it } from "vitest";
import { selectVisibleBanners } from "../statusBanners";

describe("selectVisibleBanners", () => {
  it("shows the most severe banners first and caps the stack", () => {
    const result = selectVisibleBanners([
      { key: "rail", severity: 2 },
      { key: "incident", severity: 4 },
      { key: "kill", severity: 3 },
    ]);

    expect(result.map(({ key }) => key)).toEqual(["incident", "kill"]);
  });

  it("keeps degraded mode visible when more severe banners fill the stack", () => {
    const result = selectVisibleBanners([
      { key: "rail", severity: 2 },
      { key: "degraded", severity: 1, degraded: true },
      { key: "incident", severity: 4 },
      { key: "kill", severity: 3 },
    ]);

    expect(result.map(({ key }) => key)).toEqual(["incident", "degraded"]);
  });
});
