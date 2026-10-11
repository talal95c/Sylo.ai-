import { afterEach, describe, expect, it, vi } from "vitest";
import {
  accountDiffersFromVerified,
  orderForMatchedPayment,
  submitIntake,
  type IntakeResponse,
} from "../intake";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("invoice intake helpers", () => {
  it("maps only the two recorded executable orders", () => {
    expect(orderForMatchedPayment("PAY-2026-0001")).toBe("legit");
    expect(orderForMatchedPayment("PAY-2026-0002")).toBe("diverted");
    expect(orderForMatchedPayment(null)).toBeNull();
    expect(orderForMatchedPayment("unknown")).toBeNull();
  });

  it("detects account changes using the last four digits", () => {
    expect(accountDiffersFromVerified("GH•• •••• 9083", "GH•• •••• 2207")).toBe(true);
    expect(accountDiffersFromVerified("GH•• •••• 2207", "GH•• •••• 2207")).toBe(false);
    expect(accountDiffersFromVerified(null, "GH•• •••• 2207")).toBe(false);
  });

  it("posts the document text to the live intake endpoint", async () => {
    const result: IntakeResponse = {
      intake: { fields: { accountHolder: { value: "Savanna Shea Exports Ltd" } } },
      matchedOrder: "PAY-2026-0001",
      decision: { risk: { score: 12, tier: "LOW" } },
    };
    const fetchMock = vi.fn().mockResolvedValue(Response.json(result));
    vi.stubGlobal("fetch", fetchMock);

    await expect(submitIntake("invoice body")).resolves.toEqual(result);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/v1\/intake$/),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: "invoice body" }),
      },
    );
  });

  it("surfaces engine details and gives a live-engine message when unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        Response.json({ detail: "document is too long" }, { status: 422 }),
      ),
    );
    await expect(submitIntake("invoice")).rejects.toThrow(
      "Engine refused: document is too long",
    );

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(submitIntake("invoice")).rejects.toThrow(
      "Engine unreachable: check the connection or switch to Replay",
    );
  });
});
