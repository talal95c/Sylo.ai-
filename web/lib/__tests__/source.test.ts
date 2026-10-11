import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SyloEvent } from "../events";
import { createReplaySource, type ScenarioName } from "../source";

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
