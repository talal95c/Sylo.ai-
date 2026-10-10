import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { parseEvent, parseJsonl, type SyloEvent } from "../events";
import { arcApexAltitude, CHAIN, greatCircleMidpoint, institution } from "../geo";
import { availableActions, initialState, reduce, type ViewState } from "../store";

// The fixtures recorded by the engine: /spec/fixtures, read straight from the repository.
const FIXTURES = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../spec/fixtures");

function fixture(name: string): SyloEvent[] {
  const file = path.join(FIXTURES, name);
  if (!existsSync(file)) throw new Error(`fixture not found: ${file} (record it with \`make fixtures\`)`);
  const events = parseJsonl(readFileSync(file, "utf8"));
  if (events.length === 0) throw new Error(`fixture is empty: ${file}`);
  return events;
}

function replay(state: ViewState, ...names: string[]): ViewState {
  return names.flatMap(fixture).reduce(reduce, state);
}

function event(seq: number, type: string, data: Record<string, unknown> = {}): SyloEvent {
  const parsed = parseEvent({ v: 1, seq, id: `evt-${String(seq).padStart(6, "0")}`, ts: "2026-10-11T09:00:00.000Z", type, paymentId: null, simulated: false, data });
  if (!parsed) throw new Error("invalid test event");
  return parsed;
}

describe("fixtures replayed through reduce", () => {
  it("scene1-legit ends credited", () => {
    const state = replay(initialState, "scene1-legit.jsonl");
    expect(state.payment.status).toBe("credited");
    expect(state.payment.id).toBe("PAY-2026-0001");
    expect(state.payment.tier).toBe("LOW");
    expect(state.selectedRouteId).toBe("R3");
    expect(state.routes.find((route) => route.routeId === "R4")?.status).toBe("EXCLUDED");
    expect(state.hops).toHaveLength(5);
    expect(state.hops.every((hop) => hop.state === "settled")).toBe(true);
    expect(state.hops[2].kind).toBe("chain");
    expect(state.payment.sealed?.txHash).toMatch(/^0x[0-9a-f]{64}$/);
    expect(state.payment.credited?.at).toBe("supplier_ssx");
    expect(state.held).toBeNull();
    expect(state.feed.length).toBeGreaterThanOrEqual(15);
    expect(availableActions(state)).toEqual({ run: true, supplierAnswer: false, attack: false });
  });

  it("scene2-diverted stops in escrow and waits for the supplier", () => {
    const state = replay(initialState, "scene2-diverted.jsonl");
    expect(state.payment.status).toBe("awaiting_supplier");
    expect(state.payment.tier).toBe("MEDIUM");
    expect(state.payment.beneficiary?.knownAccount).toBe(false);
    expect(state.held?.headline).toBeTruthy();
    expect(state.held?.reasons).toHaveLength(4);
    expect(state.held?.protection).toBeTruthy();
    expect(state.held?.nextStep).toBeTruthy();
    expect(state.escrow).toMatchObject({ status: "locked", hop: 2 });
    expect(state.hops.map((hop) => hop.state)).toEqual(["settled", "settled", "active", "pending"]);
    expect(availableActions(state)).toEqual({ run: false, supplierAnswer: true, attack: false });
  });

  it("scene2 + deny ends stopped", () => {
    const state = replay(initialState, "scene2-diverted.jsonl", "scene2-deny.jsonl");
    expect(state.payment.status).toBe("stopped");
    expect(state.payment.stopped?.headline).toBeTruthy();
    expect(state.verification?.result).toBe("DENIED");
    expect(state.verification?.answerText).toBeTruthy();
    expect(state.revocation).not.toBeNull();
    expect(state.escrow).toMatchObject({ status: "refunded", to: "payer_rhone" });
    expect(state.hops.map((hop) => hop.state)).toEqual(["refunded", "refunded", "refunded", "pending"]);
    expect(state.attack).toBeNull();
    expect(availableActions(state)).toEqual({ run: true, supplierAnswer: false, attack: true });
  });

  it("scene2 + confirm ends credited", () => {
    const state = replay(initialState, "scene2-diverted.jsonl", "scene2-confirm.jsonl");
    expect(state.payment.status).toBe("credited");
    expect(state.verification?.result).toBe("CONFIRMED");
    expect(state.escrow?.status).toBe("released");
    expect(state.revocation).toBeNull();
    expect(state.hops.every((hop) => hop.state === "settled")).toBe(true);
    expect(state.payment.credited?.at).toBe("mule_bank");
    expect(availableActions(state).attack).toBe(false);
  });

  it("scene2 + deny + scene2b ends stopped with the attack reverted", () => {
    const state = replay(initialState, "scene2-diverted.jsonl", "scene2-deny.jsonl", "scene2b-release-revoked.jsonl");
    expect(state.payment.status).toBe("stopped");
    expect(state.attack?.reverted).toBe(true);
    expect(state.attack?.reason).toBe("PaymentNotReleasable");
    expect(state.lastRevert?.text).toContain("PaymentNotReleasable");
    expect(state.feed.some((item) => item.text.includes("PaymentNotReleasable"))).toBe(true);
  });

  it("replaying a scene after another one starts a clean view (seq restarts at 1)", () => {
    const afterAttack = replay(initialState, "scene2-diverted.jsonl", "scene2-deny.jsonl", "scene2b-release-revoked.jsonl");
    const state = replay(afterAttack, "scene1-legit.jsonl");
    expect(state.payment.status).toBe("credited");
    expect(state.payment.id).toBe("PAY-2026-0001");
    expect(state.attack).toBeNull();
    expect(state.held).toBeNull();
    expect(state.revocation).toBeNull();
    expect(state.feed).toHaveLength(fixture("scene1-legit.jsonl").length);
    expect(state.applied).toBeGreaterThan(afterAttack.applied);
  });

  it("a replayed session buffer (reconnect) rebuilds the same view", () => {
    const once = replay(initialState, "scene2-diverted.jsonl");
    const twice = replay(once, "scene2-diverted.jsonl");
    expect(twice.payment).toEqual(once.payment);
    expect(twice.hops.map((hop) => hop.state)).toEqual(once.hops.map((hop) => hop.state));
    expect(twice.feed).toHaveLength(once.feed.length);
  });
});

