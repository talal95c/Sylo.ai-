import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { parseJsonl, type SyloEvent } from "../events";
import { shortNames, type Geo } from "../geo";
import {
  canAnswerSupplier,
  canAttack,
  canRunScenario,
  describeEvent,
  initialState,
  reduce,
  type ViewState,
} from "../store";

const specDir = new URL("../../../spec/", import.meta.url);
const fixture = (name: string): SyloEvent[] =>
  parseJsonl(readFileSync(fileURLToPath(new URL(`fixtures/${name}.jsonl`, specDir)), "utf8"));
const geo = JSON.parse(readFileSync(fileURLToPath(new URL("geo/institutions.json", specDir)), "utf8")) as Geo;

const play = (...files: string[]): ViewState =>
  files.flatMap(fixture).reduce((state, event) => reduce(state, event), initialState());

describe("fixtures through the reducer", () => {
  it("scene1: the legit payment is credited over the five hops of R3", () => {
    const state = play("scene1-legit");
    expect(state.payment.status).toBe("credited");
    expect(state.payment.tier).toBe("LOW");
    expect(state.payment.score).toBe(10);
    expect(state.selectedRouteId).toBe("R3");
    expect(state.hops).toHaveLength(5);
    expect(state.hops.every((h) => h.state === "settled")).toBe(true);
    expect(state.hops[2].kind).toBe("chain");
    expect(state.routes.find((r) => r.routeId === "R4")?.status).toBe("EXCLUDED");
    expect(state.held).toBeNull();
    expect(state.credited?.at).toBe("supplier_ssx");
    expect(state.feed.length).toBeGreaterThanOrEqual(15);
  });

  it("scene2: the diverted payment is held in escrow and waits for the supplier", () => {
    const state = play("scene2-diverted");
    expect(state.payment.status).toBe("awaiting_supplier");
    expect(state.payment.tier).toBe("MEDIUM");
    expect(state.payment.score).toBe(64);
    expect(state.payment.beneficiary?.knownAccount).toBe(false);
    expect(state.chain.lock).toBe("locked");
    expect(state.held?.reasons).toHaveLength(4);
    expect(state.held?.hop).toBe(2);
    expect(state.hops[2].state).toBe("active");
  });

  it("scene2 + deny: revoked, refunded hop by hop and stopped", () => {
    const state = play("scene2-diverted", "scene2-deny");
    expect(state.payment.status).toBe("stopped");
    expect(state.chain.lock).toBe("revoked");
    expect(state.chain.refund?.to).toBe("payer_rhone");
    expect(state.hops.filter((h) => h.index <= 2).every((h) => h.state === "refunded")).toBe(true);
    expect(state.hops[3].state).toBe("pending");
    expect(state.stopped?.headline).toBe("Payment stopped. EUR 85,000 returned to Rhône Cosmétiques.");
  });

  it("scene2 + confirm: released from escrow and credited", () => {
    const state = play("scene2-diverted", "scene2-confirm");
    expect(state.payment.status).toBe("credited");
    expect(state.chain.lock).toBe("open");
    expect(state.chain.executed).toBe(true);
    expect(state.hops.every((h) => h.state === "settled")).toBe(true);
    expect(state.credited?.at).toBe("mule_bank");
  });

  it("scene2 + deny + scene2b: the release attack reverts and the payment stays stopped", () => {
    const state = play("scene2-diverted", "scene2-deny", "scene2b-release-revoked");
    expect(state.payment.status).toBe("stopped");
    expect(state.attack?.attempted).toBe(true);
    expect(state.attack?.reverted).toBe(true);
    expect(state.attack?.reason).toBe("PaymentNotReleasable");
    expect(state.chainEvents.at(-1)?.type).toBe("tx.reverted");
  });
});

