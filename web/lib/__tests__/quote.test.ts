import { afterEach, describe, expect, it, vi } from "vitest";
import {
  buildQuoteBody,
  EngineError,
  fetchQuote,
  INVOICE_AMOUNT,
  INVOICE_REFERENCE,
  submitPayment,
} from "../quote";

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

  it("sends a custom amount as an executable custom quote", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);
    await fetchQuote("diverted", 12000);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      custom: { amount: "12000.00", invoiceRef: INVOICE_REFERENCE, account: "verified" },
    });
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

  it("maps new bank details to the recorded diverted quote in replay mode", async () => {
    vi.stubEnv("NEXT_PUBLIC_SOURCE", "replay");
    const details = {
      account: "new" as const,
      newAccountSelected: true,
      accountNumber: "GH1234567890",
      holderName: "Savanna Shea Exports",
    };
    await expect(fetchQuote("legit", INVOICE_AMOUNT, undefined, details)).resolves.toEqual(
      await fetchQuote("diverted", INVOICE_AMOUNT),
    );
  });

  it("surfaces engine refusals instead of falling back", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('{"detail":"bad"}', { status: 422 })));
    await expect(fetchQuote("legit", INVOICE_AMOUNT)).rejects.toMatchObject({ status: 422, detail: "bad" });
  });
});

describe("buildQuoteBody", () => {
  it("keeps the recorded request for the default amount and invoice reference", () => {
    expect(buildQuoteBody("legit", INVOICE_AMOUNT)).toEqual({ order: "legit" });
  });

  it("uses a custom quote when the invoice reference changes", () => {
    expect(buildQuoteBody("legit", INVOICE_AMOUNT, { invoiceRef: "SSE-2026-119" })).toEqual({
      custom: { amount: "85000.00", invoiceRef: "SSE-2026-119", account: "verified" },
    });
  });

  it("includes user-supplied bank details for a new account", () => {
    expect(
      buildQuoteBody("legit", INVOICE_AMOUNT, {
        newAccountSelected: true,
        account: "new",
        invoiceRef: INVOICE_REFERENCE,
        accountNumber: "GH1234567890",
        holderName: "Savanna Shea Exports",
        senderDomain: "savannashea-exports.co",
      }),
    ).toEqual({
      custom: {
        amount: "85000.00",
        invoiceRef: INVOICE_REFERENCE,
        account: "new",
        accountNumber: "GH1234567890",
        holderName: "Savanna Shea Exports",
        senderDomain: "savannashea-exports.co",
      },
    });
  });

  it("retains the recorded diverted order when its recorded terms are unchanged", () => {
    expect(buildQuoteBody("diverted", INVOICE_AMOUNT)).toEqual({ order: "diverted" });
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
