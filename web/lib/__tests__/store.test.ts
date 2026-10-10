import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { SyloEvent } from "../events";
import { availableActions, initialState, reduce } from "../store";

function fixture(name: string): SyloEvent[] {
  const contents = readFileSync(
    new URL(`../../samples/fixtures/${name}.jsonl`, import.meta.url),
    "utf8",
  );
  return contents
    .trim()
    .split(/\r?\n/)
    .map((line) => JSON.parse(line) as SyloEvent);
}

function replay(...events: SyloEvent[]) {
  return events.reduce(reduce, initialState);
}

describe("store reducer", () => {
  it("replays the legitimate payment to credit across five settled hops", () => {
    const state = replay(...fixture("scene1-legit"));

    expect(state.payment?.status).toBe("credited");
    expect(state.hops).toHaveLength(5);
    expect(state.hops.every((hop) => hop.state === "settled")).toBe(true);
  });

  it("stops, revokes, and refunds a denied diverted payment", () => {
    const state = replay(
      ...fixture("scene2-diverted"),
      ...fixture("scene2-deny"),
    );

    expect(state.payment?.status).toBe("stopped");
    expect(state.revoked).toBe(true);
    expect(state.refunded).toBe(true);
    expect(state.hops.slice(0, 3).every((hop) => hop.state === "refunded")).toBe(
      true,
    );
  });

  it("credits a diverted payment after supplier confirmation", () => {
    const state = replay(
      ...fixture("scene2-diverted"),
      ...fixture("scene2-confirm"),
    );

    expect(state.payment?.status).toBe("credited");
    expect(state.released).toBe(true);
    expect(state.hops).toHaveLength(4);
    expect(state.hops.every((hop) => hop.state === "settled")).toBe(true);
  });

  it("records a rejected release attempt after the deny branch", () => {
    const state = replay(
      ...fixture("scene2-diverted"),
      ...fixture("scene2-deny"),
      ...fixture("scene2b-release-revoked"),
    );

    expect(state.payment?.status).toBe("stopped");
    expect(state.attack.reverted).toBe(true);
    expect(state.attack.reason).toBe("PaymentNotReleasable");
  });

  it("ignores duplicate sequence numbers", () => {
    const created = fixture("scene1-legit")[1];
    const state = reduce(initialState, created);
    const duplicate = {
      ...created,
      data: {
        ...created.data,
        amount: { value: "1.00", currency: "EUR" },
      },
    } as SyloEvent;

    expect(reduce(state, duplicate)).toBe(state);
    expect(state.payment?.amount.value).toBe("85000.00");
  });

  it("keeps unknown events in the feed without applying state changes", () => {
    const event = {
      v: 1,
      seq: 1,
      id: "evt-000001",
      ts: "2026-10-11T09:00:00.000Z",
      type: "future.event",
      paymentId: null,
      simulated: false,
      data: { example: true },
    } as SyloEvent;
    const state = reduce(initialState, event);

    expect(state.payment).toBeNull();
    expect(state.feed.at(-1)).toMatchObject({
      type: "future.event",
      family: "system",
      text: "Event received: future.event",
    });
  });

  it("applies system mode with sequence zero after later events", () => {
    const lateEvent = {
      ...fixture("scene1-legit")[1],
      seq: 8,
      id: "evt-000008",
    };
    const mode = {
      v: 1,
      seq: 0,
      id: "evt-000000",
      ts: "2026-10-11T09:00:00.000Z",
      type: "system.mode",
      paymentId: null,
      simulated: false,
      data: {
        risk: "rules",
        chain: "mock",
        llm: "off",
        rails: "simulated",
        degraded: [],
      },
    } as SyloEvent;
    const state = reduce(reduce(initialState, lateEvent), mode);

    expect(state.mode?.chain).toBe("mock");
    expect(state.lastSeq).toBe(8);
  });

  it("enables supplier responses only while awaiting the supplier", () => {
    const diverted = fixture("scene2-diverted");
    const state = replay(...diverted);
    const available = availableActions(state);

    expect(state.payment?.status).toBe("awaiting_supplier");
    expect(available.confirm).toBe(true);
    expect(available.deny).toBe(true);
    expect(available.runLegit).toBe(false);
    expect(available.runDiverted).toBe(false);
  });
});