describe("reducer rules", () => {
  it("ignores events it has already seen (a reconnect can replay the buffer)", () => {
    const events = fixture("scene1-legit");
    const once = events.reduce(reduce, initialState());
    const replayed = events.slice(5).reduce(reduce, once);
    expect(replayed.feed).toHaveLength(once.feed.length);
    expect(replayed.payment.status).toBe("credited");
  });

  it("applies system.mode whatever its seq, without touching the payment", () => {
    const state = play("scene1-legit");
    const mode = { risk: "model", chain: "fuji", llm: "off", rails: "simulated", degraded: ["llm"] };
    const next = reduce(state, { v: 1, seq: 0, id: "evt-000000", ts: "2026-10-11T09:00:00.000Z", type: "system.mode", paymentId: null, simulated: false, data: mode });
    expect(next.mode?.chain).toBe("fuji");
    expect(next.payment.status).toBe("credited");
    expect(next.lastSeq).toBe(state.lastSeq);
  });

  it("session.reset clears the view but keeps the engine mode", () => {
    const withMode = reduce(play("scene1-legit"), { v: 1, seq: 0, id: "evt-000000", ts: "2026-10-11T09:00:00.000Z", type: "system.mode", paymentId: null, simulated: false, data: { risk: "rules", chain: "mock", llm: "off", rails: "simulated", degraded: [] } });
    const reset = reduce(withMode, { v: 1, seq: 30, id: "evt-000030", ts: "2026-10-11T09:01:00.000Z", type: "session.reset", paymentId: null, simulated: false, data: {} });
    expect(reset.payment.status).toBe("idle");
    expect(reset.feed).toHaveLength(0);
    expect(reset.mode?.risk).toBe("rules");
    expect(reset.run).toBe(withMode.run + 1);
  });

  it("scenario.started resets the view even when its seq restarts (replay of a new fixture)", () => {
    const state = play("scene1-legit", "scene2-diverted");
    expect(state.payment.id).toBe("PAY-2026-0002");
    expect(state.payment.status).toBe("awaiting_supplier");
    expect(state.feed[0].type).toBe("scenario.started");
    expect(state.feed).toHaveLength(15);
  });

  it("keeps unknown event types in the feed and otherwise ignores them", () => {
    const state = play("scene1-legit");
    const next = reduce(state, { v: 1, seq: 99, id: "evt-000099", ts: "2026-10-11T09:01:00.000Z", type: "rail.down", paymentId: null, simulated: true, data: { rail: "R1" } });
    expect(next.feed.at(-1)?.type).toBe("rail.down");
    expect(next.feed.at(-1)?.family).toBe("system");
    expect(next.payment).toEqual(state.payment);
  });
});

describe("feed text and controls", () => {
  it("describes every fixture event in plain words", () => {
    const names = shortNames(geo);
    const files = ["scene1-legit", "scene2-diverted", "scene2-deny", "scene2-confirm", "scene2b-release-revoked"];
    for (const event of files.flatMap(fixture)) {
      const text = describeEvent(event, names);
      expect(text.length).toBeGreaterThan(5);
      expect(text).not.toMatch(/undefined|NaN|\[object/);
    }
    const legSent = fixture("scene1-legit").find((e) => e.type === "leg.sent" && (e.data as { kind: string }).kind === "chain");
    expect(describeEvent(legSent!, names)).toBe("Leg 3 sent: EuroLedger CASP → Kente Digital Assets on Avalanche C-Chain");
  });

  it("enables only the actions that apply", () => {
    expect(canRunScenario(initialState())).toBe(true);
    const waiting = play("scene2-diverted");
    expect(canRunScenario(waiting)).toBe(false);
    expect(canAnswerSupplier(waiting)).toBe(true);
    expect(canAttack(waiting)).toBe(false);
    const denied = play("scene2-diverted", "scene2-deny");
    expect(canAnswerSupplier(denied)).toBe(false);
    expect(canAttack(denied)).toBe(true);
    expect(canRunScenario(denied)).toBe(true);
    expect(canAttack(play("scene2-diverted", "scene2-deny", "scene2b-release-revoked"))).toBe(false);
    expect(canAttack(play("scene2-diverted", "scene2-confirm"))).toBe(false);
  });
});
