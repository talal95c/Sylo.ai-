import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { SyloEvent } from "../events";
import {
  availableActions,
  initialState,
  reduce,
  resetForSourceChange,
  riskModeForSource,
} from "../store";

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

function specFixture(name: string): SyloEvent[] {
  const contents = readFileSync(
    new URL(`../../../spec/fixtures/${name}.jsonl`, import.meta.url),
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

function synthetic(type: string, data: Record<string, unknown>, seq = 1): SyloEvent {
  return {
    v: 1,
    seq,
    id: `evt-${String(seq).padStart(6, "0")}`,
    ts: "2026-10-11T09:00:00.000Z",
    type,
    paymentId: null,
    simulated: true,
    data,
  } as SyloEvent;
}

describe("store reducer", () => {
  it("keeps fraud risk tier separate from route and action tier", () => {
    const events = fixture("scene1-legit");
    const created = events.find((event) => event.type === "payment.created")!;
    const scored = events.find((event) => event.type === "risk.scored")!;
    const route = events.find((event) => event.type === "route.selected")!;
    const committed = events.find((event) => event.type === "intent.committed")!;
    const withData = (
      event: SyloEvent,
      seq: number,
      data: Record<string, unknown>,
    ) =>
      ({
        ...event,
        seq,
        id: `evt-${String(seq).padStart(6, "0")}`,
        data,
      }) as SyloEvent;
    const risk = withData(scored, 3, {
      ...scored.data,
      tier: "HIGH",
      model: "gbm-20261011",
    });
    const selected = withData(route, 4, { ...route.data, tier: "MEDIUM" });
    const intent = withData(committed, 5, {
      ...committed.data,
      tier: "MEDIUM",
    });

    const state = replay(created, risk, selected, intent);

    expect(state.payment?.tier).toBe("HIGH");
    expect(state.payment?.actionTier).toBe("MEDIUM");
    expect(state.risk?.model).toBe("gbm-20261011");
  });

  it("uses the current source's risk model after switching from live to replay", () => {
    const event = fixture("scene1-legit").find(
      (candidate) => candidate.type === "risk.scored",
    )!;
    const liveState = reduce(initialState, {
      ...event,
      data: { ...event.data, model: "gbm-20261011" },
    });

    expect(riskModeForSource(liveState, "live")).toBe("model");

    const replayState = resetForSourceChange(liveState);
    expect(replayState.risk).toBeNull();
    expect(riskModeForSource(replayState, "replay")).toBe("model");
  });

  it("ignores a chain revert that does not follow an attack", () => {
    const state = replay(...fixture("scene2-diverted"));
    const revert = synthetic("tx.reverted", { function: "recordVerification", reason: "NonceUsed" }, state.lastSeq + 1);
    expect(reduce(state, revert).attack).toEqual(state.attack);
  });

  it("enables the swap and replay attacks for any signed payment", () => {
    const legit = availableActions(replay(...fixture("scene1-legit")));
    expect(legit.swapAttack && legit.replayAttack).toBe(true);
    const diverted = availableActions(replay(...fixture("scene2-diverted")));
    expect(diverted.swapAttack && diverted.replayAttack).toBe(true);
  });

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

  it("clears the feed on reset while preserving system mode", () => {
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
    const started = fixture("scene1-legit")[0];
    const active = reduce(reduce(initialState, mode), started);
    const reset = {
      v: 1,
      seq: started.seq + 1,
      id: `evt-${String(started.seq + 1).padStart(6, "0")}`,
      ts: "2026-10-11T09:01:00.000Z",
      type: "session.reset",
      paymentId: null,
      simulated: false,
      data: {},
    } as SyloEvent;
    const state = reduce(active, reset);

    expect(state.feed).toHaveLength(0);
    expect(state.mode).toEqual(mode.data);
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

  it("enables the live guardian scene only on a payment held in escrow", () => {
    expect(availableActions(initialState, "live").runGuardian).toBe(false);
    expect(availableActions(initialState, "replay").runGuardian).toBe(true);

    const held = replay(...fixture("scene2-diverted"));
    expect(held.held?.at).toBe("escrow");
    expect(availableActions(held, "live").runGuardian).toBe(true);
    expect(availableActions(held, "replay").runGuardian).toBe(false);
  });

  it("stores the guardian DORA draft and clears it on reset", () => {
    const events = fixture("samples-scene4-guardian");
    const incidentIndex = events.findIndex((event) => event.type === "guardian.incident");
    const state = replay(...events.slice(0, incidentIndex + 1));

    expect(state.incident?.dora.amountEur).toBe(85000);
    expect(state.incident?.simulated).toBe(true);
    expect(state.payment?.status).toBe("frozen");

    const reset = synthetic("session.reset", {}, state.lastSeq + 1);
    expect(reduce(state, reset).incident).toBeNull();
  });

  it("tracks a rail outage until the matching rail.up event", () => {
    const events = fixture("samples-scene5-outage");
    const downIndex = events.findIndex((event) => event.type === "rail.down");
    const upIndex = events.findIndex((event) => event.type === "rail.up");
    const down = replay(...events.slice(0, downIndex + 1));

    expect(down.rails.R3).toMatchObject({ routeId: "R3", simulated: true });
    expect(replay(...events.slice(0, upIndex + 1)).rails.R3).toBeUndefined();
  });

  it("keeps a kill switch across scenarios and clears it on session reset", () => {
    const killed = reduce(initialState, synthetic("killswitch.on", {
      adapter: "R3",
      name: "Euro stablecoin on Avalanche",
      reason: "2 refused legs",
      refusals: 2,
      revoked: [],
    }));
    const nextScenario = reduce(killed, synthetic("scenario.started", { scenario: "legit", speed: 1, auto: true }, 2));

    expect(nextScenario.killSwitch?.adapter).toBe("R3");
    expect(reduce(nextScenario, synthetic("session.reset", {}, 3)).killSwitch).toBeNull();
  });

  it("keeps mule-wave samples through the stopped follow-up payment", () => {
    const state = replay(...specFixture("samples-scene3-mule-wave"));

    expect(state.feed).toHaveLength(12);
    expect(state.scenario).toBe("mule_wave");
    expect(state.wave?.samples).toHaveLength(3);
    expect(state.wave?.cluster?.clusterId).toBeTruthy();
    expect(state.wave?.breaker?.breakerId).toBeTruthy();
    expect(state.payment).toMatchObject({
      paymentId: "PAY-2026-0002",
      status: "stopped",
    });

    const restarted = reduce(
      state,
      synthetic(
        "scenario.started",
        { scenario: "legit", speed: 1, auto: true },
        state.lastSeq + 1,
      ),
    );
    expect(restarted.scenario).toBe("legit");
    expect(restarted.wave).toBeNull();
    expect(restarted.feed).toHaveLength(1);
  });

  it("starts a fresh session for a backwards sequence and drops equal duplicates", () => {
    const prior = replay(...fixture("scene1-legit"));
    const backwards = synthetic(
      "payment.stopped",
      { headline: "Stopped", detail: "New engine session" },
      1,
    );
    const restarted = reduce(prior, backwards);

    expect(restarted.lastSeq).toBe(1);
    expect(restarted.mode).toEqual(prior.mode);
    expect(restarted.payment).toBeNull();
    expect(restarted.stopped?.detail).toBe("New engine session");
    expect(restarted.feed).toHaveLength(1);

    const duplicate = synthetic(
      "payment.stopped",
      { headline: "Ignored", detail: "Duplicate sequence" },
      restarted.lastSeq,
    );
    expect(reduce(restarted, duplicate)).toBe(restarted);
  });

  it.each([
    "samples-scene3-mule-wave",
    "samples-scene4-guardian",
    "samples-scene5-outage",
    "scene2b-swap-beneficiary",
    "scene2b-replay",
  ])("replays the %s demo fixture without dropping events", (name) => {
    const events = fixture(name);
    const state = replay(...events);
    const lastScenarioIndex = events.findLastIndex(
      (event) => event.type === "scenario.started",
    );
    const visibleEvents = events.slice(Math.max(0, lastScenarioIndex));
    const expectedFeedLength =
      name === "samples-scene3-mule-wave" ? events.length : visibleEvents.length;

    expect(events.length).toBeGreaterThan(0);
    expect(state.feed).toHaveLength(expectedFeedLength);
    expect(state.lastSeq).toBe(Math.max(...events.map((event) => event.seq)));
  });
});
