import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { SyloEvent } from "../events";
import { edgeStatus, FLOW_EDGES, flowLane, flowStatuses, narrate } from "../flow";
import type { FlowEdge, FlowNodeId } from "../flow";
import { initialState, reduce } from "../store";

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

function edgeById(id: string): FlowEdge {
  const edge = FLOW_EDGES.find((candidate) => candidate.id === id);
  if (!edge) throw new Error(`Unknown flow edge: ${id}`);
  return edge;
}

function status(state: ReturnType<typeof replay>, node: FlowNodeId) {
  return flowStatuses(state)[node];
}

function edge(state: ReturnType<typeof replay>, id: string) {
  return edgeStatus(edgeById(id), flowStatuses(state));
}

describe("payment flow", () => {
  it("starts with every node and edge idle and neutral narration", () => {
    const statuses = flowStatuses(initialState);

    expect(Object.values(statuses).every((value) => value === "idle")).toBe(true);
    expect(
      FLOW_EDGES.every((flowEdge) => edgeStatus(flowEdge, statuses) === "idle"),
    ).toBe(true);
    expect(narrate(initialState).tone).toBe("neutral");
  });

  it("replays the legitimate payment through the direct lane", () => {
    const state = replay(...fixture("scene1-legit"));
    const statuses = flowStatuses(state);

    expect(flowLane(state)).toBe("direct");
    expect(statuses).toMatchObject({
      payment: "done",
      norms: "done",
      risk: "done",
      sealDirect: "done",
      settle: "done",
      credited: "done",
      sealEscrow: "skipped",
      hold: "skipped",
      supplier: "skipped",
      stopped: "skipped",
    });
    expect(edge(state, "risk-direct")).toBe("done");
    expect(edge(state, "direct-settle")).toBe("done");
    expect(edge(state, "settle-credited")).toBe("done");
    expect(edge(state, "risk-escrow")).toBe("skipped");
    expect(edge(state, "supplier-credited")).toBe("skipped");
  });

  it("marks settlement as running after the first leg is sent", () => {
    const events = fixture("scene1-legit");
    const firstLegSent = events.findIndex((event) => event.type === "leg.sent");
    expect(firstLegSent).toBeGreaterThanOrEqual(0);

    const state = replay(...events.slice(0, firstLegSent + 1));

    expect(status(state, "settle")).toBe("running");
    expect(edge(state, "direct-settle")).toBe("active");
  });

  it("waits for supplier confirmation on the diverted escrow lane", () => {
    const state = replay(...fixture("scene2-diverted"));

    expect(flowLane(state)).toBe("escrow");
    expect(flowStatuses(state)).toMatchObject({
      risk: "warn",
      hold: "warn",
      supplier: "waiting",
      sealDirect: "skipped",
      settle: "skipped",
      credited: "idle",
      stopped: "idle",
    });
    expect(edge(state, "hold-supplier")).toBe("active");
  });

  it("marks the denied supplier path as failed", () => {
    const state = replay(
      ...fixture("scene2-diverted"),
      ...fixture("scene2-deny"),
    );

    expect(flowStatuses(state)).toMatchObject({
      supplier: "fail",
      stopped: "fail",
      credited: "skipped",
    });
    expect(edge(state, "supplier-stopped")).toBe("done");
    expect(edge(state, "supplier-credited")).toBe("skipped");
    expect(narrate(state).tone).toBe("danger");
  });

  it("credits the diverted payment after supplier confirmation", () => {
    const state = replay(
      ...fixture("scene2-diverted"),
      ...fixture("scene2-confirm"),
    );

    expect(flowStatuses(state)).toMatchObject({
      supplier: "done",
      credited: "done",
      stopped: "skipped",
    });
    expect(edge(state, "supplier-credited")).toBe("done");
  });

  it("narrates a rejected release attempt after denial", () => {
    const state = replay(
      ...fixture("scene2-diverted"),
      ...fixture("scene2-deny"),
      ...fixture("scene2b-release-revoked"),
    );
    const narration = narrate(state);

    expect(narration.tone).toBe("low");
    expect(narration.text).toContain("PaymentNotReleasable");
    expect(narration.text).toContain("release()");
  });

  it("narrates each attack by its own name", () => {
    const swap = narrate(replay(...fixture("scene2-diverted"), ...fixture("scene2b-swap-beneficiary")));
    expect(swap.text).toContain("CommitmentMismatch");
    expect(swap.text).not.toContain("release()");

    const replayed = narrate(replay(...fixture("scene2-diverted"), ...fixture("scene2b-replay")));
    expect(replayed.text).toContain("replayed");
    expect(replayed.text).not.toContain("release()");
  });

  it("takes the lane from the selected settlement, not from the tier", () => {
    const events = fixture("scene2-diverted");
    const scored = events.findIndex((event) => event.type === "risk.scored");
    const beforeRoute = replay(...events.slice(0, scored + 1));
    expect(beforeRoute.risk?.tier).not.toBe("LOW");
    expect(flowLane(beforeRoute)).toBeNull();
    expect(narrate(beforeRoute).text).not.toContain("escrow");

    const selected = events.findIndex((event) => event.type === "route.selected");
    const routed = replay(...events.slice(0, selected + 1));
    expect(flowLane(routed)).toBe("escrow");
    expect(narrate(routed).text).toContain("on-chain escrow");
  });
});
