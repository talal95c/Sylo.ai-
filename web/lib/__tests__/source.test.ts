import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createLiveSource,
  EngineRequestError,
  formatInvoiceError,
  invoiceComposerVisible,
} from "../source";

describe("jury invoice source controls", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the invoice composer out of Replay", () => {
    expect(invoiceComposerVisible("replay")).toBe(false);
    expect(invoiceComposerVisible("live")).toBe(true);
  });

  it("sends invoiceText only with the requested Live scenario", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    const source = createLiveSource("http://engine.test/");

    await source.runScenario("diverted", {
      speed: 2,
      invoiceText: "jury invoice",
    });

    expect(fetch).toHaveBeenCalledWith(
      "http://engine.test/v1/scenarios/diverted/run",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          speed: 2,
          auto: false,
          invoiceText: "jury invoice",
        }),
      },
    );
  });

  it("preserves an engine 429 message and retry header for inline display", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "one invoice run is allowed every 30 seconds" }), {
        status: 429,
        headers: { "Content-Type": "application/json", "Retry-After": "25" },
      }),
    );
    vi.stubGlobal("fetch", fetch);
    const source = createLiveSource("http://engine.test");

    await expect(
      source.runScenario("diverted", { speed: 1, invoiceText: "jury invoice" }),
    ).rejects.toMatchObject<Partial<EngineRequestError>>({
      status: 429,
      message: "one invoice run is allowed every 30 seconds",
      retryAfter: "25",
    });
  });

  it("formats 403, 422 and 429 responses for the inline form message", () => {
    expect(formatInvoiceError(new EngineRequestError(403, "live invoice is disabled"))).toBe(
      "live invoice is disabled",
    );
    expect(
      formatInvoiceError(new EngineRequestError(422, "Engine request failed (422)")),
    ).toContain("2,000 characters");
    expect(
      formatInvoiceError(
        new EngineRequestError(429, "one invoice run is allowed every 30 seconds", "25"),
      ),
    ).toContain("Retry in 25 seconds");
  });
});