describe("sequence rule", () => {
  it("ignores events whose seq is not greater than the last one seen", () => {
    const events = fixture("scene1-legit.jsonl");
    const state = events.reduce(reduce, initialState);
    const again = events.slice(1).reduce(reduce, state);
    expect(again).toBe(state);
  });

  it("always applies system.mode and never moves lastSeq with it", () => {
    const state = replay(initialState, "scene2-diverted.jsonl");
    const mode = { risk: "rules", chain: "mock", llm: "off", rails: "simulated", degraded: ["chain"] };
    const next = reduce(state, event(0, "system.mode", mode));
    expect(next.mode).toEqual(mode);
    expect(next.lastSeq).toBe(state.lastSeq);
    expect(next.payment).toBe(state.payment);
    expect(reduce(next, event(0, "system.mode", mode))).toBe(next);
  });

  it("session.reset clears the view, keeps the mode and takes its own seq", () => {
    const mode = { risk: "rules", chain: "mock", llm: "off", rails: "simulated", degraded: [] };
    const state = replay(reduce(initialState, event(0, "system.mode", mode)), "scene1-legit.jsonl");
    const next = reduce(state, event(57, "session.reset"));
    expect(next.payment.status).toBe("idle");
    expect(next.routes).toHaveLength(0);
    expect(next.hops).toHaveLength(0);
    expect(next.mode).toEqual(mode);
    expect(next.lastSeq).toBe(57);
    expect(next.feed).toHaveLength(1);
  });

  it("hands the globe a list that only ever appends or strictly shrinks, and always shows it the reset event", () => {
    const sequence: SyloEvent[] = [
      event(0, "system.mode", { risk: "rules", chain: "mock", llm: "off", rails: "simulated", degraded: [] }),
      event(40, "session.reset"),
      ...fixture("scene1-legit.jsonl"),
      event(60, "session.reset"),
      event(61, "session.reset"),
      ...fixture("scene2-diverted.jsonl").slice(0, 1),
      ...fixture("scene2-diverted.jsonl"),
      ...fixture("scene2-deny.jsonl"),
      ...fixture("scene1-legit.jsonl"),
    ];
    let state = initialState;
    let seen = 0; // what a consumer by position has handled so far
    const handled: string[] = [];
    for (const next of sequence) {
      const before = state.events;
      state = reduce(state, next);
      if (state.events === before) continue;
      if (state.events.length < seen) seen = 0;
      expect(state.events.length).toBeGreaterThan(seen);
      handled.push(...state.events.slice(seen).map((item) => item.type));
      seen = state.events.length;
      if (next.type === "session.reset" || next.type === "scenario.started") expect(handled.at(-1)).toBe(next.type);
    }
    expect(state.events.some((item) => item.type === "system.mode")).toBe(false);
    expect(state.events[0].type).toBe("scenario.started");
    expect(state.events).toHaveLength(fixture("scene1-legit.jsonl").length);
    expect(state.payment.status).toBe("credited");
  });

  it("keeps unknown event types in the feed and otherwise ignores them", () => {
    const state = replay(initialState, "scene2-diverted.jsonl");
    const next = reduce(state, event(state.lastSeq + 1, "cluster.detected", { nodes: 7 }));
    expect(next.feed).toHaveLength(state.feed.length + 1);
    expect(next.feed.at(-1)?.type).toBe("cluster.detected");
    expect(next.payment).toBe(state.payment);
    expect(next.lastSeq).toBe(state.lastSeq + 1);
  });
});

describe("geography", () => {
  it("puts the lock at the apex of the chain hop", () => {
    const from = institution("casp_eu");
    const to = institution("vasp_gh");
    expect(from && to).toBeTruthy();
    if (!from || !to) return;
    const mid = greatCircleMidpoint(from, to);
    expect(mid.lat).toBeGreaterThan(25);
    expect(mid.lat).toBeLessThan(31);
    expect(mid.lng).toBeGreaterThan(1);
    expect(mid.lng).toBeLessThan(6);
    expect(CHAIN.arcAltitude).toBe(0.45);
    expect(arcApexAltitude(from, to, CHAIN.arcAltitude)).toBeCloseTo(0.46, 1);
  });
});
