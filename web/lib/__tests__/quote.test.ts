import { afterEach, describe, expect, it, vi } from "vitest";
import { EngineError, fetchQuote, INVOICE_AMOUNT, submitPayment } from "../quote";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("fetchQuote", () => {
  it("returns the engine's quote untouched", async () => {
    const quote = { quoteId: "Q-0001", executable: true, route: { chosen: "R3" } };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(quote)));
    vi.stubGlobal("fetch", fetchMock);
    await expect(fetchQuote("legit", INVOICE_AMOUNT)).resolves.toEqual(quote);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ order: "legit" });
  });

  it("sends a custom amount for pricing", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);
    await fetchQuote("diverted", 12000);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ order: "diverted", amount: "12000.00" });
  });

  it("falls back to the recorded quote, labelled, when the engine is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    const quote = await fetchQuote("diverted", INVOICE_AMOUNT);
    expect(quote.recorded).toBe(true);
    expect(quote.executable).toBe(false);
    expect(quote.route.chosen).toBe("R3");
    expect(quote.rails.every((rail) => rail.simulated)).toBe(true);
  });

  it("does not invent a price for a custom amount offline", async () => {
    vi.stubEnv("NEXT_PUBLIC_SOURCE", "replay");
    await expect(fetchQuote("legit", 12000)).rejects.toBeInstanceOf(EngineError);
  });

  it("surfaces engine refusals instead of falling back", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"detail":"bad"}', { status: 422 })));
    await expect(fetchQuote("legit", INVOICE_AMOUNT)).rejects.toMatchObject({ status: 422, detail: "bad" });
  });
});

describe("submitPayment", () => {
  it("submits the quote with an idempotency key", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"paymentId":"PAY-2026-0001"}'));
    vi.stubGlobal("fetch", fetchMock);
    await submitPayment("Q-0007");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/v1\/payments$/);
    expect(JSON.parse(init.body)).toEqual({ quoteId: "Q-0007" });
    expect(init.headers["Idempotency-Key"]).toBe("web-Q-0007");
  });
});
