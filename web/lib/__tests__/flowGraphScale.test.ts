import { describe, expect, it } from "vitest";
import { flowGraphScale } from "../flowGraphScale";

describe("flowGraphScale", () => {
  it("keeps the graph at its readable base size when it does not fit", () => {
    expect(flowGraphScale(1232, 500, 1360, 680)).toBe(1);
  });

  it("scales up only when extra space is available", () => {
    expect(flowGraphScale(1800, 900, 1360, 680)).toBe(1.15);
  });
});
