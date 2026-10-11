import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SyloEvent } from "../events";
import {
  createLiveSource,
  createReplaySource,
  EngineRequestError,
  formatInvoiceError,
  invoiceComposerVisible,
  type ScenarioName,
} from "../source";

const scenes = [
  { name: "diverted_simswap", file: "scene2-simswap.jsonl" },
  { name: "diverted_expiry", file: "samples-hold-expiry.jsonl" },
  { name: "diverted_timelock", file: "samples-time-lock.jsonl" },
  { name: "confidential", file: "samples-confidential.jsonl" },
] as const satisfies ReadonlyArray<{ name: ScenarioName; file: string }>;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("replay scenes", () => {
  it.each(scenes)("loads and parses $file", async ({ name, file }) => {
    const contents = readFileSync(
      new URL(`../../samples/fixtures/${file}`, import.meta.url),
      "utf8",
    );
    const fetchMock = vi.fn().mockResolvedValue(new Response(contents));
    vi.stubGlobal("fetch", fetchMock);
    const events: SyloEvent[] = [];
    const source = createReplaySource();

    source.start({
      onEvent: (event) => events.push(event),
      onStatus: () => {},
    });
    await source.runScenario(name, { speed: Number.POSITIVE_INFINITY });
    source.stop();

    const expected = contents
      .trim()
      .split(/\r?\n/)
      .map((line) => JSON.parse(line) as SyloEvent);
    expect(fetchMock).toHaveBeenCalledWith(`/spec/fixtures/${file}`);
    expect(events).toHaveLength(expected.length);
    expect(events.map((event) => event.type)).toEqual(
      expected.map((event) => event.type),
    );
    expect(events.map((event) => event.data)).toEqual(
      expected.map((event) => event.data),
    );
  });
});

describe("jury invoice source controls", () => {
  it("keeps the invoice composer out of Replay", () => {
    expect(invoiceComposerVisible("replay")).toBe(false);
    expect(invoiceComposerVisible("live")).toBe(true);
  });

  it("sends invoiceText with the Live diverted scenario", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const source = createLiveSource("http://engine.test/");

    await source.runScenario("diverted", {
      speed: 2,
      invoiceText: "jury invoice",
    });

    expect(fetchMock).toHaveBeenCalledWith(
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

  it("preserves 403, 422 and 429 invoice errors for inline display", () => {
    expect(formatInvoiceError(new EngineRequestError(403, "live invoice is disabled"))).toBe(
      "live invoice is disabled",
    );
    expect(formatInvoiceError(new EngineRequestError(422, "Engine request failed (422)"))).toContain(
      "2,000 characters",
    );
    expect(
      formatInvoiceError(
        new EngineRequestError(429, "one invoice run is allowed every 30 seconds", "25"),
      ),
    ).toContain("Retry in 25 seconds");
  });

  it("preserves an engine 429 detail and Retry-After header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ detail: "one invoice run is allowed every 30 seconds" }),
        {
          status: 429,
          headers: { "Content-Type": "application/json", "Retry-After": "25" },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const source = createLiveSource("http://engine.test");

    await expect(
      source.runScenario("diverted", { speed: 1, invoiceText: "jury invoice" }),
    ).rejects.toMatchObject<Partial<EngineRequestError>>({
      status: 429,
      message: "one invoice run is allowed every 30 seconds",
      retryAfter: "25",
    });
  });
});
